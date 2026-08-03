"""
起動時のベクトルDB自動更新。

GitHub 上の最新 data/*.json（Actions が週1で差分更新している）を取得し、
手元のものより新しければ差し替える。ネットワーク不可・取得失敗時は同梱版を使う
（＝オフラインでも動く）。取得するのはベクトル等のJSONのみ（画像は取得しない）。

配布時は REPO を自分のリポジトリに合わせること。環境変数で無効化も可:
  BOOTH_HAIR_NO_SYNC=1  → 更新をスキップ
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

from booth_client import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

REPO = "IRURUCA/booth-hair-search"
BRANCH = "main"
FILES = ["products.json", "hair_vectors.json", "hair_vocab.json", "product_stats.json"]
BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/data/"


def sync_db(timeout: int = 15) -> int:
    """最新DBを取得して差し替える。差し替えたファイル数を返す。失敗は無視。"""
    if os.environ.get("BOOTH_HAIR_NO_SYNC"):
        return 0
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    updated = 0
    for name in FILES:
        try:
            r = session.get(BASE + name, timeout=timeout)
            if r.status_code != 200 or not r.content:
                continue
            json.loads(r.content)  # 壊れたJSONで上書きしない
            dest = DATA_DIR / name
            if not dest.exists() or dest.read_bytes() != r.content:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                updated += 1
        except (requests.RequestException, ValueError):
            continue  # ネット不可・不正JSON等 → 同梱版のまま
    return updated


if __name__ == "__main__":
    n = sync_db()
    print(f"DB更新: {n} ファイル差し替え", file=sys.stderr)
