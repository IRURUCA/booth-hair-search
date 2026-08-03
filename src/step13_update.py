"""
ステップ13（フェーズ3-1）: 差分更新。新着の新商品だけを取り込む（自動更新用）。

- 「3D髪型」新着ページを上から見て、products.json に無い新商品を集める
- あるページが「全て既知」になったら、それ以降は古い商品なので早期終了
- 新商品のみ: サムネDL（一時利用）→ タグ抽出 → hair_vectors に追記、stats も取得
- 既存の data/*.json を非破壊マージ。画像はコミットしない（.gitignore）

GitHub Actions で定期実行する想定。クロールは booth_client が直列・低負荷・UA明記。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from booth_client import BoothClient
from hair_tags import build_hair_vocab
from step1_crawl_listings import CATEGORY_URL, parse_listing_page
from step11_stats import parse_price
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
STATS_FILE = ROOT / "data" / "product_stats.json"
IMAGES_DIR = ROOT / "images"
MODEL_CACHE = ROOT / "cache" / "hf"
HAIR_EPS = 0.05
MAX_SCAN_PAGES = 10  # 新着をこのページ数まで確認（差分なので通常は数ページで足りる）


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    by_id = {p["product_id"]: p for p in products}
    known = set(by_id)
    client = BoothClient()

    # --- 新着ページを走査して新商品を集める（全既知ページで早期終了）---
    new_products: list[dict] = []
    for page in range(1, MAX_SCAN_PAGES + 1):
        html = client.get_html(f"{CATEGORY_URL}?sort=new&page={page}")
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

    if not new_products:
        print("新商品なし。更新スキップ。")
        return

    # --- 新商品のタグ付け＋stats ---
    hair_vectors = json.loads(HAIR_VECTORS_FILE.read_text(encoding="utf-8"))
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8")) if STATS_FILE.exists() else {}
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)

    ok = 0
    for i, p in enumerate(new_products, 1):
        pid = p["product_id"]
        try:
            if p.get("thumbnail_url"):
                dest = IMAGES_DIR / f"{pid}.jpg"
                client.get_image(p["thumbnail_url"], dest)
                g = tagger.tag_image(dest)
                hair_vectors[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= HAIR_EPS}
            d = json.loads(client.get_html(f"https://booth.pm/ja/items/{pid}.json"))
            stats[pid] = {"wish": int(d.get("wish_lists_count") or 0),
                          "published_at": d.get("published_at") or "",
                          "price": parse_price(d.get("price"))}
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {pid} 失敗: {e}", file=sys.stderr)

    products = list(by_id.values())
    PRODUCTS_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    HAIR_VECTORS_FILE.write_text(json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"更新完了: 新商品 {len(new_products)} 件（タグ済み {ok}）/ 総数 {len(products)}")


if __name__ == "__main__":
    main()
