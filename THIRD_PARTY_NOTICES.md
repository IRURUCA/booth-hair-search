# サードパーティ表記 / Third-Party Notices

本ソフトウェアは以下のモデル・ライブラリを利用しています。各成果物の著作権は
それぞれの権利者に帰属し、対応するライセンスの条件に従って利用しています。

## モデル / Model

### WD Tagger v3 (SmilingWolf/wd-swinv2-tagger-v3)
- 著作権 / Copyright: © SmilingWolf
- ライセンス / License: Apache License 2.0
- 用途 / Use: 画像からのタグ推論（ONNX Runtime, CPU）
- 学習データ / Training data: Danbooru の画像（本ソフトはモデルの重みを推論に
  利用するのみで、学習画像そのものは含みません）
- 入手元 / Source: https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3

Apache License 2.0 の全文は http://www.apache.org/licenses/LICENSE-2.0 を参照。

## Python ライブラリ / Python libraries

| ライブラリ | ライセンス |
|---|---|
| gradio | Apache-2.0 |
| requests | Apache-2.0 |
| opencv-python-headless | Apache-2.0 |
| huggingface_hub | Apache-2.0 |
| onnxruntime | MIT |
| beautifulsoup4 | MIT |
| Pillow | HPND (MIT-CMU) |
| numpy | BSD-3-Clause |
| pandas | BSD-3-Clause |
| lxml | BSD-3-Clause |

いずれも寛容型ライセンス（Apache-2.0 / MIT / BSD）です。各ライブラリの完全な
ライセンス条文は、それぞれの配布物（`pip show <package>` や各プロジェクトの
リポジトリ）を参照してください。

## データ / Data

BOOTH（https://booth.pm ）から取得した公開情報（商品名・価格・タグ・説明文等）
および商品ページのサムネイル画像の著作権は、各出品者およびピクシブ株式会社に
帰属します。本ソフトウェアはこれらの画像を再配布しません（詳細は README の
「データの取り扱い」を参照）。
