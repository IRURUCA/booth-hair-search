"""
ステップ1-3: images/ の各画像に WD Tagger v3 を適用してタグを抽出する。

出力:
- data/tags.json        : 各商品の general タグ（conf >= THRESHOLD）辞書。人間の目視確認用
- data/hair_vocab.json  : 髪形状タグの語彙（照合ベクトルの次元。ステップ1-4 と共有）
- data/hair_vectors.json: 各商品の髪形状タグ確信度（語彙全次元、色・アクセサリ除外）

最後に 10 件分のタグ出力（商品名つき）を表示して停止する。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from hair_tags import build_hair_vocab, is_hair_shape_tag
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "images"
PRODUCTS_FILE = ROOT / "data" / "products.json"
MODEL_CACHE = ROOT / "cache" / "hf"

HAIR_VOCAB_FILE = ROOT / "data" / "hair_vocab.json"

# 目視確認用の一般タグ表示しきい値
THRESHOLD = 0.35
# 髪ベクトルに残す最小確信度（これ未満は 0 とみなして疎に保存）
HAIR_EPS = 0.05


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", action="store_true",
                    help="頭部クロップ（チューニング①）を適用して抽出する")
    args = ap.parse_args()

    # クロップ版は別ファイルに出して no-crop と A/B 比較できるようにする
    suffix = "_crop" if args.crop else ""
    tags_file = ROOT / "data" / f"tags{suffix}.json"
    hair_vectors_file = ROOT / "data" / f"hair_vectors{suffix}.json"

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    name_by_id = {p["product_id"]: p["name"] for p in products}

    print(f"WD Tagger v3 をロード中（crop={args.crop}）...", file=sys.stderr, flush=True)
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    print(f"  入力サイズ: {tagger.target_size}px / general タグ数: {len(tagger.general_names)}", file=sys.stderr)

    hair_vocab = build_hair_vocab(tagger.general_names)
    print(f"  髪形状タグ語彙: {len(hair_vocab)} 次元", file=sys.stderr)

    image_files = sorted(IMAGES_DIR.glob("*.jpg"))
    print(f"  対象画像: {len(image_files)} 枚", file=sys.stderr)

    tags_all: dict[str, dict[str, float]] = {}
    hair_vectors: dict[str, dict[str, float]] = {}

    t0 = time.time()
    for i, img_path in enumerate(image_files, 1):
        pid = img_path.stem
        try:
            general = tagger.tag_image(img_path, crop=args.crop)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}] {pid} 失敗: {e}", file=sys.stderr)
            continue

        # 目視用: しきい値以上の general タグ
        tags_all[pid] = {t: round(c, 4) for t, c in general.items() if c >= THRESHOLD}
        # 照合用: 髪形状タグの確信度（色・アクセサリ除外、EPS 以上を保存）
        hair_vectors[pid] = {
            t: round(general.get(t, 0.0), 4)
            for t in hair_vocab
            if general.get(t, 0.0) >= HAIR_EPS
        }

        if i % 25 == 0 or i == len(image_files):
            rate = i / (time.time() - t0)
            print(f"  [{i}/{len(image_files)}] {rate:.1f} img/s", file=sys.stderr, flush=True)

    tags_file.write_text(json.dumps(tags_all, ensure_ascii=False, indent=2), encoding="utf-8")
    HAIR_VOCAB_FILE.write_text(json.dumps(hair_vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    hair_vectors_file.write_text(json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"タグ抽出完了: {len(tags_all)} 件 (crop={args.crop})")
    print(f"  {tags_file.name} / hair_vocab.json({len(hair_vocab)}次元) / {hair_vectors_file.name}")
    print("=" * 70)

    # --- 10件分のタグ出力（目視確認用）---
    print("\n### 10件のタグ出力（この内容が商品画像と合っているか目視してください）\n")
    for pid in list(tags_all.keys())[:10]:
        name = name_by_id.get(pid, "?")
        general = tags_all[pid]
        top_general = sorted(general.items(), key=lambda x: -x[1])[:12]
        hair = sorted(hair_vectors[pid].items(), key=lambda x: -x[1])
        print(f"■ {pid}  {name}")
        print(f"   URL: https://booth.pm/ja/items/{pid}")
        print("   一般タグ:", ", ".join(f"{t}={c}" for t, c in top_general))
        print("   ★髪形状タグ:", ", ".join(f"{t}={c}" for t, c in hair) or "(なし)")
        print()


if __name__ == "__main__":
    main()
