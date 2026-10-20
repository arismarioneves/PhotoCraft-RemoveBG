import hashlib
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import models_dir


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    url: str
    size: int
    sha256: str
    license: str


MODELS = {
    "isnet": ModelSpec(
        "isnet", "isnet-general-use.onnx",
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        178648008, "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a", "Apache-2.0"),
    "rmbg-1.4": ModelSpec(
        "rmbg-1.4", "bria-rmbg-1.4.onnx",
        "https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx",
        176153355, "8cafcf770b06757c4eaced21b1a88e57fd2b66de01b8045f35f01535ba742e0f",
        "bria-rmbg-1.4 (non-commercial)"),
}


class ModelError(Exception):
    pass


def model_path(spec: ModelSpec) -> Path:
    return models_dir() / spec.filename


def ensure_model(spec: ModelSpec, report: Callable[[str], None] = print) -> Path:
    path = model_path(spec)
    if path.is_file() and path.stat().st_size == spec.size:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    report(f"Downloading the {spec.key} model ({spec.size / 2**20:.0f} MB)...")
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(spec.url, timeout=60) as response, open(partial, "wb") as out:
            next_report = 10
            while chunk := response.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                percent = received * 100 // spec.size if spec.size else 100
                while percent >= next_report and next_report <= 100:
                    report(f"  {next_report}%")
                    next_report += 10
    except OSError as err:
        partial.unlink(missing_ok=True)
        raise ModelError(f"Could not download the {spec.key} model ({err}); "
                         "check your internet connection and try again.") from err
    if received != spec.size or digest.hexdigest() != spec.sha256:
        partial.unlink(missing_ok=True)
        raise ModelError(f"The downloaded {spec.key} model does not match the expected file "
                         f"(sha256 {digest.hexdigest()[:12]}..., {received} bytes); "
                         "check your internet connection and try again.")
    os.replace(partial, path)
    return path


def _cli(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "ensure" and argv[1] in MODELS:
        try:
            ensure_model(MODELS[argv[1]])
        except ModelError as err:
            print(err, file=sys.stderr)
            return 1
        return 0
    print(f"usage: python -m removebg.models ensure {{{','.join(MODELS)}}}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
