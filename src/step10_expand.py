"""
ステップ10（フェーズ2-1）: DBを条件つきで拡張する（マージ型・非破壊）。

- 「3D髪型」カテゴリを新着順にさらに辿り、TARGET 件まで商品を増やす
- 既存の products.json / hair_vectors.json は壊さずマージ（評価の追加正解商品も保持）
- 新規商品だけ: サムネDL → タグ抽出 → hair_vectors.json に追記
- クロール規則（直列・1〜2秒・キャッシュ・UA明記）は booth_client が担保
- 途中で止めても、再実行すれば続きから（キャッシュ＆済みスキップ）

使い方: python src/step10_expand.py [TARGET]   (既定 1200)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from booth_client import BoothClient
from hair_tags import build_hair_vocab
from step1_crawl_listings import CATEGORY_URL, parse_listing_page
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
IMAGES_DIR = ROOT / "images"
MODEL_CACHE = ROOT / "cache" / "hf"
HAIR_EPS = 0.05
MAX_PAGES = 40  # 保険。カテゴリは約36ページ


def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1200

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    by_id = {p["product_id"]: p for p in products}
    client = BoothClient()

    # --- 1) 新着順にページを辿って商品をマージ（TARGET件まで）---
    page = 1
    while len(by_id) < target and page <= MAX_PAGES:
        url = f"{CATEGORY_URL}?sort=new&page={page}"
        print(f"[listing p{page}] 現在 {len(by_id)} 件", file=sys.stderr, flush=True)
        html = client.get_html(url)
        page_products = parse_listing_page(html)
        if not page_products:
            print("  ページ末尾に到達。", file=sys.stderr)
            break
        for p in page_products:
            by_id.setdefault(p["product_id"], p)
        page += 1

    products = list(by_id.values())
    PRODUCTS_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"商品マージ完了: {len(products)} 件", file=sys.stderr)

    # --- 2) 新規サムネDL + タグ抽出（既存はスキップ）---
    hair_vectors = json.loads(HAIR_VECTORS_FILE.read_text(encoding="utf-8"))
    todo = [p for p in products if p["product_id"] not in hair_vectors]
    print(f"タグ未取得の新規商品: {len(todo)} 件", file=sys.stderr)

    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)

    t0 = time.time()
    ok = 0
    for i, p in enumerate(todo, 1):
        pid = p["product_id"]
        url = p.get("thumbnail_url")
        if not url:
            continue
        dest = IMAGES_DIR / f"{pid}.jpg"
        try:
            client.get_image(url, dest)
            g = tagger.tag_image(dest)
            hair_vectors[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= HAIR_EPS}
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {pid} 失敗: {e}", file=sys.stderr)
        if i % 25 == 0 or i == len(todo):
            HAIR_VECTORS_FILE.write_text(json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [{i}/{len(todo)}] 新規タグ {ok} 件 / {i/(time.time()-t0)*60:.0f} 商品/分", file=sys.stderr, flush=True)

    HAIR_VECTORS_FILE.write_text(json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 56)
    print(f"DB拡張完了: 商品 {len(products)} 件 / タグ済み {len(hair_vectors)} 件（新規 {ok}）")
    print("=" * 56)


if __name__ == "__main__":
    main()
