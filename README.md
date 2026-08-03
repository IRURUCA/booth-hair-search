# 画像から探す髪型検索ツール【booth-hair-search】

アバターのスクリーンショットや髪型画像から、**BOOTH の似た髪型商品を探す**Windows 向けツール。
「これ、どの髪型に似てるやつ売ってるかな？」を画像から探せます。

- 画像を入れる → 髪型タグを自動抽出 → **気になる特徴を手で足す** → 似た商品を一覧
- 見つけた候補はそのまま **BOOTH 商品ページへリンク**
- インストール不要・**ダブルクリックで起動**（推論はすべてローカル / GPU 不要）

> 完全自動で「1件を当てる」ツールではありません。**候補を出して人が選ぶ**設計です。
> 髪色は改変で最も変わるため、あえて色は無視して「形・長さ・結い方」で照合します。

---

## ダウンロードして使う（Windows）

1. **[最新版をダウンロード](https://github.com/IRURUCA/booth-hair-search/releases/latest)**（`booth-hair-search-win-x64.zip`）
2. zip を **書き込み可能な場所**（ダウンロード / デスクトップ等。`Program Files` は不可）に解凍
3. `booth-hair-search.exe` をダブルクリック → **自動でブラウザが開きます**
4. 画像をアップロード → 「① タグ抽出」→（必要なら「ツインテール」等をカナで追加）→「② 検索」

### 注意
- **Windows (x64) 専用** / **ネット接続が必要**（サムネ表示・商品リンクのため。検索自体はオフラインでも動きます）
- 初回起動で **「Windows によって PC が保護されました（発行元不明）」** の警告が出ます。
  署名なしのため正常です → **「詳細情報」→「実行」** で起動してください
- ウイルス対策ソフトが誤検知することがあります（PyInstaller 製 exe のため）

## 機能

- 髪型タグの**自動抽出＋手修正**（日本語カナ入力OK：`ツインテール`→`twintails` 等に自動変換）
- 「選択タグを含む商品だけ」に絞り込み
- 並び替え：**類似度順 / 類似＋スキ / 類似＋新着**
- 10 件ずつのページ送り、♡スキ数表示
- 対象は BOOTH「3D髪型」カテゴリ 約 2,100 件（**自動で定期更新**）

## データの取り扱い

BOOTH の公開情報を「独自の検索・レコメンド」に活用します（BOOTH のスクレイピング
ガイドライン 2025-10 改定に沿う方針）。

- **BOOTH の商品画像（サムネイル）はアプリに同梱・再配布しません。**
  サムネは表示時に、各利用者の端末が BOOTH から直接取得してキャッシュします
  （ブラウザで商品ページを見るのと同じ、閲覧のための取得です）。
- 配布・保持するのは**検索用のタグベクトルと商品 URL のみ**です。
- **商品ファイル本体（zip / unitypackage 等）は取得も配布もしません。**
- 検索結果は必ず **BOOTH 商品ページへのリンク**を伴い、購入は BOOTH で行われます。
- クロールは直列・低速・キャッシュ利用で、サーバーに過負荷をかけません。

**掲載取り下げ等のご要望**は X [@irukavrchat](https://x.com/irukavrchat) までご連絡ください。速やかに対応します。

## 開発 / ソースから実行

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
python src/step7_ui.py
```

初回はタグ推論モデル（WD Tagger v3, 約 400MB）を自動ダウンロードします。

- 検索の中核: [`src/matcher.py`](src/matcher.py)（WD Tagger v3 + IDF 重み付きコサイン照合）
- UI: [`src/step7_ui.py`](src/step7_ui.py)（Gradio）
- 差分更新: [`src/step13_update.py`](src/step13_update.py) を GitHub Actions が週1実行
- 実行ファイルのビルド手順: [`packaging/BUILD.md`](packaging/BUILD.md)

## ライセンス

- 本ソフトウェアのコード: **MIT License**（[LICENSE](LICENSE)）
- 同梱・利用するモデル／ライブラリの著作権・ライセンス: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 謝辞

- タグ推論モデル: [WD Tagger v3 — SmilingWolf](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3)（Apache-2.0）
- 商品情報の提供元: [BOOTH](https://booth.pm)
