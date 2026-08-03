"""
ステップ6: マルチ画像の「賢い集約」を比較する。

step5 で商品ごとに落とした images_multi/{id}/*.jpg を1枚ずつタグ付けし、
複数の集約方法で商品ベクトルを作る。ネットワーク不要（ローカル画像のみ）。

集約方法:
- max     : 各タグ、全画像の最大（step5と同じ。平凡タグを底上げしやすい）
- mean    : 平均（底上げを抑制）
- best    : 髪タグ確信度の合計が最大の「1枚」だけ採用（宣伝カードを自動で捨てる）
- cons2   : 各タグ2番目に高い確信度（=2枚以上で立ったタグを重視、単発ノイズ除去）

出力: data/hair_vectors_multi_{max,mean,best,cons2}.json
per-image タグは data/multi_per_image.json にも保存（再実験で再タグ不要にする）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from hair_tags import build_hair_vocab
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
IMAGES_MULTI_DIR = ROOT / "images_multi"
SINGLE_VECTORS = ROOT / "data" / "hair_vectors.json"
MODEL_CACHE = ROOT / "cache" / "hf"
PER_IMAGE_FILE = ROOT / "data" / "multi_per_image.json"
HAIR_EPS = 0.05


def aggregate(per_img: list[dict[str, float]], vocab: list[str], method: str) -> dict[str, float]:
    if not per_img:
        return {}
    M = np.array([[d.get(t, 0.0) for t in vocab] for d in per_img], dtype=np.float32)  # (n_img, n_tag)
    if method == "max":
        v = M.max(axis=0)
    elif method == "mean":
        v = M.mean(axis=0)
    elif method == "best":
        best = int(np.argmax(M.sum(axis=1)))  # 髪タグ総量が最大の画像
        v = M[best]
    elif method == "cons2":
        # 各タグ、上位2番目の値（画像1枚なら its own値）
        s = np.sort(M, axis=0)[::-1]
        v = s[1] if M.shape[0] >= 2 else s[0]
    else:
        raise ValueError(method)
    return {vocab[i]: round(float(v[i]), 4) for i in range(len(vocab)) if v[i] >= HAIR_EPS}


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    single = json.loads(SINGLE_VECTORS.read_text(encoding="utf-8"))
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)
    vset = set(vocab)

    # per-image タグ（キャッシュ再開）
    per_image: dict[str, list[dict[str, float]]] = {}
    if PER_IMAGE_FILE.exists():
        per_image = json.loads(PER_IMAGE_FILE.read_text(encoding="utf-8"))

    t0 = time.time()
    total = len(products)
    for i, p in enumerate(products, 1):
        pid = p["product_id"]
        if pid in per_image:
            continue
        imgs = sorted((IMAGES_MULTI_DIR / pid).glob("*.jpg"))
        tags_per_img = []
        for img in imgs:
            try:
                g = tagger.tag_image(img)
                tags_per_img.append({t: round(g[t], 4) for t in vset if g.get(t, 0.0) >= HAIR_EPS})
            except Exception as e:  # noqa: BLE001
                print(f"  {pid}/{img.name} 失敗: {e}", file=sys.stderr)
        per_image[pid] = tags_per_img
        if i % 25 == 0 or i == total:
            print(f"  [{i}/{total}] {i/(time.time()-t0):.1f} 商品/s", file=sys.stderr, flush=True)
            PER_IMAGE_FILE.write_text(json.dumps(per_image, ensure_ascii=False), encoding="utf-8")

    PER_IMAGE_FILE.write_text(json.dumps(per_image, ensure_ascii=False), encoding="utf-8")

    # 4種の集約DBを書き出す。画像が無い商品は単一DBにフォールバック
    for method in ("max", "mean", "best", "cons2"):
        db = {}
        for pid, imgs in per_image.items():
            if imgs:
                db[pid] = aggregate(imgs, vocab, method)
            elif pid in single:
                db[pid] = single[pid]
        out = ROOT / "data" / f"hair_vectors_multi_{method}.json"
        out.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {out.name}: {len(db)} 商品", file=sys.stderr)

    print("完了。step6_compare.py で比較してください。", file=sys.stderr)


if __name__ == "__main__":
    main()
