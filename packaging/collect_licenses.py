"""
配布用ライセンス収集スクリプト。ビルド前にリポジトリ直下から実行する:

  python packaging/collect_licenses.py

ビルド venv にインストールされている全パッケージ（PyInstaller が exe に同梱する
間接依存を含む）のライセンス文を licenses/ に集める。Apache-2.0 §4(a) と
MIT/BSD の「再配布時はライセンス文・著作権表示を添付する」条件を満たすため、
生成された licenses/ フォルダは配布 zip に必ず同梱すること（spec が同梱する）。

併せて以下もコピーする:
- 本体の LICENSE / THIRD_PARTY_NOTICES.md
- WD Tagger v3 モデル（SmilingWolf, Apache-2.0）用のライセンス正文
"""
from __future__ import annotations

import re
import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "licenses"
APACHE_TXT = Path(__file__).resolve().parent / "LICENSE-2.0-apache.txt"

# dist-info 内でライセンス・著作権表示とみなすファイル名
LICENSE_RE = re.compile(
    r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)", re.IGNORECASE)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # --- 本体・モデル ---
    shutil.copy(ROOT / "LICENSE", OUT / "booth-hair-search.LICENSE.txt")
    shutil.copy(ROOT / "THIRD_PARTY_NOTICES.md", OUT / "THIRD_PARTY_NOTICES.md")
    shutil.copy(APACHE_TXT, OUT / "wd-tagger-v3-model.APACHE-2.0.txt")

    # --- インストール済み全パッケージ ---
    index_lines: list[str] = []
    missing: list[str] = []
    for dist in sorted(distributions(), key=lambda d: (d.metadata.get("Name") or "").lower()):
        name = dist.metadata["Name"]
        if not name:
            continue
        version = dist.version or "unknown"
        meta = dist.metadata
        lic = (meta.get("License-Expression") or meta.get("License") or "").strip()
        if len(lic) > 100:  # License フィールドに全文が入っている古いパッケージ対策
            lic = meta.get("Classifier") or "see license file"
        pkg_dir = OUT / f"{name}-{version}"

        copied = 0
        for f in (dist.files or []):
            parts = f.parts
            if not any(p.endswith(".dist-info") for p in parts):
                continue
            if not LICENSE_RE.match(f.name):
                continue
            src = dist.locate_file(f)
            try:
                if Path(src).is_file():
                    pkg_dir.mkdir(exist_ok=True)
                    shutil.copy(src, pkg_dir / f.name)
                    copied += 1
            except OSError:
                pass

        if copied:
            index_lines.append(f"- {name} {version} ({lic or 'license file included'})")
        else:
            # ライセンスファイルが dist-info に無い → メタデータの表記を残す
            missing.append(f"- {name} {version}: {lic or 'ライセンス表記なし(要手動確認)'}")
            index_lines.append(f"- {name} {version} ({lic or '要確認'}) ※license file無し")

    (OUT / "INDEX.md").write_text(
        "# 同梱パッケージのライセンス一覧\n\n"
        "本フォルダには、配布物に同梱される各パッケージのライセンス文を収録しています。\n\n"
        + "\n".join(index_lines) + "\n",
        encoding="utf-8")

    print(f"収集完了: {OUT} （{len(index_lines)} パッケージ）")
    if missing:
        print("\nライセンスファイルが見つからなかったパッケージ（メタデータ表記のみ）:")
        print("\n".join(missing))
        print("→ 配布前に上記の表記が妥当か確認してください。")


if __name__ == "__main__":
    sys.exit(main())
