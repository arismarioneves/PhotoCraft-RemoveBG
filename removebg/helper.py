"""Keeps a PhotoCraft open with the control channel and answers the trigger plug-in.

Started by the "PhotoCraft (Remove Background)" shortcut (pythonw, no console). Exits a few
seconds after PhotoCraft closes.
"""
import gc
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from . import photocraft
from .config import (
    Config, ConfigError, config_path, data_dir, ensure_token, exchange_dir, load_config, log_path,
    resolve_model, token_path,
)
from .control import Control, ControlError, port_open
from .matte import Matter
from .models import MODELS, ModelError, ensure_model
from .notify import show_error
from .photocraft import JobError

IDLE_UNLOAD_SECONDS = 600
POLL_SECONDS = 0.5
GONE_AFTER_SECONDS = 10
MEMORY_MESSAGE = "Not enough memory to remove the background. Close other programs and try again."

log = logging.getLogger("removebg.helper")


def user_message(err: BaseException) -> str:
    text = str(err)
    if isinstance(err, MemoryError) or "bad allocation" in text or "Failed to allocate" in text:
        return MEMORY_MESSAGE
    if isinstance(err, (ModelError, JobError)):
        return text
    if isinstance(err, ControlError):
        return f"PhotoCraft refused a step: {text}"
    return f"Remove Background (AI) failed: {type(err).__name__}: {text}. Details: {log_path()}"


def default_matter(model: str) -> Matter:
    return Matter(ensure_model(MODELS[model], report=log.info))


class Helper:
    def __init__(self, cfg: Config, ctl: Control, ops=photocraft,
                 matter_factory: Callable[[str], Matter] = default_matter,
                 notify: Callable[[str], None] = show_error,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.ctl = ctl
        self.ops = ops
        self.matter_factory = matter_factory
        self.notify = notify
        self.clock = clock
        self.handled: dict = {}
        self.seen: dict = {}
        self._matter: Matter | None = None
        self._last_use = clock()
        self._warned = False

    def step(self) -> None:
        for request in self.ops.poll_requests(self.ctl, self.handled, self.seen):
            self._process(request)
        if self._matter is not None and self.clock() - self._last_use > IDLE_UNLOAD_SECONDS:
            log.info("Unloading the model after %d s without requests", IDLE_UNLOAD_SECONDS)
            self._matter = None
            gc.collect()

    def _process(self, request) -> None:
        key = (request.name, request.path)
        exchange = exchange_dir()
        job = None
        try:
            marks = [time.perf_counter()]
            job = self.ops.begin(self.ctl, request)
            marks.append(time.perf_counter())
            exported = self.ops.export_layer(self.ctl, job, exchange)
            marks.append(time.perf_counter())
            with Image.open(exported) as img:
                image = img.convert("RGBA")
            matte = self._get_matter().matte(image)
            mask = Image.new("RGBA", image.size, (255, 255, 255, 0))
            mask.putalpha(matte)
            matte_png = exchange / f"{job.key}-matte.png"
            mask.save(matte_png, compress_level=1)
            marks.append(time.perf_counter())
            self.handled[key] = self.ops.apply_mask(self.ctl, job, matte_png, exchange)
            marks.append(time.perf_counter())
            begin_s, export_s, model_s, apply_s = (b - a for a, b in zip(marks, marks[1:]))
            log.info("Removed the background of %s in %.1f s (start %.1f, export %.1f, model %.1f, mask %.1f)",
                     request.name, marks[-1] - marks[0], begin_s, export_s, model_s, apply_s)
        except OSError:
            raise
        except Exception as err:
            log.exception("Request on %s failed", request.name)
            if job is not None:
                try:
                    self.ops.abort(self.ctl, job)
                except OSError:
                    raise
                except Exception:
                    log.exception("Cleanup after the failure also failed")
            self.notify(user_message(err))
            current = self.ops.revision_of(self.ctl, request)
            self.handled[key] = current if current is not None else request.revision
            if job is not None:
                for leftover in exchange.glob(f"{job.key}-*"):
                    leftover.unlink(missing_ok=True)
        finally:
            self._last_use = self.clock()

    def _get_matter(self) -> Matter:
        if self._matter is None:
            model, warning = resolve_model(self.cfg)
            if warning and not self._warned:
                self._warned = True
                self.notify(warning)
            log.info("Loading the %s model", model)
            self._matter = self.matter_factory(model)
        return self._matter


def main(argv: list[str] | None = None) -> int:
    data_dir().mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_path(), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        return _main()
    except Exception as err:
        log.exception("Helper crashed")
        show_error(user_message(err), wait=True)
        return 1


def _main() -> int:
    try:
        cfg = load_config()
    except ConfigError as err:
        show_error(f"The settings file could not be read: {err}", wait=True)
        return 1

    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", cfg.lock_port))
    except OSError:
        try:
            Control(cfg.control_port, ensure_token()).call("ui.focus")
        except (OSError, ControlError):
            pass
        return 0

    token = ensure_token()
    exchange_dir().mkdir(parents=True, exist_ok=True)
    if not port_open(cfg.control_port):
        if not _launch(cfg):
            return 1
    log.info("Helper started")
    return _serve(cfg, token)


def _launch(cfg: Config) -> bool:
    exe = Path(cfg.photocraft_exe)
    if not exe.is_file():
        show_error(f"PhotoCraft was not found at {exe}. Set photocraftExe in {config_path()}.", wait=True)
        return False
    subprocess.Popen([str(exe), "--control", str(cfg.control_port), "--control-token-file", str(token_path()),
                      "--automation-read-root", str(exchange_dir()),
                      "--automation-write-root", str(exchange_dir())])
    deadline = time.monotonic() + 30
    while not port_open(cfg.control_port):
        if time.monotonic() > deadline:
            show_error("PhotoCraft started but did not open its control channel within 30 seconds.", wait=True)
            return False
        time.sleep(0.2)
    return True


def _serve(cfg: Config, token: str) -> int:
    helper = Helper(cfg, ctl=None)
    shown: set[str] = set()
    lost_since = None
    while True:
        try:
            ctl = Control(cfg.control_port, token)
        except ControlError:
            show_error(f"Port {cfg.control_port} is in use by another program. "
                       f"Change controlPort in {config_path()}.", wait=True)
            return 1
        except OSError:
            lost_since = lost_since or time.monotonic()
            if time.monotonic() - lost_since > GONE_AFTER_SECONDS:
                log.info("PhotoCraft is closed; helper exiting")
                return 0
            time.sleep(1)
            continue
        lost_since = None
        try:
            missing = photocraft.missing_commands(ctl)
            if missing:
                show_error(f"This PhotoCraft version is not supported (missing: {', '.join(missing)}).", wait=True)
                return 1
            photocraft.install_trigger(ctl)
            removed = photocraft.remove_leftover_indicators(ctl)
            if removed:
                log.info("Removed %d leftover indicator layer(s)", removed)
            helper.ctl = ctl
            while True:
                try:
                    helper.step()
                except OSError:
                    raise
                except Exception as err:
                    log.exception("Polling failed")
                    message = user_message(err)
                    if message not in shown:
                        shown.add(message)
                        show_error(message)
                    time.sleep(2)
                time.sleep(POLL_SECONDS)
        except OSError as err:
            log.info("Lost the connection to PhotoCraft: %s", err)
            ctl.close()
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
