"""
実行環境（開発 / PyInstaller凍結）に応じたパス解決を一元化。

- 読み取り専用の同梱リソース（初期DB・モデル）は BUNDLE_ROOT（凍結時は sys._MEIPASS）
- 書き込みが必要なもの（サムネキャッシュ・更新後DB）は USER_ROOT（凍結時は exe と同じ場所）
  → sys._MEIPASS は一時展開・読み取り専用なので、そこには書かない

開発時（非凍結）は BUNDLE_ROOT == USER_ROOT == リポジトリ直下 なので従来通り。
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    USER_ROOT = Path(sys.executable).resolve().parent / "booth-hair-search-data"
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent.parent
    USER_ROOT = BUNDLE_ROOT

# 読み取り専用（同梱）
BUNDLE_DATA = BUNDLE_ROOT / "data"
BUNDLE_MODEL_DIR = BUNDLE_ROOT / "model"      # 凍結時: model.onnx + selected_tags.csv を同梱
HF_CACHE = BUNDLE_ROOT / "cache" / "hf"       # 開発時のモデルDLキャッシュ

# 書き込み可能
USER_DATA = USER_ROOT / "data"                # 起動時更新DBの保存先
IMAGES_DIR = USER_ROOT / "images"             # サムネのローカルキャッシュ


def data_file(name: str) -> Path:
    """更新済み(USER_DATA)を優先、無ければ同梱(BUNDLE_DATA)を返す。"""
    u = USER_DATA / name
    return u if u.exists() else BUNDLE_DATA / name


def has_bundled_model() -> bool:
    return (BUNDLE_MODEL_DIR / "model.onnx").exists()
