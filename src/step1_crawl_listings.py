"""
ステップ1-1: BOOTH「3D髪型」カテゴリの商品リストを取得する。

取得フィールド: 商品ID / 商品名 / 商品URL / サムネイル画像URL / ショップ名 / 価格
（+ 補助シグナルとして VRChat 対応バッジの有無、ショップURL）

注: 説明文（description）は一覧カードには無く商品ページにしか存在しないため、
このステップでは取らない。必要なら別途 per-item のパスで取得する。

一覧ページ 1 ページ = 60 件。500 件 ≒ 9 ページのみ取得するので footprint は軽い。
結果は data/products.json に保存。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from booth_client import BoothClient

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "products.json"

# 「3D髪型」= URLエンコードで 3D%E9%AB%AA%E5%9E%8B
CATEGORY_URL = "https://booth.pm/ja/browse/3D%E9%AB%AA%E5%9E%8B"
TARGET_COUNT = 500
PER_PAGE = 60


def parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    products = []
    for li in soup.select("li.item-card[data-product-id]"):
        pid = li.get("data-product-id")
        if not pid:
            continue

        # 商品名: タイトルアンカーの全文（data-product-name は省略されている）
        title_a = li.select_one("a.item-card__title-anchor--multiline") or li.select_one(
            ".item-card__title a"
        )
        name = title_a.get_text(strip=True) if title_a else (li.get("data-product-name") or "")

        # 商品URL
        url = title_a["href"] if title_a and title_a.has_attr("href") else f"https://booth.pm/ja/items/{pid}"

        # サムネイル: 最初の js-thumbnail-image の data-original
        thumb_a = li.select_one("a.js-thumbnail-image[data-original]")
        thumb_url = thumb_a["data-original"] if thumb_a else None

        # ショップ名 / URL
        shop_name_el = li.select_one(".item-card__shop-name")
        shop_name = shop_name_el.get_text(strip=True) if shop_name_el else None
        shop_a = li.select_one("a.item-card__shop-name-anchor")
        shop_url = shop_a["href"] if shop_a and shop_a.has_attr("href") else None

        # 価格: data 属性が最も確実
        price = li.get("data-product-price")
        price = int(price) if price and price.isdigit() else None

        # VRChat 対応バッジ（Phase 2 の対応アバター絞り込みの補助シグナル）
        has_vrchat_badge = li.select_one('img[src*="badges/vrchat"]') is not None

        products.append(
            {
                "product_id": pid,
                "name": name,
                "url": url,
                "thumbnail_url": thumb_url,
                "shop_name": shop_name,
                "shop_url": shop_url,
                "price": price,
                "has_vrchat_badge": has_vrchat_badge,
            }
        )
    return products


def main() -> None:
    client = BoothClient()
    collected: dict[str, dict] = {}  # product_id -> product (重複排除)
    page = 1

    while len(collected) < TARGET_COUNT:
        url = f"{CATEGORY_URL}?sort=new&page={page}"
        print(f"[page {page}] fetching {url}", file=sys.stderr, flush=True)
        html = client.get_html(url)
        page_products = parse_listing_page(html)
        if not page_products:
            print(f"[page {page}] 0 件。ページ末尾に到達したとみなして終了。", file=sys.stderr)
            break
        for p in page_products:
            collected.setdefault(p["product_id"], p)
        print(f"  -> このページ {len(page_products)} 件 / 累計ユニーク {len(collected)} 件", file=sys.stderr)
        page += 1

    products = list(collected.values())[:TARGET_COUNT]

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- レポート ---
    with_thumb = sum(1 for p in products if p["thumbnail_url"])
    with_vrc = sum(1 for p in products if p["has_vrchat_badge"])
    print("\n" + "=" * 60)
    print(f"取得完了: {len(products)} 件を {OUT_FILE} に保存")
    print(f"  サムネイルURLあり: {with_thumb} / {len(products)}")
    print(f"  VRChatバッジあり: {with_vrc} / {len(products)}")
    print(f"  取得ページ数: {page - 1}")
    print("=" * 60)
    print("\n--- 最初の5件 ---")
    for p in products[:5]:
        print(json.dumps(p, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
