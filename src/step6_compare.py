"""
ステップ6の比較: 各商品DB（single / multi_max / mean / best / cons2）を、
IDFあり・なしで評価し、top-1/5/10 ヒット率を一覧する。

入力(eval/)は単一画像のまま。商品側の表現だけを差し替えて効果を見る。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

from hair_tags import build_hair_vocab
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
MODEL_CACHE = ROOT / "cache" / "hf"

DBS = {
    "single":      ROOT / "data" / "hair_vectors.json",
    "multi_max":   ROOT / "data" / "hair_vectors_multi_max.json",
    "multi_mean":  ROOT / "data" / "hair_vectors_multi_mean.json",
    "multi_best":  ROOT / "data" / "hair_vectors_multi_best.json",
    "multi_cons2": ROOT / "data" / "hair_vectors_multi_cons2.json",
}


def main() -> None:
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)

    def vec(d):
        return np.array([d.get(x, 0.0) for x in vocab], dtype=np.float32)

    evals = sorted(f for f in glob.glob(str(ROOT / "eval" / "*"))
                   if not os.path.basename(f).startswith("x_")
                   and os.path.splitext(f)[1].lower() in (".png", ".jpg", ".jpeg", ".webp"))
    # 入力タグは一度だけ計算
    queries = [(os.path.basename(f).split("_")[0].split(".")[0], vec(tagger.tag_image(Path(f))))
               for f in evals]
    n = len(queries)

    def evaluate(db_file: Path, idf: bool):
        db = json.loads(db_file.read_text(encoding="utf-8"))
        pids = list(db.keys())
        P = np.stack([vec(db[p]) for p in pids])
        w = np.ones(len(vocab), dtype=np.float32)
        if idf:
            dfreq = np.sum(P >= 0.2, axis=0)
            w = np.log((P.shape[0] + 1) / (dfreq + 1)).astype(np.float32) + 1
        Pn = P * w
        Pn = Pn / (np.linalg.norm(Pn, axis=1, keepdims=True) + 1e-9)
        h = {1: 0, 5: 0, 10: 0}
        for cid, q in queries:
            if cid not in pids:
                continue
            qq = q * w
            sims = Pn @ (qq / (np.linalg.norm(qq) or 1.0))
            r = int((np.argsort(-sims) == pids.index(cid)).argmax()) + 1
            for k in (1, 5, 10):
                if r <= k:
                    h[k] += 1
        return h

    print(f"評価画像: {n} 枚（採点用）\n")
    print(f"{'config':16} {'IDF':>4} | top-1   top-5   top-10")
    print("-" * 48)
    best = None
    for name, f in DBS.items():
        if not f.exists():
            print(f"{name:16}  --  | (未生成)")
            continue
        for idf in (False, True):
            h = evaluate(f, idf)
            line = f"{name:16} {'on' if idf else 'off':>4} | {h[1]/n*100:4.0f}%  {h[5]/n*100:4.0f}%  {h[10]/n*100:5.0f}%"
            print(line)
            score = (h[10], h[5], h[1])
            if best is None or score > best[0]:
                best = (score, name, idf, h)
    (sc, name, idf, h) = best
    print("-" * 48)
    print(f"★ ベスト: {name} (IDF {'on' if idf else 'off'}) "
          f"→ top-1 {h[1]}/{n} top-5 {h[5]}/{n} top-10 {h[10]}/{n}")


if __name__ == "__main__":
    main()
