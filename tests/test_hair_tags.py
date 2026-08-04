# -*- coding: utf-8 -*-
"""hair_tags の解決ロジックのテスト（表記ゆれ・接頭辞合成・外部辞書）。

実行: python -m pytest tests/ -q
      （pytest が無ければ python tests/test_hair_tags.py でも走る簡易ランナーつき）
モデル不要・ネットワーク不要。語彙は data/hair_vocab.json を使う。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hair_tags import (JP_SYNONYMS, load_external_dict, normalize_ja,  # noqa: E402
                       resolve_tag)

VOCAB = json.loads((ROOT / "data" / "hair_vocab.json").read_text(encoding="utf-8"))

# (入力, 期待タグ)。None は「解決できないのが正しい」。
CASES = [
    # 表記ゆれ（ひらがな/カタカナ/漢字）
    ("ツインみつあみ", "twin_braids"),
    ("ツインミツアミ", "twin_braids"),
    ("ついんみつあみ", "twin_braids"),
    ("ツイン三つ編み", "twin_braids"),
    ("みつあみ", "braid"),
    ("ミツアミ", "braid"),
    ("三つ編み", "braid"),
    ("3つ編み", "braid"),
    ("三つ網", "braid"),
    ("あみこみ", "braid"),
    ("おだんご", "hair_bun"),
    ("オダンゴ", "hair_bun"),
    ("ツインおだんご", "double_bun"),
    ("ツインお団子", "double_bun"),
    # 接頭辞合成
    ("サイドみつあみ", "side_braid"),
    ("サイドおだんご", "single_side_bun"),
    ("サイドドリル", "side_drill"),
    ("ローツインテール", "low_twintails"),
    ("低ツインテール", "low_twintails"),
    ("ハイポニーテール", "high_ponytail"),
    ("ハイサイドポニー", "high_side_ponytail"),
    ("両みつあみ", "twin_braids"),
    ("一本三つ編み", "single_braid"),
    ("ショートツインテール", "short_twintails"),
    ("ショートポニーテール", "short_ponytail"),
    ("ロング三つ編み", "long_braid"),
    ("ロングみつあみ", "long_braid"),
    # 同義語（結び方）
    ("おさげ", "twin_braids"),
    ("二つ結び", "twintails"),
    ("ひとつ結び", "ponytail"),
    ("編みおろし", "single_braid"),
    # 同義語（カット・前髪・スタイル）
    ("マッシュ", "bowl_cut"),
    ("オン眉", "short_bangs"),
    ("おんまゆ", "short_bangs"),
    ("切りっぱなし", "blunt_ends"),
    ("オールバック", "hair_slicked_back"),
    ("インテーク", "hair_intakes"),
    ("ベリーショート", "very_short_hair"),
    ("ツーブロック", "undercut"),
    ("モヒカン", "mohawk"),
    ("ちょんまげ", "topknot"),
    ("ドレッド", "dreadlocks"),
    ("無造作", "messy_hair"),
    ("アシメ", "asymmetrical_hair"),
    ("カーテンバング", "curtained_hair"),
    ("編み込みお団子", "braided_bun"),
    ("あみこみおだんご", "braided_bun"),
    # 語彙拡張分
    ("ポンパドール", "pompadour"),
    ("アフロ", "afro"),
    ("前髪ポンパ", "bangs_pinned_back"),
    ("片側上げ", "asymmetrical_bangs"),
    # 既存動作の回帰
    ("ツインテール", "twintails"),
    ("ツインテ", "twintails"),
    ("ぱっつん", "blunt_bangs"),
    ("ポニテ", "ponytail"),
    ("縦ロール", "drill_hair"),
    ("ボブ", "bob_cut"),
    ("twintails", "twintails"),
    ("bob", "bob_cut"),
    ("braid", "braid"),
    ("ロングヘアー", "long_hair"),
    ("ウェーブヘアー", "wavy_hair"),
    ("セミロング", "medium_hair"),
    # 解決できないのが正しいもの
    ("", None),
    ("存在しない髪型語", None),
]


def test_resolve_cases():
    fails = []
    for inp, want in CASES:
        got = resolve_tag(inp, VOCAB)
        if got != want:
            fails.append(f"{inp!r}: got {got!r}, want {want!r}")
    assert not fails, "\n".join(fails)


def test_synonym_targets_exist_in_vocab():
    """組み込み辞書の解決先タグが全て語彙に実在すること（typo検出）。"""
    vocab_set = set(VOCAB)
    bad = sorted({v for v in JP_SYNONYMS.values() if v not in vocab_set})
    assert not bad, f"語彙に無いタグを指す同義語: {bad}"


def test_external_dict_file_valid():
    """data/jp_synonyms.json が読めて、解決先タグが語彙に実在すること。"""
    p = ROOT / "data" / "jp_synonyms.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    vocab_set = set(VOCAB)
    bad = sorted({v for v in (d.get("synonyms") or {}).values() if v not in vocab_set})
    assert not bad, f"jp_synonyms.json: 語彙に無いタグ {bad}"
    for key, combined in (d.get("prefix_combos") or {}).items():
        assert "|" in str(key), f"prefix_combos のキーは '接頭辞|基本タグ' 形式: {key!r}"
        assert combined in vocab_set, f"prefix_combos: 語彙に無いタグ {combined!r}"
    for pair in d.get("morph_canon") or []:
        assert len(pair) == 2, f"morph_canon は [src, dst] のペア: {pair!r}"


def test_external_dict_merge_and_robustness():
    """外部辞書のマージ動作と、壊れたファイルへの耐性。"""
    ext = {"synonyms": {"тестゆにーく語": "wavy_hair"}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(ext, f)
        tmp = f.name
    try:
        assert resolve_tag("тестゆにーく語", VOCAB) is None
        n = load_external_dict(tmp)
        assert n == 1
        assert resolve_tag("тестゆにーく語", VOCAB) == "wavy_hair"
    finally:
        Path(tmp).unlink(missing_ok=True)
    # 壊れたJSON・欠落ファイルは 0 件で落ちない
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        f.write("{broken")
        tmp = f.name
    try:
        assert load_external_dict(tmp) == 0
    finally:
        Path(tmp).unlink(missing_ok=True)
    assert load_external_dict(ROOT / "data" / "no_such_file.json") == 0


def test_normalize_ja():
    assert normalize_ja("ミツアミ") == normalize_ja("三つ編み")
    assert normalize_ja("おだんご") == normalize_ja("オダンゴ")
    assert normalize_ja("ＢＯＢ") == "bob"  # NFKC + 小文字化


if __name__ == "__main__":
    # pytest 無しでも動く簡易ランナー
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[OK] {name}")
            except AssertionError as e:
                failed += 1
                print(f"[NG] {name}: {e}")
    print("PASS" if not failed else f"FAIL ({failed})")
    sys.exit(1 if failed else 0)
