"""
髪型検索の中核（UI・評価から共用）。

single + IDF をベースラインとして採用（フェーズ1で最良: top-10 61%）。
- 商品DB: data/hair_vectors.json（サムネ1枚のタグ）
- 語彙  : data/hair_vocab.json（髪形状100次元、色・アクセサリ除外）
- IDF重み: 平凡タグを抑え、希少な形状タグを重視
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from hair_tags import build_hair_vocab, normalize_ja, resolve_tag
from paths import (BUNDLE_MODEL_DIR, BUNDLE_ROOT, HF_CACHE, data_file,
                   has_bundled_model)
from wd_tagger import WDTagger

ROOT = BUNDLE_ROOT  # 後方互換（他モジュールが参照）
PRODUCTS_FILE = data_file("products.json")
HAIR_VECTORS_FILE = data_file("hair_vectors.json")
PRODUCT_AVATARS_FILE = data_file("product_avatars.json")
AVATAR_VOCAB_FILE = data_file("avatar_vocab.json")
AVATAR_ALIASES_FILE = data_file("avatar_aliases.json")
STATS_FILE = data_file("product_stats.json")
MODEL_CACHE = HF_CACHE

# 商品名からVRChat対応を推定する補助シグナル（バッジが不完全なため）
# 注: 確実なのは items/{id}.json の VRChat タグ。ここは当面の近似。
_VRC_NAME = re.compile(r"VRC|VRChat|アバター対応|対応アバター|avatars?", re.IGNORECASE)


def looks_vrchat(product: dict) -> bool:
    if product.get("has_vrchat_badge"):
        return True
    return bool(_VRC_NAME.search(product.get("name", "")))


class HairMatcher:
    def __init__(self) -> None:
        # 同梱モデルがあれば直接ロード（配布ビルド・オフライン）、無ければ HF から取得
        if has_bundled_model():
            self.tagger = WDTagger(model_dir=BUNDLE_MODEL_DIR)
        else:
            self.tagger = WDTagger(cache_dir=HF_CACHE)
        self.vocab = build_hair_vocab(self.tagger.general_names)
        self.vocab_index = {t: i for i, t in enumerate(self.vocab)}

        # ファイルは construction 時に解決（起動時 sync 後の最新を拾う）
        products = json.loads(data_file("products.json").read_text(encoding="utf-8"))
        self.product_by_id = {p["product_id"]: p for p in products}
        self.stats = {}
        stats_f = data_file("product_stats.json")
        if stats_f.exists():
            self.stats = json.loads(stats_f.read_text(encoding="utf-8"))
        # 商品ごとのBOOTHタグ（表記ゆれ正規化済み）。商品名＋タグのキーワード検索に使う。
        self.product_tags = {pid: [normalize_ja(str(t)) for t in (s.get("tags") or [])]
                             for pid, s in self.stats.items()}
        # 概要欄（表記ゆれ正規化済み）。キーワード検索のみに使い、表示はしない。
        self.product_desc = {pid: normalize_ja(str(s.get("desc") or ""))
                             for pid, s in self.stats.items()}
        hv = json.loads(data_file("hair_vectors.json").read_text(encoding="utf-8"))

        self.pids = [pid for pid in hv if pid in self.product_by_id]
        self.hair_vectors = {pid: hv[pid] for pid in self.pids}
        P = np.stack([self._vec(hv[pid]) for pid in self.pids])

        # IDF重み: log(N/df)+1、df は各タグが >=0.2 で立つ商品数
        df = np.sum(P >= 0.2, axis=0)
        self.weights = np.log((P.shape[0] + 1) / (df + 1)).astype(np.float32) + 1.0

        Pw = P * self.weights
        self.Pn = Pw / (np.linalg.norm(Pw, axis=1, keepdims=True) + 1e-9)

        # 対応アバター情報（あれば）
        self.product_avatars: dict[str, set[str]] = {}
        if PRODUCT_AVATARS_FILE.exists():
            raw = json.loads(PRODUCT_AVATARS_FILE.read_text(encoding="utf-8"))
            self.product_avatars = {pid: set(av) for pid, av in raw.items()}
        self.avatar_vocab: list[str] = []
        if AVATAR_VOCAB_FILE.exists():
            self.avatar_vocab = [name for name, _cnt in
                                 json.loads(AVATAR_VOCAB_FILE.read_text(encoding="utf-8"))]
        self.avatar_aliases: dict[str, str] = {}
        if AVATAR_ALIASES_FILE.exists():
            self.avatar_aliases = json.loads(AVATAR_ALIASES_FILE.read_text(encoding="utf-8"))
        # 照合対象になりうる正規名の集合（あいまい一致用）
        self._known_avatars = set(self.avatar_vocab) | {
            a for avs in self.product_avatars.values() for a in avs}

    def resolve_avatar(self, text: str):
        """ユーザー入力のアバター名を canonical に解決。(canonical or None)。

        別名索引（しお=Sio, フィオナ=Fiona 等）→ 完全一致 → 部分一致 の順。
        """
        t = (text or "").strip()
        if not t:
            return None
        if t.lower() in self.avatar_aliases:
            return self.avatar_aliases[t.lower()]
        if t in self._known_avatars:
            return t
        low = t.lower()
        cands = [a for a in self._known_avatars if low in a.lower() or a.lower() in low]
        if cands:
            return min(cands, key=len)
        return None

    def resolve_avatars(self, texts):
        """複数のアバター入力を解決。(解決済みcanonicalリスト, 未解決リスト)。"""
        resolved, unresolved = [], []
        for x in texts:
            c = self.resolve_avatar(x)
            if c:
                if c not in resolved:
                    resolved.append(c)
            else:
                unresolved.append(x)
        return resolved, unresolved

    def compatible_with(self, pid: str, avatars) -> bool:
        """商品 pid が、指定アバター(canonical)のいずれかに対応しているか。"""
        return bool(self.product_avatars.get(pid, set()) & set(avatars))

    def _vec(self, tag_conf: dict[str, float]) -> np.ndarray:
        v = np.zeros(len(self.vocab), dtype=np.float32)
        for t, c in tag_conf.items():
            i = self.vocab_index.get(t)
            if i is not None:
                v[i] = c
        return v

    def resolve_tags(self, tokens):
        """ユーザー入力（カナ等）を WD形状タグに解決。(解決済みリスト, 未解決リスト) を返す。"""
        resolved, unresolved = [], []
        for tok in tokens:
            r = resolve_tag(tok, self.vocab)
            if r:
                if r not in resolved:
                    resolved.append(r)
            else:
                unresolved.append(tok)
        return resolved, unresolved

    def contains_any(self, pid: str, tags, thresh: float = 0.2) -> bool:
        """商品 pid が、指定タグのいずれかを thresh 以上で持つか。"""
        v = self.hair_vectors.get(pid, {})
        return any(v.get(t, 0.0) >= thresh for t in tags)

    def keyword_hit(self, pid: str, name: str, kw: str) -> bool:
        """キーワードが 商品名 / BOOTHタグ / 概要欄 のいずれかに含まれるか（アバター名検索用）。

        両辺を normalize_ja で正規化して比較するので、「みつあみ」でも
        商品側の「三つ編み」にヒットする（ひらがな/カタカナ/漢字の表記ゆれ吸収）。
        """
        kw = normalize_ja(kw)
        if kw in normalize_ja(name or ""):
            return True
        if any(kw in t for t in self.product_tags.get(pid, ())):
            return True
        return kw in self.product_desc.get(pid, "")

    def extract_hair_tags(self, image_path: str, thresh: float = 0.2) -> dict[str, float]:
        """画像から髪形状タグ(>=thresh)を確信度つきで返す（降順）。"""
        g = self.tagger.tag_image(Path(image_path))
        pairs = [(t, round(g.get(t, 0.0), 3)) for t in self.vocab if g.get(t, 0.0) >= thresh]
        return dict(sorted(pairs, key=lambda x: -x[1]))

    def search(self, query_tags: dict[str, float], top_k: int = 10) -> list[dict]:
        """タグ確信度の辞書 -> top_k の商品（スコアつき）。"""
        q = self._vec(query_tags) * self.weights
        qn = q / (np.linalg.norm(q) or 1.0)
        sims = self.Pn @ qn
        order = np.argsort(-sims)[:top_k]
        out = []
        for i in order:
            pid = self.pids[i]
            p = self.product_by_id[pid]
            out.append({
                "product_id": pid,
                "score": float(sims[i]),
                "name": p.get("name", ""),
                "url": p.get("url", f"https://booth.pm/ja/items/{pid}"),
                "thumbnail_url": p.get("thumbnail_url"),
                "shop_name": p.get("shop_name"),
                "price": p.get("price"),
                "has_vrchat_badge": p.get("has_vrchat_badge", False),
                "is_vrchat": looks_vrchat(p),
                "avatars": sorted(self.product_avatars.get(pid, set())),
                "wish": int(self.stats.get(pid, {}).get("wish", 0) or 0),
                "published_at": self.stats.get(pid, {}).get("published_at") or "",
            })
        return out
