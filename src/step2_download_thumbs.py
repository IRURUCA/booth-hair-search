"""
ステップ1-2: products.json のサムネイル画像をダウンロードして images/ に保存する。

- 1〜2秒間隔・直列（booth_client の throttle 経由）
- 既にファイルがあればスキップ（キャッシュ）
- 進捗を表示、完了後に合計サイズと失敗件数を報告
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from booth_client import BoothClient

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = ROOT / "data" / "products.json"
IMAGES_DIR = ROOT / "images"


def main() -> None:
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    client = BoothClient()

    total = len(products)
    ok = skipped = failed = 0
    failed_ids: list[str] = []

    for i, p in enumerate(products, 1):
        pid = p["product_id"]
        url = p.get("thumbnail_url")
        dest = IMAGES_DIR / f"{pid}.jpg"

        if not url:
            failed += 1
            failed_ids.append(pid)
            continue

        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
        else:
            try:
                client.get_image(url, dest)
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                failed_ids.append(pid)
                print(f"  [{i}/{total}] FAILED {pid}: {e}", file=sys.stderr, flush=True)
                continue

        if i % 25 == 0 or i == total:
            print(f"  [{i}/{total}] ok={ok} skipped={skipped} failed={failed}", file=sys.stderr, flush=True)

    total_bytes = sum(f.stat().st_size for f in IMAGES_DIR.glob("*.jpg"))
    print("\n" + "=" * 60)
    print(f"ダウンロード完了: 新規 {ok} / スキップ {skipped} / 失敗 {failed}")
    print(f"images/ 合計サイズ: {total_bytes / 1024 / 1024:.1f} MB ({len(list(IMAGES_DIR.glob('*.jpg')))} ファイル)")
    if failed_ids:
        print(f"失敗した product_id: {failed_ids}")
    print("=" * 60)


if __name__ == "__main__":
    main()
