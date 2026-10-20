"""Compare PhotoCraft's classic Remove Background with open matting models.

    python compare.py --cli <photocraft-cli.exe> [--models isnet,rmbg-1.4] [--cutouts]

For every photo in photos/ this writes the alpha each method produces to
results/mattes/<photo>__<method>.png, the timings and peak memory to results/measurements.json,
and the two comparison grids to results/. Each model runs in its own process, so the peak
committed memory is per model. Windows only (the memory figures come from the Win32 API).

Methods:
  classic        photocraft-cli run <photo> --cmd layer.removeBackground (time includes CLI startup)
  isnet          rembg "isnet-general-use" (Apache-2.0)
  rmbg-1.4       BRIA RMBG-1.4 through rembg's dis_custom session (non-commercial license)
  birefnet-lite  rembg "birefnet-general-lite" (MIT); needs about 6.4 GB of free memory
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHOTOS = HERE / "photos"
RESULTS = HERE / "results"
MATTES = RESULTS / "mattes"
CUTOUTS = RESULTS / "cutouts"
MEASUREMENTS = RESULTS / "measurements.json"

RMBG14_URL = "https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx"
RMBG14_SHA256 = "8cafcf770b06757c4eaced21b1a88e57fd2b66de01b8045f35f01535ba742e0f"
LABELS = {"classic": "PhotoCraft 0.10 classic", "isnet": "ISNet (DIS)",
          "birefnet-lite": "BiRefNet-lite", "rmbg-1.4": "BRIA RMBG-1.4"}
COLUMN_ORDER = ["classic", "isnet", "birefnet-lite", "rmbg-1.4"]
EDGE_CROPS = [("portrait-hair", (0.08, 0.02, 0.48, 0.52)), ("animal-fur", (0.30, 0.45, 0.70, 0.95)),
              ("thin-structures", (0.55, 0.50, 0.92, 0.98))]
GREEN = (40, 170, 90, 255)


class _MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(name, ctypes.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


def peak_commit_gb(handle=None) -> float | None:
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_MemoryCounters), wt.DWORD]
    ok = psapi.GetProcessMemoryInfo(handle or kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PeakPagefileUsage / 2**30 if ok else None


def photos() -> list[Path]:
    return sorted(PHOTOS.glob("*.jpg"))


def record(method: str, data: dict) -> None:
    everything = json.loads(MEASUREMENTS.read_text()) if MEASUREMENTS.exists() else {}
    everything[method] = data
    MEASUREMENTS.write_text(json.dumps(everything, indent=2))


def save_outputs(photo: Path, method: str, matte, write_cutout: bool) -> None:
    from PIL import Image
    matte.save(MATTES / f"{photo.stem}__{method}.png", optimize=True)
    if write_cutout:
        CUTOUTS.mkdir(exist_ok=True)
        rgba = Image.open(photo).convert("RGBA")
        rgba.putalpha(matte)
        rgba.save(CUTOUTS / f"{photo.stem}__{method}.png")


def run_classic(cli: str, write_cutout: bool) -> None:
    from PIL import Image
    times, peaks = {}, []
    scratch = RESULTS / "classic-tmp.png"
    for photo in photos():
        started = time.perf_counter()
        proc = subprocess.Popen([cli, "run", str(photo), "--cmd", "layer.removeBackground", "--out", str(scratch)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait()
        times[photo.stem] = round(time.perf_counter() - started, 2)
        # Popen keeps the process handle open after exit, so the peak can still be read.
        peaks.append(peak_commit_gb(int(proc._handle)))
        if proc.returncode != 0:
            raise SystemExit(f"photocraft-cli failed on {photo.name}")
        save_outputs(photo, "classic", Image.open(scratch).convert("RGBA").getchannel("A"), write_cutout)
    scratch.unlink(missing_ok=True)
    record("classic", {"seconds_per_image": times, "peak_commit_gb": round(max(p for p in peaks if p), 2)})
    print("classic", times)


def _prepare(method: str) -> tuple[str, dict]:
    """Return rembg's session name and arguments, with the model file already downloaded."""
    from rembg.sessions import sessions
    from rembg.sessions.base import BaseSession
    if method == "rmbg-1.4":
        # rembg only loads custom models from inside its own data folder.
        model = Path(BaseSession.rembg_home()) / "models" / "bria-rmbg-1.4" / "model.onnx"
        if not model.is_file():
            model.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(RMBG14_URL, model)
        with model.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != RMBG14_SHA256:
                raise SystemExit(f"{model} does not match the published RMBG-1.4 file")
        return "dis_custom", {"model_path": str(model)}
    name = {"isnet": "isnet-general-use", "birefnet-lite": "birefnet-general-lite"}.get(method)
    if name is None:
        raise SystemExit(f"unknown method {method}")
    sessions[name].download_models()
    return name, {}


def run_model(method: str, write_cutout: bool) -> None:
    import onnxruntime as ort
    from PIL import Image
    from rembg import new_session, remove
    name, arguments = _prepare(method)
    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    started = time.perf_counter()
    session = new_session(name, sess_opts=options, **arguments)
    load = time.perf_counter() - started
    times = {}
    for photo in photos():
        started = time.perf_counter()
        image = Image.open(photo).convert("RGB")
        matte = remove(image, session=session, only_mask=True, post_process_mask=False).convert("L")
        save_outputs(photo, method, matte, write_cutout)
        times[photo.stem] = round(time.perf_counter() - started, 2)
    record(method, {"model_load_seconds": round(load, 2), "seconds_per_image": times,
                    "peak_commit_gb": round(peak_commit_gb(), 2)})
    print(method, times)


def _on_green(photo: Path, method: str, size=None, box=None):
    from PIL import Image
    rgba = Image.open(photo).convert("RGBA")
    rgba.putalpha(Image.open(MATTES / f"{photo.stem}__{method}.png").convert("L"))
    if box:
        rgba = rgba.crop(box)
    if size:
        rgba = rgba.resize(size, Image.LANCZOS)
    canvas = Image.new("RGBA", rgba.size, GREEN)
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def build_grids() -> None:
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype("arialbd.ttf", 16)
    methods = [m for m in COLUMN_ORDER if (MATTES / f"{photos()[0].stem}__{m}.png").exists()]

    width, top, gap = 360, 34, 4
    rows = []
    for photo in photos():
        original = Image.open(photo).convert("RGB")
        height = round(original.height * width / original.width)
        rows.append([original.resize((width, height), Image.LANCZOS)]
                    + [_on_green(photo, m, (width, height)) for m in methods])
    labels = ["original"] + [LABELS[m] for m in methods]
    grid = Image.new("RGB", (width * len(labels) + gap * (len(labels) - 1), top + sum(r[0].height + gap for r in rows)),
                     "white")
    draw = ImageDraw.Draw(grid)
    for i, label in enumerate(labels):
        draw.text((i * (width + gap) + 6, 8), label, fill="black", font=font)
    y = top
    for row in rows:
        for i, cell in enumerate(row):
            grid.paste(cell, (i * (width + gap), y))
        y += row[0].height + gap
    grid.save(RESULTS / "comparison.jpg", quality=88)

    crop_height = 400
    rows = []
    for stem, (a, b, c, d) in EDGE_CROPS:
        photo = PHOTOS / f"{stem}.jpg"
        original = Image.open(photo).convert("RGB")
        box = (int(a * original.width), int(b * original.height), int(c * original.width), int(d * original.height))
        size = (round((box[2] - box[0]) * crop_height / (box[3] - box[1])), crop_height)
        rows.append([original.crop(box).resize(size, Image.LANCZOS)]
                    + [_on_green(photo, m, size, box) for m in methods])
    labels = ["original"] + [LABELS[m] for m in methods]
    grid = Image.new("RGB", (max(sum(c.width + gap for c in r) - gap for r in rows), top + (crop_height + gap) * len(rows)),
                     "white")
    draw = ImageDraw.Draw(grid)
    x = 0
    for label, cell in zip(labels, rows[0]):
        draw.text((x + 6, 8), label, fill="black", font=font)
        x += cell.width + gap
    for i, row in enumerate(rows):
        x = 0
        for cell in row:
            grid.paste(cell, (x, top + i * (crop_height + gap)))
            x += cell.width + gap
    grid.save(RESULTS / "comparison-edges.jpg", quality=90)
    print("grids written to", RESULTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cli", help="path to photocraft-cli.exe (for the classic column)")
    parser.add_argument("--models", default="isnet,rmbg-1.4", help="comma-separated: isnet, rmbg-1.4, birefnet-lite")
    parser.add_argument("--cutouts", action="store_true", help="also write RGBA cut-outs to results/cutouts/")
    parser.add_argument("--run-model", help=argparse.SUPPRESS)
    args = parser.parse_args()
    MATTES.mkdir(parents=True, exist_ok=True)

    if args.run_model:
        run_model(args.run_model, args.cutouts)
        return 0
    if args.cli:
        run_classic(args.cli, args.cutouts)
    failed = []
    for method in [m for m in args.models.split(",") if m]:
        command = [sys.executable, __file__, "--run-model", method] + (["--cutouts"] if args.cutouts else [])
        if subprocess.run(command).returncode != 0:
            failed.append(method)
            print(f"{method} failed; see the error above")
    build_grids()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
