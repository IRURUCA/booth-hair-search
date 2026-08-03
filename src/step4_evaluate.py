"""
ステップ1-4: 評価用画像で精度（top-1/5/10 ヒット率）を測る。

- eval/ の画像（ファイル名 = 正解の商品ID_連番.png）に同じタガーを適用
- 髪形状タグ確信度ベクトル（色・アクセサリ除外）を作り、
  products の髪ベクトルとコサイン類似度で照合
- 各評価画像について top-10 を出力
- ファイル名の正解IDが top-1 / top-5 / top-10 に入るかを集計してヒット率を表示

重要な公平性の注意:
  500件は「新着」の髪型商品なので、評価画像の正解商品がDBに無いことがある。
  正解がDBに無ければ top-k は原理的に当たらない。
  --augment を付けると、DBに無い正解商品だけを追加取得して公平に測る。

ベクトルDBは使わず numpy 総当たり（数百〜数千件で十分）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from booth_client import BoothClient
from hair_tags import build_hair_vocab
from step1_crawl_listings import parse_listing_page
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
IMAGES_DIR = ROOT / "images"
PRODUCTS_FILE = ROOT / "data" / "products.json"
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
HAIR_VOCAB_FILE = ROOT / "data" / "hair_vocab.json"
MODEL_CACHE = ROOT / "cache" / "hf"

EVAL_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def ground_truth_id(path: Path) -> str:
    """ファイル名 '正解ID_連番' から正解商品IDを取り出す。"""
    return path.stem.split("_")[0]


def is_distractor(path: Path) -> bool:
    """正解の無いディストラクタ画像か（アバター標準髪など）。

    ファイル名が 'x_' で始まる、または先頭トークンが数値(商品ID)でないものは
    採点対象外のディストラクタとして扱う。
    """
    stem = path.stem
    if stem.lower().startswith("x_"):
        return True
    return not ground_truth_id(path).isdigit()


def vec_from_tags(tag_conf: dict[str, float], vocab: list[str]) -> np.ndarray:
    return np.array([tag_conf.get(t, 0.0) for t in vocab], dtype=np.float32)


def l2_normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def augment_missing(missing_ids: set[str], client: BoothClient) -> list[dict]:
    """DBに無い正解商品の一覧情報を、商品ページから1件ずつ取得する。"""
    added = []
    for pid in sorted(missing_ids):
        url = f"https://booth.pm/ja/items/{pid}"
        try:
            html = client.get_html(url)
        except Exception as e:  # noqa: BLE001
            print(f"  正解商品 {pid} の取得に失敗: {e}", file=sys.stderr)
            continue
        # 商品ページにも item-card 相当のOGP/サムネがあるが、確実なのはリストのパーサではない。
        # ここでは最低限、サムネイルURLを og:image から拾う。
        import re
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        thumb = m.group(1) if m else None
        mname = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        name = mname.group(1) if mname else pid
        added.append({
            "product_id": pid, "name": name, "url": url,
            "thumbnail_url": thumb, "shop_name": None, "shop_url": None,
            "price": None, "has_vrchat_badge": False,
        })
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--augment", action="store_true",
                    help="DBに無い正解商品を追加取得してから測る")
    ap.add_argument("--crop", action="store_true",
                    help="頭部クロップ版で測る（data/hair_vectors_crop.json を使用）")
    ap.add_argument("--idf", action="store_true",
                    help="タグをIDF重み付けする（平凡タグを下げ、希少な形状タグを上げる）")
    ap.add_argument("--multi", action="store_true",
                    help="マルチ画像DB(data/hair_vectors_multi.json)で測る")
    args = ap.parse_args()

    hair_vectors_file = HAIR_VECTORS_FILE
    if args.multi:
        hair_vectors_file = ROOT / "data" / "hair_vectors_multi.json"
        if not hair_vectors_file.exists():
            print("先に  python src/step5_multi_image.py  を実行してください。", file=sys.stderr)
            sys.exit(1)
    elif args.crop:
        hair_vectors_file = ROOT / "data" / "hair_vectors_crop.json"
        if not hair_vectors_file.exists():
            print("先に  python src/step3_tagger.py --crop  を実行してください。", file=sys.stderr)
            sys.exit(1)

    eval_files = sorted(p for p in EVAL_DIR.glob("*") if p.suffix.lower() in EVAL_EXTS)
    if not eval_files:
        print("eval/ に評価画像がありません。'正解ID_連番.png' 形式で置いてください。", file=sys.stderr)
        sys.exit(1)

    # 採点対象（正解ID付き）と ディストラクタ（正解なし・標準髪など）に分ける
    scored_files = [p for p in eval_files if not is_distractor(p)]
    distractor_files = [p for p in eval_files if is_distractor(p)]

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    hair_vectors = json.loads(hair_vectors_file.read_text(encoding="utf-8"))
    vocab = json.loads(HAIR_VOCAB_FILE.read_text(encoding="utf-8"))
    name_by_id = {p["product_id"]: p["name"] for p in products}

    # 追加取得の対象は「採点対象の正解ID」だけ（ディストラクタには正解が無い）
    gt_ids = {ground_truth_id(p) for p in scored_files}
    have_ids = set(hair_vectors.keys())
    missing = gt_ids - have_ids

    tagger = WDTagger(cache_dir=MODEL_CACHE)

    # --- 公平性のための追加取得（任意）。取得した正解商品はDBに恒久保存する ---
    if missing and args.augment:
        print(f"DBに無い正解商品 {len(missing)} 件を追加取得します...", file=sys.stderr)
        client = BoothClient()
        added = augment_missing(missing, client)
        known_pids = {p["product_id"] for p in products}
        newly_saved = 0
        for p in added:
            pid = p["product_id"]
            thumb = p.get("thumbnail_url")
            if not thumb:
                continue
            dest = IMAGES_DIR / f"{pid}.jpg"
            try:
                client.get_image(thumb, dest)
                g = tagger.tag_image(dest, crop=args.crop)
                hair_vectors[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= 0.05}
                name_by_id[pid] = p["name"]
                if pid not in known_pids:  # products.json にも追記
                    products.append(p)
                    known_pids.add(pid)
                newly_saved += 1
            except Exception as e:  # noqa: BLE001
                print(f"  {pid} の追加処理に失敗: {e}", file=sys.stderr)
        # 恒久保存: 次回以降は取得・再タグ付けをスキップできる
        if newly_saved:
            hair_vectors_file.write_text(
                json.dumps(hair_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
            PRODUCTS_FILE.write_text(
                json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {newly_saved} 件を DB({hair_vectors_file.name} / products.json)に保存しました。", file=sys.stderr)
        have_ids = set(hair_vectors.keys())
        missing = gt_ids - have_ids

    # --- 商品側の行列を作る ---
    prod_ids = list(hair_vectors.keys())
    P = np.stack([vec_from_tags(hair_vectors[pid], vocab) for pid in prod_ids])

    # --- IDF重み（任意）: 各タグを log(N/df) で重み付け ---
    # df = そのタグが >=0.2 で立っている商品数。平凡タグ(long_hair等)は重みが下がる。
    weights = np.ones(len(vocab), dtype=np.float32)
    if args.idf:
        N = P.shape[0]
        df = np.sum(P >= 0.2, axis=0)
        weights = np.log((N + 1.0) / (df + 1.0)).astype(np.float32) + 1.0
        top = sorted(zip(vocab, weights), key=lambda x: x[1])
        print("IDF重み（低い=平凡なタグ / 高い=希少で識別に効くタグ）:", file=sys.stderr)
        print("  低い:", ", ".join(f"{t}={w:.2f}" for t, w in top[:5]), file=sys.stderr)
        print("  高い:", ", ".join(f"{t}={w:.2f}" for t, w in top[-5:]), file=sys.stderr)

    Pn = l2_normalize(P * weights)

    def search(path: Path):
        """画像→髪ベクトル→全商品とのコサイン類似度。降順の (score, prod_id) を返す。"""
        g = tagger.tag_image(path, crop=args.crop)
        q = vec_from_tags(g, vocab) * weights
        qn = q / (np.linalg.norm(q) or 1.0)
        sims = Pn @ qn
        order = np.argsort(-sims)
        return [(float(sims[i]), prod_ids[i]) for i in order]

    # ================= 採点対象（正解ID付き）=================
    hits = {1: 0, 5: 0, 10: 0}
    scored = 0                 # 正解がDBにある＝採点可能な枚数
    tp_top1_scores: list[float] = []   # 採点対象の top-1 類似スコア（true-positive 側）
    print("\n" + "=" * 78)
    print("【採点対象】正解ID付きの評価画像")
    print("=" * 78)
    for ef in scored_files:
        gid = ground_truth_id(ef)
        ranked = search(ef)
        top10 = ranked[:10]
        top10_ids = [pid for _, pid in top10]
        in_db = gid in have_ids
        rank = top10_ids.index(gid) + 1 if gid in top10_ids else None
        if in_db:
            scored += 1
            tp_top1_scores.append(top10[0][0])
            for k in (1, 5, 10):
                if rank is not None and rank <= k:
                    hits[k] += 1
        flag = "" if in_db else "  ⚠正解がDBに無い(採点対象外／--augment 推奨)"
        rank_s = f"top{rank}" if rank else "圏外"
        print(f"[{ef.name}] 正解={gid} → {rank_s}{flag}")
        for sc, pid in top10[:5]:
            mark = "★" if pid == gid else " "
            print(f"    {mark} {sc:.3f}  {pid}  {name_by_id.get(pid,'?')[:40]}")

    # ================= ディストラクタ（正解なし）=================
    fp_top1_scores: list[float] = []   # ディストラクタの top-1 類似スコア（false-positive 側）
    if distractor_files:
        print("\n" + "=" * 78)
        print("【ディストラクタ】正解の無い画像（アバター標準髪など・採点対象外）")
        print("  → 目視: 出てきた候補は『似た買える髪』として妥当か？ スコアは本物マッチより低いか？")
        print("=" * 78)
        for ef in distractor_files:
            ranked = search(ef)
            fp_top1_scores.append(ranked[0][0])
            print(f"[{ef.name}] top-1類似={ranked[0][0]:.3f}")
            for sc, pid in ranked[:5]:
                print(f"      {sc:.3f}  {pid}  {name_by_id.get(pid,'?')[:40]}")

    # ================= 集計 =================
    print("\n" + "=" * 78)
    n = len(eval_files)
    print(f"評価画像 合計: {n} 枚（採点対象 {len(scored_files)} / ディストラクタ {len(distractor_files)}）")
    print(f"  うち採点可能(正解がDB内): {scored} 枚 / 正解がDB外: {len(missing)} 種類")
    if scored:
        print("\n★ ヒット率（採点可能な画像に対して）")
        for k in (1, 5, 10):
            print(f"   top-{k:<2}: {hits[k]}/{scored} = {hits[k]/scored*100:.1f}%")

    # 偽陽性の分離可能性: 本物マッチの top-1 スコア vs ディストラクタの top-1 スコア
    if tp_top1_scores and fp_top1_scores:
        tp = np.array(tp_top1_scores)
        fp = np.array(fp_top1_scores)
        print("\n★ 偽陽性チェック（top-1 類似スコアの分布）")
        print(f"   正解あり(true) : min={tp.min():.3f} 中央={np.median(tp):.3f} max={tp.max():.3f}")
        print(f"   標準髪(false)  : min={fp.min():.3f} 中央={np.median(fp):.3f} max={fp.max():.3f}")
        if fp.max() < tp.min():
            print(f"   → 完全分離可能。しきい値 {(fp.max()+tp.min())/2:.3f} 付近で偽陽性を弾ける")
        elif np.median(fp) < np.median(tp):
            print("   → 分布はずれているが重なりあり。しきい値で一部の偽陽性は弾ける")
        else:
            print("   → 分離できていない。スコアだけでは本物と標準髪を区別できない（要改善）")

    if scored < len(scored_files):
        print("\n注: 採点対象外があるのは、正解商品が500件の新着DBに含まれていないため。")
        print("    公平に測るには  python src/step4_evaluate.py --augment  を使う。")


if __name__ == "__main__":
    main()
