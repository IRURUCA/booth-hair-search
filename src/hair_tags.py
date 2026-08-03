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

    # --- ツインテール系 ---
    "twintails", "low_twintails", "short_twintails", "uneven_twintails",
    "one_side_up", "two_side_up", "asymmetrical_hair",

    # --- 三つ編み / 編み込み ---
    "braid", "twin_braids", "single_braid", "french_braid", "crown_braid",
    "side_braid", "side_braids", "low_twin_braids", "braided_ponytail",
    "long_braid", "tri_braids", "multiple_braids", "braided_bangs",
    "low-braided_long_hair", "low-tied_long_hair",

    # --- お団子 / まとめ髪 ---
    "hair_bun", "double_bun", "single_hair_bun", "cone_hair_bun",
    "doughnut_hair_bun", "braided_bun", "single_side_bun", "updo",
    "half_updo", "hair_rings", "single_hair_ring", "topknot",

    # --- ドリル / 巻き ---
    "drill_hair", "twin_drills", "side_drill", "ringlets",

    # --- 質感 / うねり ---
    "straight_hair", "wavy_hair", "curly_hair", "messy_hair", "spiked_hair",
    "flipped_hair", "hair_flaps", "dreadlocks", "hair_slicked_back",

    # --- 個別形状パーツ ---
    "ahoge", "huge_ahoge", "heart_ahoge", "antenna_hair", "cowlick",
    "sidelocks", "single_sidelock", "asymmetrical_sidelocks", "drill_sidelocks",
    "nape", "pointy_hair",

    # --- カット / 髪型名 ---
    "bob_cut", "bowl_cut", "hime_cut", "undercut", "mohawk", "buzz_cut",
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


def is_hair_shape_tag(tag: str) -> bool:
    """そのタグが髪の形状/長さ/質感タグ（許可リスト内）なら True。"""
    return tag in HAIR_SHAPE_ALLOWLIST


def resolve_tag(token: str, vocab) -> str | None:
    """ユーザー入力トークンを WD形状タグに解決する。無理なら None。

    優先順: 完全一致 → 同義語辞書 → 空白をアンダースコアに → 部分一致（あいまい補完）。
    """
    vocab_set = set(vocab)
    t = token.strip()
    if not t:
        return None
    if t in vocab_set:
        return t
    if t in JP_SYNONYMS:
        return JP_SYNONYMS[t]
    low = t.lower().strip()
    if low in JP_SYNONYMS:
        return JP_SYNONYMS[low]
    us = low.replace(" ", "_").replace("-", "_")
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
