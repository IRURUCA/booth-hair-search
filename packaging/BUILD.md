# 配布パッケージのビルド手順（ノーセットアップ実行ファイル）

目標: **ダウンロードしてダブルクリックするだけ**で起動するローカルアプリ。
セットアップ不要、サムネは表示時に BOOTH から取得（画像は同梱しない）。

> ⚠️ この手順は出発点です。PyInstaller × Gradio × onnxruntime の同梱は
> 環境依存のクセがあり、**実機での試行錯誤（数回のビルド）が必要**です。
> まず動くところまで持っていってから配布してください。

## 方針

- **同梱するもの**: `src/`、`data/*.json`（4ファイル）、WD Tagger モデル、依存ライブラリ
- **同梱しないもの**: `images/`（＝BOOTHサムネ。表示時に取得＆キャッシュ）、`cache/`、`.venv/`
- 初回起動でモデルDLが走らないよう、**モデルもパッケージに含める**（オフラインでもタグ抽出可）

## 1. モデルを同梱用に用意

現在モデルは `cache/hf` に hf_hub_download でDL済み。これをパッケージに同梱し、
実行時は `HF_HUB_OFFLINE=1` ＋ `cache_dir=<同梱パス>` でオフライン読み込みさせる。
（`src/wd_tagger.py` は既に `cache_dir` を受け取れる。配布ビルドでは同梱パスを渡す）

## 2. PyInstaller でビルド（Windows 例）

```bat
pip install pyinstaller
pyinstaller --noconfirm --name booth-hair-search ^
  --collect-all gradio ^
  --collect-all gradio_client ^
  --collect-all onnxruntime ^
  --collect-data safehttpx ^
  --collect-data groovy ^
  --add-data "data;data" ^
  --add-data "cache/hf;cache/hf" ^
  src/step7_ui.py
```

- `--collect-all gradio` … Gradio はテンプレ/静的ファイルが多く、これが無いと起動時に落ちる（最重要）
- `--add-data "data;data"` … ベクトル等のJSONを同梱（Windowsは区切りが `;`、mac/Linuxは `:`）
- `--add-data "cache/hf;cache/hf"` … モデルを同梱
- 出力は `dist/booth-hair-search/`（フォルダ配布）。単一exeにしたいなら `--onefile`（起動が遅くなる・一時展開する点に注意）

## 3. 既知のハマりどころ

- **Gradio が起動時に data files を探して FileNotFoundError** → `--collect-all gradio` を確認
- **onnxruntime のネイティブDLLが見つからない** → `--collect-all onnxruntime`
- **`data/` や `cache/hf` が実行時に見つからない** → PyInstaller 展開先は `sys._MEIPASS`。
  `ROOT` の解決を、凍結時は `sys._MEIPASS` を見るように分岐する必要がある場合あり
  （`getattr(sys, "_MEIPASS", ...)`）。`src/matcher.py` / `db_update.py` の `ROOT` 参照を要調整
- **起動が遅い** → `--onefile` をやめてフォルダ配布にする
- **書き込み先に注意（重要）**: アプリは実行中に**書き込む**——サムネのローカルキャッシュ
  (`images/`) と、起動時更新後の `data/*.json`。PyInstaller の同梱先(`sys._MEIPASS`)は
  読み取り専用・一時展開なので**そこへ書いてはいけない**。書き込み系のパス
  （`THUMB_CACHE` / `db_update` の保存先）は、**exe と同じフォルダ**か
  **`%LOCALAPPDATA%\booth-hair-search\`** など**ユーザー書き込み可能な場所**に向けること。
  読み取り専用の同梱DB（初期ベクトル・モデル）と、書き込み可能なキャッシュ/更新DBを
  パスで分ける設計が必要。

## 4. 動作確認チェックリスト

- [ ] `images/` が空の状態で起動できる
- [ ] 画像アップ → タグ抽出（オフラインでも動く＝モデル同梱OK）
- [ ] 検索 → サムネが表示される（＝表示時取得が動く、ネット必要）
- [ ] 2回目のサムネ表示が速い（＝キャッシュが効く）
- [ ] 起動時に最新DB取得が走る（`db_update`）／ネット無しでも同梱DBで動く

## 代替案（PyInstaller が難しい場合）

**ポータブルPython同梱**: 埋め込み用Python + 依存 + `src/` を1フォルダにまとめ、
`起動.bat`（`python\python.exe src\step7_ui.py`）を置く方式。ビルドが単純で確実。
UXは「フォルダを解凍して bat をダブルクリック」。
