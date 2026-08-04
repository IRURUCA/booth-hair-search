# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec。リポジトリ直下から実行すること:
#   pyinstaller packaging/booth-hair-search.spec --noconfirm
# 出力: dist/booth-hair-search/（フォルダ配布）
import os
from PyInstaller.utils.hooks import collect_all

# spec 内の相対パスは spec の場所基準になるため、リポジトリ直下を絶対パスで解決
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas = []
binaries = []
hiddenimports = []

# Gradio / onnxruntime は付随データ・ネイティブDLLが多く、collect_all が必須
for pkg in ["gradio", "gradio_client", "onnxruntime", "safehttpx", "groovy"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# アプリのデータ（ベクトル等）とモデル（同梱＝オフラインでタグ抽出可）
datas += [
    (os.path.join(ROOT, "data", "products.json"), "data"),
    (os.path.join(ROOT, "data", "hair_vectors.json"), "data"),
    (os.path.join(ROOT, "data", "hair_vocab.json"), "data"),
    (os.path.join(ROOT, "data", "product_stats.json"), "data"),
    (os.path.join(ROOT, "data", "jp_synonyms.json"), "data"),
    (os.path.join(ROOT, "data", "full_vectors.json"), "data"),
    (os.path.join(ROOT, "model", "model.onnx"), "model"),
    (os.path.join(ROOT, "model", "selected_tags.csv"), "model"),
]

# ライセンス文の同梱（Apache-2.0 §4(a)・MIT/BSD の再配布条件を満たすため必須）。
# 無ければビルドを止める: 先に `python packaging/collect_licenses.py` を実行すること。
LICENSES_DIR = os.path.join(ROOT, "licenses")
if not os.path.isdir(LICENSES_DIR):
    raise SystemExit(
        "licenses/ がありません。先に `python packaging/collect_licenses.py` を実行してください。"
    )
datas += [(LICENSES_DIR, "licenses")]

a = Analysis(
    [os.path.join(ROOT, "src", "step7_ui.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "opencv-python", "cv2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="booth-hair-search",
    console=True,   # 初回は挙動確認のためコンソール表示。安定したら False も可
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="booth-hair-search",
)
