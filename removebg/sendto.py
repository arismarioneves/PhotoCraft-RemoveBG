"""Explorer "Send to › Remove background": saves a transparent PNG of each image in a
"cutouts" folder next to it. Folders are scanned recursively."""
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

from .config import ConfigError, load_config, resolve_model
from .helper import user_message
from .matte import Matter, cutout
from .models import MODELS, ModelError, ensure_model

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
OUTPUT_DIR = "cutouts"


def collect(paths: list[str]) -> list[Path]:
    found, seen = [], set()
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            print(f"Not found, skipping: {path}")
            continue
        if path.is_dir():
            # Leave earlier results out, or every run would cut out its own output again.
            candidates = sorted(p for p in path.rglob("*")
                                if p.is_file() and OUTPUT_DIR not in p.relative_to(path).parts)
        else:
            candidates = [path]
        for candidate in candidates:
            if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def output_path(src: Path) -> Path:
    return src.parent / OUTPUT_DIR / f"{src.stem}.png"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    pause = "--pause" in args
    try:
        return _run([a for a in args if a != "--pause"])
    finally:
        if pause:
            input("\nPress Enter to close...")


def _run(paths: list[str]) -> int:
    images = collect(paths)
    if not images:
        print("No images found.")
        return 1
    try:
        model, warning = resolve_model(load_config())
        if warning:
            print(warning)
        print(f"Loading the model ({model})...")
        matter = Matter(ensure_model(MODELS[model]))
    except (ConfigError, ModelError) as err:
        print(err)
        return 1

    saved = failed = 0
    for n, src in enumerate(images, 1):
        label = f"[{n}/{len(images)}] {src.name}"
        try:
            started = time.perf_counter()
            with Image.open(src) as img:
                image = ImageOps.exif_transpose(img).convert("RGBA")
            target = output_path(src)
            target.parent.mkdir(exist_ok=True)
            cutout(image, matter.matte(image)).save(target, optimize=True)
            print(f"{label} -> {OUTPUT_DIR}\\{target.name} ({time.perf_counter() - started:.1f}s)")
            saved += 1
        except Exception as err:
            print(f"{label} -> FAILED: {user_message(err)}")
            failed += 1
    print(f"\nDone: {saved} saved, {failed} failed.")
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
