"""
ステップ13（フェーズ3-1）: 差分更新。新着の新商品だけを取り込む（自動更新用）。

- 「3D髪型」新着ページを上から見て、products.json に無い新商品を集める
- あるページが「全て既知」になったら、それ以降は古い商品なので早期終了
- 新商品のみ: サムネDL（一時利用）→ タグ抽出 → hair_vectors に追記、stats も取得
- 既存商品の stats（スキ数・価格）は毎回 REFRESH_BATCH 件ずつ古い順に再取得
  （ローテーション。404 が返った商品は削除済みとして DB から剪定する）
- 既存の data/*.json を非破壊マージ。画像はコミットしない（.gitignore）

GitHub Actions で定期実行する想定。クロールは booth_client が直列・低負荷・UA明記。
一覧ページと stats 再取得は鮮度が本質なので fresh=True（キャッシュを読まない）で取得する。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from booth_client import BoothClient, CrawlStop
from hair_tags import build_hair_vocab
from step1_crawl_listings import CATEGORY_URL, parse_listing_page
from step11_stats import extract_tags, parse_price, strip_desc
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
STATS_FILE = ROOT / "data" / "product_stats.json"
IMAGES_DIR = ROOT / "images"
MODEL_CACHE = ROOT / "cache" / "hf"
HAIR_EPS = 0.05
# 全既知ページで早期終了するので、この上限に達するのは大量新着時のみ。
# 40ページ ≒ 2,400件までカバー（週1実行での取りこぼしを防ぐ安全上限）。
MAX_SCAN_PAGES = 40
# 既存商品の stats を1回の実行で再取得する件数（古い順ローテーション）。
# 150件 × 週1 → 全 ~2,100件が約3.5ヶ月で一巡する。
REFRESH_BATCH = 150


def _fetch_stats(client: BoothClient, pid: str, fresh: bool = False) -> dict:
    d = json.loads(client.get_html(f"https://booth.pm/ja/items/{pid}.json", fresh=fresh))
    return {
        "wish": int(d.get("wish_lists_count") or 0),
        "published_at": d.get("published_at") or "",
        "price": parse_price(d.get("price")),
        "tags": extract_tags(d),  # 商品名＋タグのキーワード検索用
        "desc": strip_desc(d),    # 概要欄（キーワード検索用・非表示）
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _is_404(e: Exception) -> bool:
    return (isinstance(e, requests.HTTPError)
            and e.response is not None and e.response.status_code == 404)


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    by_id = {p["product_id"]: p for p in products}
    known = set(by_id)
    client = BoothClient()

    # --- 新着ページを走査して新商品を集める（全既知ページで早期終了）---
    new_products: list[dict] = []
    for page in range(1, MAX_SCAN_PAGES + 1):
        # 一覧は鮮度が本質 → キャッシュを読まず取得（レート制御は通常どおり）
        html = client.get_html(f"{CATEGORY_URL}?sort=new&page={page}", fresh=True)
        page_products = parse_listing_page(html)
        if not page_products:
            break
        page_new = [p for p in page_products if p["product_id"] not in known]
        print(f"[p{page}] 新規 {len(page_new)}/{len(page_products)}", file=sys.stderr, flush=True)
        for p in page_new:
            by_id[p["product_id"]] = p
            known.add(p["product_id"])
            new_products.append(p)
        if not page_new:  # このページが全て既知＝これ以降は古い → 終了
            break

    hair_vectors = json.loads(HAIR_VECTORS_FILE.read_text(encoding="utf-8"))
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8")) if STATS_FILE.exists() else {}

    # --- 新商品のタグ付け＋stats ---
    ok = 0
    if new_products:
        tagger = WDTagger(cache_dir=MODEL_CACHE)
        vocab = build_hair_vocab(tagger.general_names)
        for p in new_products:
            pid = p["product_id"]
            try:
                if p.get("thumbnail_url"):
                    dest = IMAGES_DIR / f"{pid}.jpg"
                    client.get_image(p["thumbnail_url"], dest)
                    g = tagger.tag_image(dest)
                    hair_vectors[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= HAIR_EPS}
                stats[pid] = _fetch_stats(client, pid)
                ok += 1
            except CrawlStop:
                raise  # 連続失敗 → 約束どおり止まって報告
            except Exception as e:  # noqa: BLE001
                print(f"  {pid} 失敗: {e}", file=sys.stderr)

    # --- 既存商品の stats ローテーション更新（古い順に REFRESH_BATCH 件）---
    #     404 = 削除・非公開になった商品 → DB から剪定（リンク切れとスキ数陳腐化の対策）
    new_ids = {p["product_id"] for p in new_products}
    existing = [pid for pid in by_id if pid not in new_ids]
    existing.sort(key=lambda pid: stats.get(pid, {}).get("checked_at", ""))  # 未記録が最古
    refreshed, pruned = 0, []
    for pid in existing[:REFRESH_BATCH]:
        try:
            stats[pid] = _fetch_stats(client, pid, fresh=True)
            refreshed += 1
        except CrawlStop:
            raise  # 連続失敗 → 約束どおり止まって報告
        except Exception as e:  # noqa: BLE001
            if _is_404(e):
                pruned.append(pid)
                by_id.pop(pid, None)
                hair_vectors.pop(pid, None)
                stats.pop(pid, None)
                print(f"  {pid} は404（削除済み）→ 剪定", file=sys.stderr)
            else:
                print(f"  {pid} stats更新失敗: {e}", file=sys.stderr)

    if not new_products and not refreshed and not pruned:
        print("変更なし。更新スキップ。")
        return

    products = list(by_id.values())
    PRODUCTS_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    HAIR_VECTORS_FILE.write_text(json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"更新完了: 新商品 {len(new_products)} 件（タグ済み {ok}）"
          f"/ stats再取得 {refreshed} 件 / 剪定 {len(pruned)} 件 / 総数 {len(products)}")


if __name__ == "__main__":
    main()
