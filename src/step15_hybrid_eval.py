"""
ステップ15（実験）: ハイブリッド類似度の評価。

仮説: 髪形状100タグ＋IDF（現行）に、WDタガーの「全generalタグ」の
sparse ベクトル cosine を混ぜると、タグ語彙で表現しきれない見た目の
情報が乗って精度が上がるかもしれない。

比較する手法（23枚のevalで top-1/5/10）:
  base  : 現行 = 髪形状タグ + IDF cosine
  full  : 全generalタグ(conf>=0.05) cosine（髪以外の全情報。色・衣装込み）
  rrf   : base と full の Reciprocal Rank Fusion (k=60)
  blend : 0.5*minmax(base) + 0.5*minmax(full)

使い方:
  python src/step15_hybrid_eval.py build   # 全商品の全タグsparseベクトル生成(~12分)
  python src/step15_hybrid_eval.py eval    # 評価（buildが済んでいること）
生成物 data/tags_full.json は .gitignore 対象（data/tags*.json）。実験専用。
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
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
FULL_VECTORS_FILE = ROOT / "data" / "full_vectors.json"  # 配信対象（step13が差分維持）
IMAGES_DIR = ROOT / "images"
EVAL_DIR = ROOT / "eval"
MODEL_CACHE = ROOT / "cache" / "hf"
EPS = 0.05


def build() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    done = {}
    if FULL_VECTORS_FILE.exists():
        done = json.loads(FULL_VECTORS_FILE.read_text(encoding="utf-8"))
    todo = [p for p in products if p["product_id"] not in done
            and (IMAGES_DIR / f"{p['product_id']}.jpg").exists()]
    print(f"全タグベクトル生成: 済 {len(done)} / 残 {len(todo)}", file=sys.stderr, flush=True)
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    t0 = time.time()
    for i, p in enumerate(todo, 1):
        pid = p["product_id"]
        g = tagger.tag_image(IMAGES_DIR / f"{pid}.jpg")
        done[pid] = {t: round(c, 4) for t, c in g.items() if c >= EPS}
        if i % 100 == 0 or i == len(todo):
            FULL_VECTORS_FILE.write_text(json.dumps(done, ensure_ascii=False),
                                         encoding="utf-8")
            print(f"  [{i}/{len(todo)}] {i / max(time.time() - t0, 1) * 60:.0f} 商品/分",
                  file=sys.stderr, flush=True)
    FULL_VECTORS_FILE.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    print(f"完了: {len(done)} 商品", file=sys.stderr)


def _rank_of(order: list[str], answer: str) -> int:
    """answer の順位（1始まり）。無ければ大きな数。"""
    try:
        return order.index(answer) + 1
    except ValueError:
        return 10 ** 9


def evaluate() -> None:
    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)

    hv = json.loads(HAIR_VECTORS_FILE.read_text(encoding="utf-8"))
    fv = json.loads(FULL_VECTORS_FILE.read_text(encoding="utf-8"))
    pids = [pid for pid in hv if pid in fv]
    idx = {t: i for i, t in enumerate(vocab)}

    # 髪タグ行列 + IDF（matcher と同じ式）
    P = np.zeros((len(pids), len(vocab)), dtype=np.float32)
    for r, pid in enumerate(pids):
        for t, c in hv[pid].items():
            if t in idx:
                P[r, idx[t]] = c
    df = np.sum(P >= 0.2, axis=0)
    w = np.log((P.shape[0] + 1) / (df + 1)).astype(np.float32) + 1.0
    Pw = P * w
    Pn = Pw / (np.linalg.norm(Pw, axis=1, keepdims=True) + 1e-9)

    # 全タグ行列（出現タグの和集合を次元に）
    all_tags = sorted({t for v in fv.values() for t in v})
    fidx = {t: i for i, t in enumerate(all_tags)}
    F = np.zeros((len(pids), len(all_tags)), dtype=np.float32)
    for r, pid in enumerate(pids):
        for t, c in fv[pid].items():
            F[r, fidx[t]] = c
    Fn = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    print(f"商品 {len(pids)} / 髪語彙 {len(vocab)} / 全タグ次元 {len(all_tags)}",
          file=sys.stderr)

    evals = sorted(EVAL_DIR.glob("*.png")) + sorted(EVAL_DIR.glob("*.jpg"))
    scored = [f for f in evals if f.stem.split("_")[0].isdigit()]
    print(f"eval画像 {len(scored)} 枚（distractor除く）", file=sys.stderr)

    alphas = [0.3, 0.4, 0.5, 0.6, 0.7]  # blend の base 側重み（ロバスト性確認）
    methods = ["base", "full", "rrf"] + [f"blend{a:.1f}" for a in alphas]
    ranks: dict[str, list[int]] = {m: [] for m in methods}
    for f in scored:
        answer = f.stem.split("_")[0]
        g = tagger.tag_image(f)
        # base クエリ（現行UIと同じ: 全confidences thresh 0.05）
        q = np.zeros(len(vocab), dtype=np.float32)
        for t, c in g.items():
            if t in idx and c >= EPS:
                q[idx[t]] = c
        qw = q * w
        qn = qw / (np.linalg.norm(qw) + 1e-9)
        s_base = Pn @ qn
        # full クエリ
        qf = np.zeros(len(all_tags), dtype=np.float32)
        for t, c in g.items():
            if t in fidx and c >= EPS:
                qf[fidx[t]] = c
        qfn = qf / (np.linalg.norm(qf) + 1e-9)
        s_full = Fn @ qfn

        order_base = [pids[i] for i in np.argsort(-s_base)]
        order_full = [pids[i] for i in np.argsort(-s_full)]
        # RRF
        rb = {pid: r for r, pid in enumerate(order_base, 1)}
        rf = {pid: r for r, pid in enumerate(order_full, 1)}
        s_rrf = {pid: 1 / (60 + rb[pid]) + 1 / (60 + rf[pid]) for pid in pids}
        order_rrf = sorted(pids, key=lambda p: -s_rrf[p])
        # blend（重みを振ってロバスト性を見る）
        def mm(x):
            lo, hi = float(x.min()), float(x.max())
            return (x - lo) / (hi - lo + 1e-9)
        orders = [("base", order_base), ("full", order_full), ("rrf", order_rrf)]
        for a in alphas:
            s_blend = a * mm(s_base) + (1 - a) * mm(s_full)
            orders.append((f"blend{a:.1f}", [pids[i] for i in np.argsort(-s_blend)]))

        for m, order in orders:
            ranks[m].append(_rank_of(order, answer))
        print(f"  {f.name}: " + " ".join(f"{m}={ranks[m][-1]}" for m, _ in orders),
              file=sys.stderr, flush=True)

    n = len(scored)
    print("\n手法      top-1  top-5  top-10  (n=%d)" % n)
    for m in methods:
        r = ranks[m]
        print(f"{m:8s}  {sum(x <= 1 for x in r) / n:5.0%}  "
              f"{sum(x <= 5 for x in r) / n:5.0%}  {sum(x <= 10 for x in r) / n:6.0%}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if mode == "build":
        build()
    else:
        evaluate()
