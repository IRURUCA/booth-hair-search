"""
ステップ11: 各商品の統計（スキ数・公開日・正確な価格）を items/{id}.json から集める。

- wish_lists_count（スキ数）→ スキ順ソート用
- published_at（公開日時）→ 正確な新着順用（IDでも代理可）
- price（"¥ 1,000" 等）→ 正確な価格（一覧カードの0円誤りを補正できる）

booth_client 経由なので直列・1〜2秒・キャッシュ・バックオフ込み。508件は既にキャッシュ済み。
出力: data/product_stats.json = {pid: {wish, published_at, price}}
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from booth_client import BoothClient

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
OUT_FILE = ROOT / "data" / "product_stats.json"


def parse_price(price_str) -> int | None:
    if not price_str:
        return None
    nums = re.findall(r"\d[\d,]*", str(price_str))
    if not nums:
        return None
    return min(int(n.replace(",", "")) for n in nums)  # レンジなら最小


def extract_tags(d) -> list[str]:
    """items json の tags を名前リストに（アバター名等のキーワード検索に使う）。"""
    return [t.get("name", "") for t in (d.get("tags") or []) if t.get("name")]


def strip_desc(d, cap: int = 3000) -> str:
    """概要欄をキーワード検索用に整形（空白圧縮＋上限）。表示はしない。"""
    s = (d.get("description") or "").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:cap]


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    stats: dict[str, dict] = {}
    if OUT_FILE.exists():
        stats = json.loads(OUT_FILE.read_text(encoding="utf-8"))

    client = BoothClient()
    total = len(products)
    t0 = time.time()
    for i, p in enumerate(products, 1):
        pid = p["product_id"]
        s = stats.get(pid)
        if s is not None and s.get("tags") is not None and s.get("desc") is not None:
            continue  # 済み（tags・desc まで入っている）
        try:
            d = json.loads(client.get_html(f"https://booth.pm/ja/items/{pid}.json"))
            if s is None:
                stats[pid] = {
                    "wish": int(d.get("wish_lists_count") or 0),
                    "published_at": d.get("published_at") or "",
                    "price": parse_price(d.get("price")),
                    "tags": extract_tags(d),
                    "desc": strip_desc(d),
                }
            else:  # 既存statsにタグ・概要を追加（wish等の既存フィールドは保持）
                s["tags"] = extract_tags(d)
                s["desc"] = strip_desc(d)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{total}] {pid} 失敗: {e}", file=sys.stderr)
            if s is None:
                stats[pid] = {"wish": 0, "published_at": "", "price": None, "tags": [], "desc": ""}
            else:
                s.setdefault("tags", [])
                s["desc"] = ""
        if i % 20 == 0 or i == total:
            OUT_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [{i}/{total}] {i/(time.time()-t0)*60:.0f} 商品/分", file=sys.stderr, flush=True)

    OUT_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    wished = sum(1 for s in stats.values() if s.get("wish"))
    print(f"\n統計収集完了: {len(stats)} 商品 / スキ数あり {wished}")


if __name__ == "__main__":
    main()
