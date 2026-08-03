# 配布パッケージのビルド手順（ノーセットアップ実行ファイル）

目標: **ダウンロードしてダブルクリックするだけ**で起動するローカルアプリ。
セットアップ不要、サムネは表示時に BOOTH から取得（画像は同梱しない）。

> ✅ 下記手順で Windows 実機ビルド・起動・検索・サムネ都度取得まで動作確認済み
>   （dist フォルダ約 686MB、exe 20MB、同梱モデルでオフライン推論、
>    サムネは exe 隣の `booth-hair-search-data/images/` にキャッシュ）。
>   環境が変われば微調整が要る場合があります。

## 方針

- **同梱するもの**: `src/`、`data/*.json`（4ファイル）、WD Tagger モデル、依存ライブラリ、
  `licenses/`（モデル・全依存のライセンス文。再配布条件のため必須）
- **同梱しないもの**: `images/`（＝BOOTHサムネ。表示時に取得＆キャッシュ）、`cache/`、`.venv/`
- 初回起動でモデルDLが走らないよう、**モデルもパッケージに含める**（オフラインでもタグ抽出可）

## 1. モデルを同梱用に用意（`model/` へ2ファイルをコピー）

`src/wd_tagger.py` は `model_dir=` を受け取ると `model.onnx` + `selected_tags.csv` を
直接ロードする（HF不要・オフライン）。`src/paths.py` は凍結時 `model/` を同梱先として見る。

```bash
# cache/hf にDL済みの swinv2 モデルから、flat な model/ へコピー
SNAP="cache/hf/models--SmilingWolf--wd-swinv2-tagger-v3/snapshots/<hash>"
mkdir -p model
cp "$SNAP/model.onnx" model/model.onnx
cp "$SNAP/selected_tags.csv" model/selected_tags.csv
```
（`<hash>` は `snapshots/` 直下のフォルダ名。eva02(1.2GB)は同梱しないこと）

## 2. ライセンス文を収集（配布の必須条件）

同梱するモデル（Apache-2.0）・ライブラリ（MIT/BSD/Apache 等）は、**再配布時に
ライセンス全文と著作権表示の添付が必要**（Apache-2.0 §4(a) など）。ビルド venv の
全パッケージ（間接依存含む）から自動収集する:

```bash
# リポジトリ直下から実行 → licenses/ が生成される（spec が zip に同梱）
python packaging/collect_licenses.py
```

「license file無し」と報告されたパッケージがあれば、配布前に表記を確認すること。

## 3. PyInstaller でビルド（spec 使用・確認済み）

```bash
pip install pyinstaller
# リポジトリ直下から実行
pyinstaller packaging/booth-hair-search.spec --noconfirm --distpath dist --workpath build
```

- spec が `collect_all("gradio"/"onnxruntime"…)` と `data/*.json`・`model/` の同梱を行う
- spec 内の相対パスは spec 位置基準になるため、`SPECPATH` からリポジトリ直下を解決している
- 出力は `dist/booth-hair-search/`（フォルダ配布、約686MB）。`booth-hair-search.exe` を起動
- 配布は `dist/booth-hair-search/` を zip して配る（例: GitHub Release にアップロード）

## 4. 既知のハマりどころ

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

## 5. 動作確認チェックリスト

- [ ] `dist/booth-hair-search/licenses/` にライセンス文一式が入っている
- [ ] `images/` が空の状態で起動できる
- [ ] 画像アップ → タグ抽出（オフラインでも動く＝モデル同梱OK）
- [ ] 検索 → サムネが表示される（＝表示時取得が動く、ネット必要）
- [ ] 2回目のサムネ表示が速い（＝キャッシュが効く）
- [ ] 起動時に最新DB取得が走る（`db_update`）／ネット無しでも同梱DBで動く

## 代替案（PyInstaller が難しい場合）

**ポータブルPython同梱**: 埋め込み用Python + 依存 + `src/` を1フォルダにまとめ、
`起動.bat`（`python\python.exe src\step7_ui.py`）を置く方式。ビルドが単純で確実。
UXは「フォルダを解凍して bat をダブルクリック」。
