"""
WD Tagger v3 (SmilingWolf/wd-swinv2-tagger-v3) を ONNX Runtime CPU で回すラッパー。

- huggingface_hub でモデル(model.onnx)とタグ定義(selected_tags.csv)を取得
- 前処理は SmilingWolf 公式実装に準拠:
  正方形に白背景でパディング → 指定サイズにリサイズ → RGB を BGR に →
  float32・0〜255 スケール・NHWC
- 出力は sigmoid 済み確率（0〜1）。general カテゴリのタグのみ返す
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
from huggingface_hub import hf_hub_download
from PIL import Image

MODEL_REPO = "SmilingWolf/wd-swinv2-tagger-v3"
MODEL_FILE = "model.onnx"
LABEL_FILE = "selected_tags.csv"

# selected_tags.csv の category 列: 0=general, 4=character, 9=rating
CAT_GENERAL = 0


class WDTagger:
    def __init__(self, cache_dir: Path | None = None, repo: str = MODEL_REPO) -> None:
        model_path = hf_hub_download(repo, MODEL_FILE, cache_dir=cache_dir)
        label_path = hf_hub_download(repo, LABEL_FILE, cache_dir=cache_dir)

        self.session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        # 入力形状 (1, H, W, 3) から一辺を取得
        _, h, _w, _ = self.session.get_inputs()[0].shape
        self.target_size = int(h)

        df = pd.read_csv(label_path)
        self.tag_names: list[str] = df["name"].tolist()
        self.general_idx = np.where(df["category"].values == CAT_GENERAL)[0]
        self.general_names = [self.tag_names[i] for i in self.general_idx]

    # --- 前処理 ---
    def _preprocess(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGBA")
        # 透過を白背景に合成
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        img = canvas.convert("RGB")

        # 正方形に白パディング
        w, h = img.size
        side = max(w, h)
        square = Image.new("RGB", (side, side), (255, 255, 255))
        square.paste(img, ((side - w) // 2, (side - h) // 2))

        square = square.resize((self.target_size, self.target_size), Image.BICUBIC)
        arr = np.asarray(square, dtype=np.float32)  # (S, S, 3) RGB 0-255
        arr = arr[:, :, ::-1]  # RGB -> BGR
        return arr[np.newaxis, ...]  # (1, S, S, 3)

    def tag_image(self, path: Path, crop: bool = False) -> dict[str, float]:
        """general タグ名 -> 確信度(0..1) の辞書（全 general タグ分）を返す。

        crop=True のとき頭部クロップを試み、顔が見つかればその領域だけを使う。
        顔が見つからなければ元画像にフォールバックする。
        """
        with Image.open(path) as im:
            im.load()
            src = im
            if crop:
                from head_crop import crop_head
                cropped = crop_head(im)
                if cropped is not None:
                    src = cropped
            batch = self._preprocess(src)
        preds = self.session.run(None, {self.input_name: batch})[0][0]  # (N,)
        preds = preds.astype(np.float32)
        # 念のため: 0..1 の範囲外なら sigmoid をかける
        if preds.min() < 0.0 or preds.max() > 1.0:
            preds = 1.0 / (1.0 + np.exp(-preds))
        return {self.tag_names[i]: float(preds[i]) for i in self.general_idx}
