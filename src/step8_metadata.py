"""
ステップ8（フェーズ2）: 商品メタデータ（タグ＋説明文）を収集する。

BOOTH の items/{id}.json が1リクエストで tags と description を返す。
これを全商品ぶん直列取得して data/product_meta.json に保存。
- tags: [{"name": ...}] → 名前だけのリストに整形
- description: フル説明文（「16アバター対応: ...」等の対応アバター情報を含む）

booth_client 経由なので直列・1〜2秒・キャッシュ・バックオフは自動。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from booth_client import BoothClient

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
OUT_FILE = ROOT / "data" / "product_meta.json"


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    meta: dict[str, dict] = {}
    if OUT_FILE.exists():
        meta = json.loads(OUT_FILE.read_text(encoding="utf-8"))

    client = BoothClient()
    total = len(products)
    t0 = time.time()

    for i, p in enumerate(products, 1):
        pid = p["product_id"]
        if pid in meta:  # 済みはスキップ
            continue
        url = f"https://booth.pm/ja/items/{pid}.json"
        try:
            raw = client.get_html(url)  # JSONだが中身はテキスト。キャッシュも効く
            data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{total}] {pid} 失敗: {e}", file=sys.stderr)
            meta[pid] = {"tags": [], "description": "", "error": True}
            continue
        tags = [t.get("name", "") for t in data.get("tags", []) if t.get("name")]
        meta[pid] = {
            "tags": tags,
            "description": data.get("description", "") or "",
        }
        if i % 20 == 0 or i == total:
            print(f"  [{i}/{total}] {i/(time.time()-t0)*60:.0f} 商品/分", file=sys.stderr, flush=True)
            OUT_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with_tags = sum(1 for m in meta.values() if m.get("tags"))
    with_desc = sum(1 for m in meta.values() if m.get("description"))
    print("\n" + "=" * 56)
    print(f"メタデータ収集完了: {len(meta)} 商品 -> {OUT_FILE.name}")
    print(f"  タグあり: {with_tags} / 説明文あり: {with_desc}")
    print("=" * 56)


if __name__ == "__main__":
    main()
