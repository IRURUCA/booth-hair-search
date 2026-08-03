"""
ステップ5（品質向上）: 1商品を複数画像でタグ付けし、タグを max 集約する。

BOOTHのサムネ1枚目は加工バチバチの宣伝カードで髪を読みにくいが、商品ページの
2枚目以降には Unity画面のスクショ・改変例・カラバリ・細部など「素の描画」があり、
そちらの方が髪の形状を正確に拾える（PoCで実証済み）。

- 各商品ページ(items/{id})から全画像URL(data-origin)を取得
- resized(300x300, jpg)を最大 MAX_IMAGES 枚だけ取得（商品本体ファイルは絶対に触らない）
- 各画像を WD Tagger にかけ、髪形状タグの確信度を max 集約
- 結果を data/hair_vectors_multi.json に保存

booth_client 経由なので直列・1〜2秒・キャッシュ・バックオフは自動で効く。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from booth_client import BoothClient
from hair_tags import build_hair_vocab
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
IMAGES_MULTI_DIR = ROOT / "images_multi"
MODEL_CACHE = ROOT / "cache" / "hf"
OUT_FILE = ROOT / "data" / "hair_vectors_multi.json"

MAX_IMAGES = 6          # 1商品あたり最大何枚タグ付けするか
HAIR_EPS = 0.05


def extract_image_urls(html: str, pid: str) -> list[str]:
    """商品ページHTMLから、その商品の画像URL(data-origin)を出現順・重複除去で返す。"""
    origins = re.findall(r'data-origin="([^"]+)"', html)
    return [u for u in dict.fromkeys(origins) if f"/i/{pid}/" in u]


def resized_url(orig: str, size: int = 300) -> str:
    """原寸URL -> resized(サムネ相当, 軽量jpg)URL。"""
    m = re.match(r'(https://booth\.pximg\.net)/(.+/i/\d+/[^.]+)\.\w+', orig)
    if not m:
        return orig
    return f"{m.group(1)}/c/{size}x{size}_a2_g5/{m.group(2)}_base_resized.jpg"


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    IMAGES_MULTI_DIR.mkdir(parents=True, exist_ok=True)

    # 既存の結果があれば読み込んで再開（同じURLを二度取りに行かない方針）
    result: dict[str, dict[str, float]] = {}
    if OUT_FILE.exists():
        result = json.loads(OUT_FILE.read_text(encoding="utf-8"))

    client = BoothClient()
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)

    total = len(products)
    img_counts: list[int] = []
    t0 = time.time()

    for i, p in enumerate(products, 1):
        pid = p["product_id"]
        if pid in result:  # 済みはスキップ（キャッシュ再開）
            continue
        try:
            html = client.get_html(p["url"])
            urls = extract_image_urls(html, pid)[:MAX_IMAGES]
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{total}] {pid} ページ取得失敗: {e}", file=sys.stderr)
            continue

        agg: dict[str, float] = {}
        n_ok = 0
        pdir = IMAGES_MULTI_DIR / pid
        for j, o in enumerate(urls, 1):
            dest = pdir / f"{j}.jpg"
            try:
                client.get_image(resized_url(o), dest)
                g = tagger.tag_image(dest)
                for t_ in vocab:
                    c = g.get(t_, 0.0)
                    if c > agg.get(t_, 0.0):
                        agg[t_] = c
                n_ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"    {pid} img{j} 失敗: {e}", file=sys.stderr)

        result[pid] = {t_: round(c, 4) for t_, c in agg.items() if c >= HAIR_EPS}
        img_counts.append(n_ok)

        if i % 20 == 0 or i == total:
            rate = i / (time.time() - t0)
            avg = sum(img_counts) / max(len(img_counts), 1)
            print(f"  [{i}/{total}] {rate*60:.0f} 商品/分, 平均 {avg:.1f} 枚/商品", file=sys.stderr, flush=True)
            OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"マルチ画像タグ付け完了: {len(result)} 商品 -> {OUT_FILE.name}")
    if img_counts:
        print(f"  平均画像枚数: {sum(img_counts)/len(img_counts):.1f} 枚/商品（このrun分）")
    print("=" * 60)


if __name__ == "__main__":
    main()
