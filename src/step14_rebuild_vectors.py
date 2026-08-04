"""
ステップ14: 語彙（許可リスト）変更後の全ベクトル再生成。

hair_tags.py の HAIR_SHAPE_ALLOWLIST を変えたときに実行する。
- hair_vocab.json をモデルタグとの積集合で作り直す
- 全商品のキャッシュ済みサムネ（images/{pid}.jpg）を新語彙で再タグ付け
- 画像が無い商品だけ thumbnail_url から取得（BoothClient = 直列・レート制御・キャッシュ）
- タグ付けに失敗した商品は旧ベクトルを維持（新タグは付かないが検索から消えない）
- 50件ごとにチェックポイント保存。途中で止めても再実行すれば続きから
  （--resume 時: 新語彙で既にタグ済みのものはスキップ）

使い方: python src/step14_rebuild_vectors.py [--resume] [--if-changed]
  --if-changed: 語彙が data/hair_vocab.json から変わっていなければ何もせず終了
                （毎週のGitHub Actionsから呼ぶ用。語彙変更時だけ全再生成が走る）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from booth_client import BoothClient
from hair_tags import build_hair_vocab
from wd_tagger import WDTagger

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
HAIR_VECTORS_FILE = ROOT / "data" / "hair_vectors.json"
HAIR_VOCAB_FILE = ROOT / "data" / "hair_vocab.json"
IMAGES_DIR = ROOT / "images"
MODEL_CACHE = ROOT / "cache" / "hf"
HAIR_EPS = 0.05  # step10/step13 と同じしきい値


def main() -> None:
    resume = "--resume" in sys.argv

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    old_vectors = json.loads(HAIR_VECTORS_FILE.read_text(encoding="utf-8"))
    old_vocab = set(json.loads(HAIR_VOCAB_FILE.read_text(encoding="utf-8")))

    tagger = WDTagger(cache_dir=MODEL_CACHE)
    vocab = build_hair_vocab(tagger.general_names)
    added = sorted(set(vocab) - old_vocab)
    removed = sorted(old_vocab - set(vocab))
    print(f"語彙: {len(old_vocab)} → {len(vocab)} (追加 {added or 'なし'} / 削除 {removed or 'なし'})",
          file=sys.stderr, flush=True)
    if "--if-changed" in sys.argv and not added and not removed:
        print("語彙変更なし。再生成をスキップ。", file=sys.stderr)
        return
    HAIR_VOCAB_FILE.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")

    # 進捗はサイドカーに持つ（ベクトルの中身からは「新語彙で済み」を判定できないため）
    out_file = HAIR_VECTORS_FILE
    progress_file = ROOT / "data" / ".rebuild_progress.json"
    new_vectors: dict = {}
    done: set = set()
    if resume and progress_file.exists():
        done = set(json.loads(progress_file.read_text(encoding="utf-8")))
        new_vectors = json.loads(out_file.read_text(encoding="utf-8"))
        print(f"再開: {len(done)} 件はタグ付け済み", file=sys.stderr, flush=True)

    client = BoothClient()
    todo = [p for p in products if p["product_id"] not in done]
    kept_old = 0
    ok = 0
    t0 = time.time()
    for i, p in enumerate(todo, 1):
        pid = p["product_id"]
        dest = IMAGES_DIR / f"{pid}.jpg"
        try:
            if not dest.exists():
                client.get_image(p["thumbnail_url"], dest)
            g = tagger.tag_image(dest)
            new_vectors[pid] = {t: round(g.get(t, 0.0), 4) for t in vocab if g.get(t, 0.0) >= HAIR_EPS}
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {pid} 失敗（旧ベクトル維持）: {e}", file=sys.stderr, flush=True)
            if pid in old_vectors:
                new_vectors[pid] = old_vectors[pid]
                kept_old += 1
        done.add(pid)
        if i % 50 == 0 or i == len(todo):
            out_file.write_text(json.dumps(new_vectors, ensure_ascii=False, indent=2), encoding="utf-8")
            progress_file.write_text(json.dumps(sorted(done)), encoding="utf-8")
            rate = i / max(time.time() - t0, 1) * 60
            print(f"  [{i}/{len(todo)}] 済 {ok} / 旧維持 {kept_old} / {rate:.0f} 商品/分",
                  file=sys.stderr, flush=True)

    progress_file.unlink(missing_ok=True)  # 完走したら進捗ファイルは消す

    # 新タグの付与状況サマリ
    counts = {t: 0 for t in added}
    for v in new_vectors.values():
        for t in added:
            if t in v:
                counts[t] += 1
    print("\n" + "=" * 56)
    print(f"再生成完了: {len(new_vectors)} 商品 / 語彙 {len(vocab)} タグ（失敗して旧維持 {kept_old}）")
    for t in added:
        print(f"  新タグ {t}: {counts[t]} 商品 (conf>={HAIR_EPS})")
    print("=" * 56)


if __name__ == "__main__":
    main()
