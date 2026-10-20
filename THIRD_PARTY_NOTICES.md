# Third-party notices

None of these components is bundled in this repository: the installer downloads them from their
official sources (PyPI, the rembg releases on GitHub and Hugging Face).

| Component | Used for | License | Source |
|---|---|---|---|
| ONNX Runtime 1.30.0 | running the model | MIT | https://github.com/microsoft/onnxruntime |
| NumPy 2.4.6 | image arrays | BSD-3-Clause | https://github.com/numpy/numpy |
| Pillow 12.3.0 | reading and writing images | MIT-CMU | https://github.com/python-pillow/Pillow |
| ISNet (DIS), `isnet-general-use.onnx` | default model | Apache-2.0 | https://github.com/xuebinqin/DIS (ONNX export published by https://github.com/danielgatis/rembg) |
| BRIA RMBG-1.4 | optional model | bria-rmbg-1.4, **non-commercial use only** | https://huggingface.co/briaai/RMBG-1.4 |

The image pre- and post-processing follows what rembg does for these models
(https://github.com/danielgatis/rembg, MIT).

The test photos in `tests/fixtures` are CC0 images from Wikimedia Commons; see
[tests/fixtures/CREDITS.md](tests/fixtures/CREDITS.md).

PhotoCraft is a separate project (MIT OR Apache-2.0, https://github.com/storytold/photocraft); this
add-on only uses its documented plug-in API and control channel.
