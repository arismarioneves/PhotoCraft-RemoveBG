import numpy as np
import pytest
from PIL import Image

from conftest import FIXTURES
from removebg.matte import Matter, cutout, prepare
from removebg.models import MODELS, ensure_model


def mean_in(img, box):
    return float(np.asarray(img.crop(tuple(round(v) for v in box)), dtype=np.float32).mean())


def test_prepare_scales_by_image_max_and_centers():
    arr = prepare(Image.new("RGB", (5, 3), (255, 0, 0)))
    assert arr.shape == (1, 3, 1024, 1024) and arr.dtype == np.float32
    assert np.allclose(arr[0, 0], 0.5) and np.allclose(arr[0, 1], -0.5) and np.allclose(arr[0, 2], -0.5)


def test_prepare_uses_max_not_255():
    arr = prepare(Image.new("RGB", (4, 4), (100, 50, 0)))
    assert np.allclose(arr[0, 0], 0.5) and np.allclose(arr[0, 1], 0.0)


def test_cutout_sets_alpha_and_clears_hidden_color():
    img = Image.new("RGB", (2, 1), (10, 20, 30))
    m = Image.new("L", (2, 1))
    m.putpixel((1, 0), 200)
    out = cutout(img, m)
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0)) == (0, 0, 0, 0) and out.getpixel((1, 0)) == (10, 20, 30, 200)


@pytest.mark.model
def test_isnet_separates_subject_from_background(shared_models):
    img = Image.open(FIXTURES / "portrait-hair.jpg")
    m = Matter(ensure_model(MODELS["isnet"], report=lambda s: None)).matte(img)
    w, h = img.size
    assert m.size == img.size and m.mode == "L"
    assert mean_in(m, (0.45 * w, 0.35 * h, 0.60 * w, 0.55 * h)) > 200
    assert mean_in(m, (0.90 * w, 0.00 * h, 1.00 * w, 0.10 * h)) < 30
