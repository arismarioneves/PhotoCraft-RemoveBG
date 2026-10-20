# Background removal benchmark

The script, photos and full-resolution outputs behind
[this comparison](https://github.com/storytold/photocraft/issues/2788#issuecomment-6295656662) on
storytold/photocraft#2788. It compares PhotoCraft 0.10.0's classic **Remove Background** with two
open matting models, running on the CPU of an 8 GB Windows machine.

This folder lives on its own branch so that `main`, which holds the add-on, stays small. The
benchmark does not use the add-on.

## What's here

| Path | Contents |
|---|---|
| `compare.py` | runs every method on every photo and builds the grids |
| `photos/` | the six input photos, CC0 (credits below) |
| `results/mattes/<photo>__<method>.png` | full-resolution alpha from each method, 8-bit grayscale, white = kept |
| `results/comparison.jpg`, `results/comparison-edges.jpg` | comparison grids, composited on green |

To get a cut-out, use a matte as the alpha channel of its photo. `compare.py --cutouts` does this
for you and writes RGBA PNGs to `results/cutouts/`, which is not committed.

## Method

- **Classic:** `photocraft-cli run <photo> --cmd layer.removeBackground --out <png>`, default
  parameters, from the PhotoCraft 0.10.0 Windows x64 portable build. The time includes CLI startup.
- **Models:** rembg 2.0.85 with onnxruntime 1.30.0, CPU execution provider, memory arena and memory
  pattern off. Each model runs in its own process.
  - The raw model matte is the alpha (`only_mask=True, post_process_mask=False`), with no
    post-processing and no guided filter.
  - Each model runs at its 1024² input size.
- **Times** cover decoding, inference and writing the PNG. Model load is reported separately.
- **Memory** is the peak committed (private) memory of the process, from `GetProcessMemoryInfo`.
- **Machine:** Intel Core i3-10105F (4 cores, 8 threads), 8 GB RAM, Windows 11, no usable GPU.

## Run it

Windows, Python 3.11 or newer:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python compare.py --cli C:\path\to\photocraft-cli.exe
```

- `--models` chooses the models. The default is `isnet,rmbg-1.4`; add `birefnet-lite` only if
  about 7 GB of memory is free.
- Without `--cli`, the classic column is not rerun and its previous results are kept.
- The models download on first use. rembg fetches ISNet. RMBG-1.4 comes from Hugging Face and is
  checked against its sha256.
- Each run writes its own times and peak memory to `results/measurements.json`.

## Results

| Method | Time per image | Model load | Peak committed memory |
|---|---|---|---|
| PhotoCraft classic | 0.9–2.3 s, including CLI startup | – | ~0.1 GB |
| ISNet (Apache-2.0) | 2.6–2.8 s | 0.9 s | 1.25 GB |
| BRIA RMBG-1.4 (non-commercial license) | 2.7–3.1 s | 1.6 s | 1.27 GB |
| BiRefNet-lite (MIT) | 43–98 s | – | 6.4 GB |

## Licenses

- **Script:** MIT, like the rest of this repository.
- **Photos:** CC0, from Wikimedia Commons:
  - [Wet Australian Shepherd dog, side view](https://commons.wikimedia.org/wiki/File:Wet_Australian_Shepherd_dog,_side_view.jpg), Joselodos
  - [Cute dog playing on snow](https://commons.wikimedia.org/wiki/File:Cute_dog_playing_on_snow.jpg), Savexig63
  - [Man carrying boxes on a bicycle](https://commons.wikimedia.org/wiki/File:Man_carrying_boxes_on_a_bicycle.jpg), Wilfredor
  - [Seated woman with blonde hair](https://commons.wikimedia.org/wiki/File:Seated_woman_with_blonde_hair-3177506.jpg), ivanovgood
  - [Coffee machine 2022](https://commons.wikimedia.org/wiki/File:Coffee_machine_2022.jpg), Abdulla Al Muhairi
  - [The fisherman's bicycle 2](https://commons.wikimedia.org/wiki/File:The_fisherman%27s_bicycle_2.jpg), W.carter
- **Models:** none are included; `compare.py` downloads them.
  - [ISNet (DIS)](https://github.com/xuebinqin/DIS): Apache-2.0.
  - [BiRefNet](https://github.com/ZhengPeng7/BiRefNet): MIT.
  - [BRIA RMBG-1.4](https://huggingface.co/briaai/RMBG-1.4): bria-rmbg-1.4 license, **non-commercial
    use only**. It was used here only for this non-commercial comparison. Read BRIA's license
    before using the model or its mattes for anything else.
