from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image


def prepare(image: Image.Image, size: int = 1024) -> np.ndarray:
    arr = np.asarray(image.convert("RGB").resize((size, size), Image.LANCZOS), dtype=np.float32)
    arr = arr / max(float(arr.max()), 1e-6) - 0.5
    return arr.transpose(2, 0, 1)[np.newaxis].astype(np.float32)


class Matter:
    def __init__(self, model_file: Path) -> None:
        options = ort.SessionOptions()
        # Without this the arena keeps the peak allocation of the first image for the
        # whole session, which on an 8 GB machine starves the next images.
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self._session = ort.InferenceSession(str(model_file), sess_options=options,
                                             providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def matte(self, image: Image.Image) -> Image.Image:
        pred = self._session.run(None, {self._input: prepare(image)})[0][:, 0]
        low, high = float(pred.min()), float(pred.max())
        if high - low < 1e-6:
            pred = np.zeros_like(pred)
        else:
            pred = (pred - low) / (high - low)
        mask = Image.fromarray((np.squeeze(pred) * 255).astype(np.uint8), mode="L")
        return mask.resize(image.size, Image.LANCZOS)


def cutout(image: Image.Image, matte: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    rgba.putalpha(matte)
    visible = matte.point(lambda v: 255 if v else 0)
    return Image.composite(rgba, Image.new("RGBA", rgba.size), visible)
