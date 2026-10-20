import datetime
import json
import logging
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path

APP_NAME = "PhotoCraft-RemoveBG"
MODEL_KEYS = ("isnet", "rmbg-1.4")

log = logging.getLogger(__name__)


def data_dir() -> Path:
    custom = os.environ.get("PHOTOCRAFT_REMOVEBG_HOME")
    if custom:
        return Path(custom)
    return Path(os.environ["LOCALAPPDATA"]) / APP_NAME


def models_dir() -> Path:
    custom = os.environ.get("PHOTOCRAFT_REMOVEBG_MODELS")
    return Path(custom) if custom else data_dir() / "models"


def exchange_dir() -> Path:
    return data_dir() / "exchange"


def token_path() -> Path:
    return data_dir() / "control.token"


def log_path() -> Path:
    return data_dir() / "helper.log"


def config_path() -> Path:
    return data_dir() / "config.json"


@dataclass
class Config:
    model: str = "isnet"
    rmbg14_license_accepted: str | None = None
    photocraft_exe: str = r"C:\Program Files\PhotoCraft\photocraft.exe"
    control_port: int = 7891
    lock_port: int = 7892


class ConfigError(Exception):
    pass


_JSON_KEYS = {
    "model": "model",
    "rmbg14_license_accepted": "rmbg14LicenseAccepted",
    "photocraft_exe": "photocraftExe",
    "control_port": "controlPort",
    "lock_port": "lockPort",
}


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.is_file():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ConfigError(f"{path}: {err}") from err
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a JSON object")
    values = {f.name: raw[_JSON_KEYS[f.name]] for f in fields(Config) if _JSON_KEYS[f.name] in raw}
    return Config(**values)


def save_config(cfg: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {_JSON_KEYS[f.name]: getattr(cfg, f.name) for f in fields(Config)}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_model(cfg: Config) -> tuple[str, str | None]:
    if cfg.model == "rmbg-1.4":
        if cfg.rmbg14_license_accepted:
            return "rmbg-1.4", None
        return "isnet", ("The RMBG-1.4 model is for non-commercial use only and its license has not "
                         "been accepted. To use it, run: install.ps1 -Model rmbg-1.4. Using ISNet for now.")
    if cfg.model not in MODEL_KEYS:
        return "isnet", f'Unknown model "{cfg.model}" in {config_path()}. Using ISNet.'
    return cfg.model, None


def ensure_token(path: Path | None = None) -> str:
    path = path or token_path()
    if path.is_file():
        return path.read_text(encoding="ascii").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    path.write_text(token, encoding="ascii")
    user = os.environ.get("USERNAME")
    if user:
        # icacls writes in the console code page; decode loosely, it is only logged.
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                                capture_output=True)
        if result.returncode != 0:
            log.warning("icacls failed on %s: %s", path,
                        (result.stdout + result.stderr).decode("oem", errors="replace"))
    return token


def _cli(argv: list[str]) -> int:
    if argv[:1] == ["ensure-token"]:
        ensure_token()
        return 0
    if argv[:1] == ["set-model"] and len(argv) >= 2 and argv[1] in MODEL_KEYS:
        cfg = load_config()
        cfg.model = argv[1]
        if "--accept-license" in argv[2:]:
            cfg.rmbg14_license_accepted = datetime.date.today().isoformat()
        save_config(cfg)
        return 0
    print("usage: python -m removebg.config ensure-token | set-model {isnet,rmbg-1.4} [--accept-license]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
