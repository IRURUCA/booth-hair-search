"""
ステップ12: より高精度な wd-eva02-large-tagger-v3 で全画像を再タグ付けする（A/B用）。

現行の swinv2 より精度が高い想定。出力は別ファイルにして比較できるようにする:
- data/hair_vectors_eva02.json

ネットワーク不要（images/ のローカル画像のみ）。CPU推論は swinv2 より遅い。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from hair_tags import build_hair_vocab
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "images"
MODEL_CACHE = ROOT / "cache" / "hf"
OUT_FILE = ROOT / "data" / "hair_vectors_eva02.json"
EVA02_REPO = "SmilingWolf/wd-eva02-large-tagger-v3"
HAIR_EPS = 0.05


def main() -> None:
    print("eva02-large タガーをロード中（初回はモデルDL ~1GB）...", file=sys.stderr, flush=True)
    tagger = WDTagger(cache_dir=MODEL_CACHE, repo=EVA02_REPO)
    vocab = build_hair_vocab(tagger.general_names)
    print(f"  入力{tagger.target_size}px / general {len(tagger.general_names)} / 髪語彙 {len(vocab)}", file=sys.stderr)

    result: dict[str, dict] = {}
    if OUT_FILE.exists():
        result = json.loads(OUT_FILE.read_text(encoding="utf-8"))

    imgs = sorted(IMAGES_DIR.glob("*.jpg"))
    t0 = time.time()
    for i, img in enumerate(imgs, 1):
        pid = img.stem
        if pid in result:
            continue
        try:
            g = tagger.tag_image(img)
            result[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= HAIR_EPS}
        except Exception as e:  # noqa: BLE001
            print(f"  {pid} 失敗: {e}", file=sys.stderr)
        if i % 50 == 0 or i == len(imgs):
            OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [{i}/{len(imgs)}] {i/(time.time()-t0):.1f} img/s", file=sys.stderr, flush=True)

    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"eva02 再タグ完了: {len(result)} 商品 -> {OUT_FILE.name}")


if __name__ == "__main__":
    main()
