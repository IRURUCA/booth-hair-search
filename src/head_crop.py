"""
頭部クロップ（チューニング①）。

アニメ顔検出（lbpcascade_animeface）で顔を見つけ、髪を含むように上下左右へ広げて
切り出す。背景・衣装・体を落として「髪の識別情報」を相対的に濃くするのが狙い。

- 顔が複数見つかったら最大の顔を採用
- 顔が見つからなければ None を返す（呼び出し側で元画像にフォールバック）
- 長い髪を切り落とさないよう縦方向は下に広めに取る
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CASCADE_PATH = ROOT / "cache" / "lbpcascade_animeface.xml"

# 顔ボックスからの拡大率（髪を含める）
EXPAND_X = 1.4    # 顔幅の左右にこの倍率ぶん広げる
EXPAND_UP = 1.5   # 顔の高さのこの倍率ぶん上へ（トップの髪・アホ毛）
EXPAND_DOWN = 3.5  # 顔の高さのこの倍率ぶん下へ（ロングヘア）

_cascade: cv2.CascadeClassifier | None = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _cascade
    if _cascade is None:
        c = cv2.CascadeClassifier(str(CASCADE_PATH))
        if c.empty():
            raise RuntimeError(f"カスケードを読めません: {CASCADE_PATH}")
        _cascade = c
    return _cascade


def detect_largest_face(bgr: np.ndarray):
    """最大の顔 (x, y, w, h) を返す。無ければ None。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    faces = _get_cascade().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
    )
    if len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def crop_head(img: Image.Image) -> Image.Image | None:
    """PIL画像から頭部（髪込み）を切り出す。顔が無ければ None。"""
    rgb = img.convert("RGB")
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    face = detect_largest_face(bgr)
    if face is None:
        return None

    x, y, w, h = face
    cx = x + w / 2.0
    half = w * (0.5 + EXPAND_X)
    left = int(round(cx - half))
    right = int(round(cx + half))
    top = int(round(y - h * EXPAND_UP))
    bottom = int(round(y + h + h * EXPAND_DOWN))

    W, H = rgb.size
    left = max(0, left)
    top = max(0, top)
    right = min(W, right)
    bottom = min(H, bottom)
    if right - left < 8 or bottom - top < 8:
        return None
    return rgb.crop((left, top, right, bottom))
