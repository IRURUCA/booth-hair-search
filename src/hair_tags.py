"""
髪型の「形状・長さ・質感」タグだけを取り出すための共通ロジック。

設計の核（roadmap 0章）:
- 改変で最も変わるのは色 → 髪色タグは照合に使わない
- 髪飾り（アクセサリ）も形状ではないので使わない
- 残るのは「長さ・結い方・分け目・質感」を表す形状タグだけ

方針: WD v3 の general タグは 8106 個あり、"hair" を含むだけで拾うと
armchair / armpit_hair / 色つき hairband など大量のノイズが混じる。
そこで **キュレーションした許可リスト（allowlist）** を採用し、
モデルが実際に持つタグとの積集合だけを語彙にする。

ステップ1-3（抽出）とステップ1-4（照合）で必ず同じ語彙を使うため、ここに一元化する。
"""
from __future__ import annotations

import unicodedata

# 髪型の形状/長さ/結い方/分け目/質感を表すタグの許可リスト。
# （Danbooru/WD v3 の実タグ名に合わせている。色・アクセサリ・体毛・動作は含めない）
HAIR_SHAPE_ALLOWLIST = {
    # --- 長さ ---
    "very_short_hair", "short_hair", "medium_hair", "long_hair",
    "very_long_hair", "absurdly_long_hair", "big_hair", "short_hair_with_long_locks",

    # --- 前髪 / 分け目 ---（WD v3 に plain "bangs" は無く、種類別に分かれている）
    "blunt_bangs", "swept_bangs", "parted_bangs", "asymmetrical_bangs",
    "crossed_bangs", "diagonal_bangs", "double-parted_bangs", "medium_bangs",
    "short_bangs", "long_bangs", "choppy_bangs", "arched_bangs",
    "hair_over_eyes", "hair_over_one_eye", "hair_between_eyes", "curtained_hair",
    "hair_intakes", "blunt_ends", "parted_hair", "hair_pulled_back",

    # --- ポニーテール系 ---
    "ponytail", "high_ponytail", "low_ponytail", "side_ponytail",
    "folded_ponytail", "front_ponytail", "short_ponytail", "split_ponytail",
    "high_side_ponytail", "wide_ponytail",

    # --- ツインテール系 ---
    "twintails", "low_twintails", "short_twintails", "uneven_twintails",
    "one_side_up", "two_side_up", "asymmetrical_hair",

    # --- 三つ編み / 編み込み ---
    "braid", "twin_braids", "single_braid", "french_braid", "crown_braid",
    "side_braid", "side_braids", "low_twin_braids", "braided_ponytail",
    "long_braid", "tri_braids", "multiple_braids", "braided_bangs",
    "low-braided_long_hair", "low-tied_long_hair", "braided_hair_rings",
    "low-tied_sidelocks", "multi-tied_hair",

    # --- お団子 / まとめ髪 ---
    "hair_bun", "double_bun", "single_hair_bun", "cone_hair_bun",
    "doughnut_hair_bun", "braided_bun", "single_side_bun", "updo",
    "half_updo", "hair_rings", "single_hair_ring", "topknot",

    # --- ドリル / 巻き ---
    "drill_hair", "twin_drills", "side_drill", "ringlets",

    # --- 質感 / うねり ---
    "straight_hair", "wavy_hair", "curly_hair", "messy_hair", "spiked_hair",
    "flipped_hair", "hair_flaps", "dreadlocks", "hair_slicked_back",
    "folded_hair", "hair_wings",

    # --- 個別形状パーツ ---
    "ahoge", "huge_ahoge", "heart_ahoge", "antenna_hair", "cowlick",
    "sidelocks", "single_sidelock", "asymmetrical_sidelocks", "drill_sidelocks",
    "nape", "pointy_hair",

    # --- カット / 髪型名 ---
    "bob_cut", "bowl_cut", "hime_cut", "undercut", "mohawk", "buzz_cut",
    "pompadour", "afro", "bangs_pinned_back",
}


# 日本語（カナ・漢字）・ローマ字 → WD形状タグ の同義語辞書。
# ユーザーが「ツインテール」等で入力しても正しいWDタグに変換するため。
JP_SYNONYMS = {
    # 長さ
    "ロング": "long_hair", "ロングヘア": "long_hair", "ロングヘアー": "long_hair",
    "長い": "long_hair", "長髪": "long_hair", "超ロング": "very_long_hair",
    "すごく長い": "very_long_hair", "ロングロング": "very_long_hair",
    "ショート": "short_hair", "ショートヘア": "short_hair", "短い": "short_hair", "短髪": "short_hair",
    "ミディアム": "medium_hair", "ミディ": "medium_hair", "セミロング": "medium_hair", "ミディアムヘア": "medium_hair",
    # 前髪
    "ぱっつん": "blunt_bangs", "パッツン": "blunt_bangs", "ぱっつん前髪": "blunt_bangs", "ふれ": "blunt_bangs",
    "流し前髪": "swept_bangs", "斜め前髪": "swept_bangs", "サイドバング": "swept_bangs",
    "分け前髪": "parted_bangs", "センター分け": "parted_bangs",
    "目隠れ": "hair_over_eyes", "目が隠れる": "hair_over_eyes", "片目隠れ": "hair_over_one_eye",
    # ポニーテール系
    "ポニーテール": "ponytail", "ポニテ": "ponytail", "ポニー": "ponytail",
    "ハイポニー": "high_ponytail", "高ポニー": "high_ponytail",
    "ローポニー": "low_ponytail", "低ポニー": "low_ponytail",
    "サイドテール": "side_ponytail", "サイドポニー": "side_ponytail",
    # ツインテール系
    "ツインテール": "twintails", "ツインテ": "twintails", "ツイン": "twintails",
    "ローツイン": "low_twintails", "低ツイン": "low_twintails",
    "ツーサイドアップ": "two_side_up", "サイドアップ": "one_side_up",
    # 三つ編み
    "三つ編み": "braid", "みつあみ": "braid", "編み込み": "braid", "ブレイド": "braid",
    "ツイン三つ編み": "twin_braids", "両三つ編み": "twin_braids",
    "一本三つ編み": "single_braid", "フレンチブレイド": "french_braid",
    # お団子
    "お団子": "hair_bun", "おだんご": "hair_bun", "だんご": "hair_bun", "団子": "hair_bun",
    "ツインお団子": "double_bun", "両お団子": "double_bun", "片お団子": "single_hair_bun",
    # 巻き・質感
    "ドリル": "drill_hair", "縦ロール": "drill_hair", "ツインドリル": "twin_drills",
    "巻き髪": "curly_hair", "カール": "curly_hair", "くるくる": "curly_hair",
    "ウェーブ": "wavy_hair", "ウェーブヘア": "wavy_hair", "波": "wavy_hair",
    "ストレート": "straight_hair", "さらさら": "straight_hair",
    "外ハネ": "flipped_hair", "はねる": "flipped_hair",
    # 結び方の言い換え
    "おさげ": "twin_braids", "お下げ": "twin_braids",
    "二つ結び": "twintails", "ふたつ結び": "twintails",
    "一つ結び": "ponytail", "ひとつ結び": "ponytail",
    "サイド三つ編み": "side_braid", "横三つ編み": "side_braid",
    "編みおろし": "single_braid", "編み下ろし": "single_braid",
    # 長さ・カット
    "スーパーロング": "absurdly_long_hair", "ベリーショート": "very_short_hair",
    "ショートカット": "short_hair", "マッシュ": "bowl_cut", "マッシュルームカット": "bowl_cut",
    "刈り上げ": "undercut", "ツーブロック": "undercut", "アンダーカット": "undercut",
    "坊主": "buzz_cut", "丸刈り": "buzz_cut", "モヒカン": "mohawk",
    "ちょんまげ": "topknot", "トップノット": "topknot",
    # 前髪の種類
    "オン眉": "short_bangs", "眉上": "short_bangs", "眉上前髪": "short_bangs", "短い前髪": "short_bangs",
    "長い前髪": "long_bangs", "ロング前髪": "long_bangs",
    "カーテンバング": "curtained_hair", "アーチ前髪": "arched_bangs",
    "クロス前髪": "crossed_bangs", "交差前髪": "crossed_bangs",
    "ギザギザ前髪": "choppy_bangs", "アシメ前髪": "asymmetrical_bangs",
    # 「片側だけ前髪が上がってる」スタイル。専用のWDタグが無いため
    # 最も近い asymmetrical_bangs に寄せる（swept_bangs 併用を推奨）
    "片側上げ": "asymmetrical_bangs", "片上げ": "asymmetrical_bangs",
    "片側かき上げ": "asymmetrical_bangs", "片側前髪上げ": "asymmetrical_bangs",
    "編み込み前髪": "braided_bangs", "切りっぱなし": "blunt_ends",
    # 質感・スタイル
    "オールバック": "hair_slicked_back", "かきあげ": "hair_pulled_back",
    "ボサボサ": "messy_hair", "無造作": "messy_hair", "寝ぐせ": "messy_hair",
    "ツンツン": "spiked_hair", "スパイキー": "spiked_hair",
    "ドレッド": "dreadlocks", "ドレッドヘア": "dreadlocks",
    "盛り髪": "big_hair", "リングレット": "ringlets",
    "アシメ": "asymmetrical_hair", "アシンメトリー": "asymmetrical_hair",
    # 語彙拡張分（2026-08）
    "ポンパドール": "pompadour", "アフロ": "afro",
    "前髪ポンパ": "bangs_pinned_back", "ポンパ前髪": "bangs_pinned_back", "ポンパ": "bangs_pinned_back",
    "ハイサイドポニー": "high_side_ponytail", "ハイサイドテール": "high_side_ponytail",
    # パーツ・複合
    "インテーク": "hair_intakes", "うなじ": "nape",
    "ハートアホ毛": "heart_ahoge", "でかアホ毛": "huge_ahoge", "巨大アホ毛": "huge_ahoge",
    "編み込みお団子": "braided_bun", "ドーナツお団子": "doughnut_hair_bun",
    "クラウンブレイド": "crown_braid", "冠三つ編み": "crown_braid",
    # 個別
    "姫カット": "hime_cut", "姫": "hime_cut", "ボブ": "bob_cut", "ボブカット": "bob_cut", "ショートボブ": "bob_cut",
    "アホ毛": "ahoge", "あほげ": "ahoge", "触角": "antenna_hair", "アンテナ": "antenna_hair", "触覚": "antenna_hair",
    "もみあげ": "sidelocks", "サイドの髪": "sidelocks", "サイドロック": "sidelocks",
    "ハーフアップ": "half_updo", "まとめ髪": "updo", "アップ": "updo",
    # ローマ字/英語ゆらぎ
    "twintail": "twintails", "pigtails": "twintails", "bob": "bob_cut", "buns": "double_bun",
    "bun": "hair_bun", "bangs": "blunt_bangs", "wavy": "wavy_hair", "curly": "curly_hair",
    "straight": "straight_hair", "braids": "braid", "drill": "drill_hair",
}


# --- 表記ゆれ正規化 ---------------------------------------------------------
# 「ツインみつあみ」「ツインミツアミ」「ツイン三つ編み」を同一視するため、
# 入力と辞書キーの両方を同じ正規形（NFKC→小文字→カタカナ→形態素置換）に落とす。

_HIRA_TO_KATA = {i: i + 0x60 for i in range(0x3041, 0x3097)}  # ぁ-ゖ → ァ-ヶ

# カタカナ統一後の文字列に適用する形態素の正規化（かな表記→漢字かな交じりの正規形）。
# 順序に意味がある: 長い/包含関係のあるパターンを先に置換する。
_MORPH_CANON = [
    ("ミツアミ", "三ツ編ミ"), ("三ツアミ", "三ツ編ミ"), ("ミツ編ミ", "三ツ編ミ"),
    ("三ツ網", "三ツ編ミ"), ("3ツ編ミ", "三ツ編ミ"),
    ("アミコミ", "編ミ込ミ"), ("編ミコミ", "編ミ込ミ"), ("アミ込ミ", "編ミ込ミ"),
    ("ダンゴ", "団子"),
    ("ヘアー", "ヘア"),
    ("オンマユ", "オン眉"), ("マユウエ", "眉上"),
]


def normalize_ja(text: str) -> str:
    """表記ゆれ吸収の正規形: NFKC → 小文字 → ひらがな→カタカナ → 形態素置換。"""
    s = unicodedata.normalize("NFKC", text or "").lower().strip()
    s = s.translate(_HIRA_TO_KATA)
    for src, dst in _MORPH_CANON:
        s = s.replace(src, dst)
    return s


# 正規形をキーにした同義語辞書（起動時に一度だけ構築）
_JP_SYNONYMS_NORM = {normalize_ja(k): v for k, v in JP_SYNONYMS.items()}

# 接頭辞 + 基本形状 → 複合タグ。「ツイン＋(三つ編み=braid)→twin_braids」のように、
# 辞書に無い複合語を分解して解決する。キーは (正規形の接頭辞, 基本タグ)。
_PREFIX_COMBOS = {
    ("ツイン", "braid"): "twin_braids",
    ("ツイン", "hair_bun"): "double_bun",
    ("ツイン", "drill_hair"): "twin_drills",
    ("ツイン", "ponytail"): "twintails",
    ("ロー", "twintails"): "low_twintails", ("低", "twintails"): "low_twintails",
    ("ロー", "ponytail"): "low_ponytail", ("低", "ponytail"): "low_ponytail",
    ("ハイ", "ponytail"): "high_ponytail", ("高", "ponytail"): "high_ponytail",
    ("ハイ", "side_ponytail"): "high_side_ponytail", ("高", "side_ponytail"): "high_side_ponytail",
    ("ロー", "twin_braids"): "low_twin_braids", ("低", "twin_braids"): "low_twin_braids",
    ("サイド", "braid"): "side_braid", ("横", "braid"): "side_braid",
    ("サイド", "ponytail"): "side_ponytail",
    ("サイド", "hair_bun"): "single_side_bun",
    ("サイド", "drill_hair"): "side_drill",
    ("ショート", "ponytail"): "short_ponytail",
    ("ショート", "twintails"): "short_twintails",
    ("ロング", "braid"): "long_braid",
    ("片", "hair_bun"): "single_hair_bun",
    ("両", "hair_bun"): "double_bun",
    ("両", "braid"): "twin_braids",
    ("一本", "braid"): "single_braid",
}
_COMBO_PREFIXES = sorted({p for p, _ in _PREFIX_COMBOS}, key=len, reverse=True)


def load_external_dict(path) -> int:
    """外部辞書 data/jp_synonyms.json を組み込み辞書にマージする。

    辞書追加を exe の再リリースなしで配るための仕組み。このファイルは
    db_update の同期対象なので、GitHub の main に push すれば次回起動時に
    全クライアントへ届く。形式:

        {"synonyms":      {"片側上げ": "asymmetrical_bangs", ...},
         "morph_canon":   [["オンマユ", "オン眉"], ...],
         "prefix_combos": {"ツイン|braid": "twin_braids", ...}}

    戻り値: 取り込んだエントリ数。ファイルが無い/壊れていれば 0（組み込みのみで動作）。
    """
    import json
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for src, dst in d.get("morph_canon") or []:
        pair = (str(src), str(dst))
        if pair not in _MORPH_CANON:
            _MORPH_CANON.append(pair)
            n += 1
    for k, v in (d.get("synonyms") or {}).items():
        if JP_SYNONYMS.get(k) != v:
            JP_SYNONYMS[k] = str(v)
            n += 1
    for key, combined in (d.get("prefix_combos") or {}).items():
        try:
            prefix, base = str(key).split("|", 1)
        except ValueError:
            continue
        if _PREFIX_COMBOS.get((prefix, base)) != combined:
            _PREFIX_COMBOS[(prefix, base)] = str(combined)
            n += 1
    if n:
        # 形態素置換が増えた可能性があるので、正規形キーの辞書を作り直す
        _JP_SYNONYMS_NORM.clear()
        _JP_SYNONYMS_NORM.update({normalize_ja(k): v for k, v in JP_SYNONYMS.items()})
        _COMBO_PREFIXES[:] = sorted({pf for pf, _ in _PREFIX_COMBOS}, key=len, reverse=True)
    return n


def is_hair_shape_tag(tag: str) -> bool:
    """そのタグが髪の形状/長さ/質感タグ（許可リスト内）なら True。"""
    return tag in HAIR_SHAPE_ALLOWLIST


def resolve_tag(token: str, vocab) -> str | None:
    """ユーザー入力トークンを WD形状タグに解決する。無理なら None。

    優先順: 完全一致 → 同義語辞書（表記ゆれ正規化込み）→ 接頭辞合成
    → 空白をアンダースコアに → 部分一致（あいまい補完）。
    """
    vocab_set = set(vocab)
    t = token.strip()
    if not t:
        return None
    if t in vocab_set:
        return t
    if t in JP_SYNONYMS:
        return JP_SYNONYMS[t]
    norm = normalize_ja(t)
    if norm in _JP_SYNONYMS_NORM:
        return _JP_SYNONYMS_NORM[norm]
    # 接頭辞合成: 「ツイン＋みつあみ」のような辞書に無い複合語を分解して解決
    for prefix in _COMBO_PREFIXES:
        if norm.startswith(prefix) and len(norm) > len(prefix):
            rest = _JP_SYNONYMS_NORM.get(norm[len(prefix):])
            if rest:
                combined = _PREFIX_COMBOS.get((prefix, rest))
                if combined:
                    return combined
                return rest  # 合成先が無ければ基本形状だけでも返す
    us = norm.replace(" ", "_").replace("-", "_")
    if us in vocab_set:
        return us
    # あいまい: 入力がタグの部分文字列（またはその逆）で最短一致
    cands = [v for v in vocab_set if us and (us in v or v in us)]
    if cands:
        return min(cands, key=len)
    return None


def build_hair_vocab(all_tag_names) -> list[str]:
    """モデルの全タグ名と許可リストの積集合を、照合ベクトルの次元にする。"""
    known = set(all_tag_names)
    vocab = sorted(t for t in HAIR_SHAPE_ALLOWLIST if t in known)
    return vocab
