"""
ステップ9（フェーズ2）: 商品メタから「対応アバター」を抽出・正規化する。

高精度シグナル: BOOTHタグの多くが「<アバター名>対応 / 用 / 専用」形式で対応アバターを列挙。
  例: 'マヌカ対応', 'Shinano対応', 'lime用', 'Miriam専用'
接尾辞を剥がすとアバター名が得られる。説明文の「Nアバター対応: A / B ...」も補助。

JP/EN 別名（しお=Sio, フィオナ=Fiona 等）:
  ① 手動シード（MANUAL_ALIASES）
  ② 説明文の「かな（英字）」「英字（かな）」の隣接表記から自動抽出し、
     実在アバター（①の抽出集合）に触れるペアだけ採用（Prefab/Material等のノイズを除外）
  → surface(表記) → canonical(JP優先) の索引を作り、全アバター名を正規化する。

出力:
- data/product_avatars.json : {product_id: [canonicalアバター名, ...]}
- data/avatar_vocab.json    : [[canonical名, 商品数], ...] 降順
- data/avatar_aliases.json  : {surface(小文字): canonical} ユーザー入力解決用
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META_FILE = ROOT / "data" / "product_meta.json"
OUT_PRODUCT_AVATARS = ROOT / "data" / "product_avatars.json"
OUT_AVATAR_VOCAB = ROOT / "data" / "avatar_vocab.json"
OUT_AVATAR_ALIASES = ROOT / "data" / "avatar_aliases.json"

SUFFIX = re.compile(r"(対応版|専用|対応|向け|用)$")
KANA = r"[ぁ-んァ-ヶ一-龠]{2,12}"
LATIN = r"[A-Za-z][A-Za-z0-9_]{1,14}"

NOT_AVATAR = {
    "vrchat", "vrc", "vrc想定モデル", "3d", "3dモデル", "3d素材", "髪", "髪型", "ヘア",
    "ヘアー", "へあ", "hair", "アバター", "avatar", "ロング", "ショート", "ボブ",
    "ツインテール", "ポニーテール", "ウルフ", "ウルフカット", "セール", "sale", "liltoon",
    "modular", "modularavatar", "ma", "pb", "physbone", "quest", "pc", "オリジナル",
    "オリジナル3dモデル", "改変", "衣装", "アクセサリー", "アクセサリ", "vroid", "unity",
    "セール中", "無料", "free", "vtuber", "配信用", "アバター用", "女性", "男性", "女の子",
    "男の子", "ユニセックス", "中性的", "髪の毛", "3dモデル素材", "prefab", "material",
    "texture", "package", "shader", "wear", "jp", "zh", "en", "discord", "psd", "png",
    "めがね", "マスク", "マップ", "材質", "材质", "贴图", "预制件", "プレハブ", "本体",
    "利用規約", "使用条款", "お問い合わせ", "おまけ", "最新版推奨", "最新版", "改変前提",
}

# 手動シード（surface -> canonical JP）。ユーザーが挙げた例＋頻出を含む。
MANUAL_ALIASES = {
    "sio": "しお", "fiona": "フィオナ", "shinano": "しなの", "manuka": "マヌカ",
    "chocolat": "ショコラ", "chocolate": "ショコラ", "selestia": "セレスティア",
    "rurune": "ルルネ", "kipfel": "キプフェル", "ramune": "ラムネ", "moe": "萌",
    "airi": "愛莉", "milltina": "ミルティナ", "milfy": "ミルフィ", "kumaly": "クマリ",
    "eku": "エク", "mayo": "まよ", "lime": "ライム", "minase": "水瀬", "komano": "狛乃",
    "bokusei": "墨惺", "hanka": "斑霞", "shinra": "森羅", "linne": "リンネ", "lumina": "ルミナ",
    "kalne": "カルネ", "shizune": "雫峰", "nakiya": "泣夜", "anila": "アニラ", "lunary": "ルナリィ",
    "siusiu": "しうしう", "miriam": "ミリアム", "nelfy": "ネルフィ", "nagi": "凪",
    "marycia": "マリシア", "mao": "真央", "kaguya": "輝夜", "chiffon": "シフォン",
    "rinasciita": "リナシータ", "rokona": "ロコナ", "lapwing": "ラプウィング",
    "mamehinata": "まめひなた", "io": "イオ", "kanata": "彼方",
}


def clean(token: str) -> str:
    t = SUFFIX.sub("", token.strip()).strip()
    return t


def is_avatarish(token: str) -> bool:
    low = token.lower()
    return bool(token) and len(token) > 1 and low not in NOT_AVATAR


def raw_avatars(meta_entry) -> set[str]:
    """接尾辞シグナル＋説明文列挙から、正規化前の生アバター表記を集める。"""
    out = set()
    for t in meta_entry.get("tags", []):
        if SUFFIX.search(t):
            c = clean(t)
            if is_avatarish(c):
                out.add(c)
    desc = meta_entry.get("description", "")
    for m in re.finditer(r"(?:\d+\s*(?:体|アバター|avatars?)\s*対応|対応アバター|Supported[^:]*:)([^\n]{0,300})",
                         desc, re.I):
        for part in re.split(r"[／/、,・\|]", m.group(1)):
            c = clean(part)
            if is_avatarish(c):
                out.add(c)
    return out


def build_alias_index(meta, raw_surface_set) -> dict[str, str]:
    """surface(小文字) -> canonical(JP優先) の索引。"""
    idx: dict[str, str] = {}
    for k, v in MANUAL_ALIASES.items():
        idx[k.lower()] = v
        idx[v.lower()] = v
    # 自動抽出: かな(英字) / 英字(かな)。実在アバターに触れるペアだけ採用
    pairs = collections.Counter()
    for d in meta.values():
        txt = d.get("description", "") + " " + " ".join(d.get("tags", []))
        for m in re.finditer(rf"({KANA})\s*[（(]\s*({LATIN})\s*[）)]", txt):
            pairs[(m.group(1), m.group(2))] += 1
        for m in re.finditer(rf"({LATIN})\s*[（(]\s*({KANA})\s*[）)]", txt):
            pairs[(m.group(2), m.group(1))] += 1
    for (jp, en), _c in pairs.items():
        if jp in raw_surface_set or en in raw_surface_set or en.lower() in idx:
            if jp.lower() in NOT_AVATAR or en.lower() in NOT_AVATAR:
                continue
            idx[en.lower()] = jp
            idx[jp.lower()] = jp
    return idx


def canonical(token: str, idx: dict[str, str]) -> str:
    return idx.get(token.lower(), token)


def main() -> None:
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))

    # pass1: 生表記を集める
    raw_by_pid = {pid: raw_avatars(m) for pid, m in meta.items()}
    global_raw = set().union(*raw_by_pid.values()) if raw_by_pid else set()

    # 別名索引
    idx = build_alias_index(meta, global_raw)

    # pass2: canonical 化して紐付け
    product_avatars: dict[str, list[str]] = {}
    counter: collections.Counter = collections.Counter()
    for pid, raws in raw_by_pid.items():
        canon = {canonical(r, idx) for r in raws}
        canon = {c for c in canon if is_avatarish(c)}
        if canon:
            product_avatars[pid] = sorted(canon)
            counter.update(canon)

    vocab = [[name, cnt] for name, cnt in counter.most_common() if cnt >= 2]

    OUT_PRODUCT_AVATARS.write_text(json.dumps(product_avatars, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_AVATAR_VOCAB.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_AVATAR_ALIASES.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"対応アバター: {len(product_avatars)} 商品 / 語彙 {len(vocab)} / 別名索引 {len(idx)} 表記")
    print("頻出 top20:")
    for name, cnt in counter.most_common(20):
        print(f"  {name:12} {cnt}")


if __name__ == "__main__":
    main()
