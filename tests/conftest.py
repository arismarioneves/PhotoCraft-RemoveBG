import os
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from removebg.config import ensure_token
from removebg.control import Control, ControlError, port_open
from removebg.photocraft import install_trigger

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOCRAFT_REMOVEBG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PHOTOCRAFT_REMOVEBG_MODELS", str(tmp_path / "models"))


@pytest.fixture
def shared_models(monkeypatch):
    cache = REPO / ".cache" / "models"
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PHOTOCRAFT_REMOVEBG_MODELS", str(cache))
    return cache


@pytest.fixture
def photocraft_cli():
    cli = os.environ.get("PHOTOCRAFT_CLI")
    if not cli or not Path(cli).is_file():
        pytest.skip("set PHOTOCRAFT_CLI to photocraft-cli.exe")
    return Path(cli)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def exchange(tmp_path_factory):
    return tmp_path_factory.mktemp("exchange")


@pytest.fixture(scope="session")
def app(exchange, tmp_path_factory):
    exe = os.environ.get("PHOTOCRAFT_EXE")
    if not exe or not Path(exe).is_file():
        pytest.skip("set PHOTOCRAFT_EXE to photocraft.exe")
    port = _free_port()
    token_file = tmp_path_factory.mktemp("control") / "control.token"
    token = ensure_token(token_file)
    proc = subprocess.Popen([exe, "--control", str(port), "--control-token-file", str(token_file),
                             "--automation-read-root", str(exchange), "--automation-write-root", str(exchange)])
    deadline = time.monotonic() + 30
    while not port_open(port):
        if time.monotonic() > deadline:
            proc.kill()
            pytest.fail("PhotoCraft did not open its control port in 30 s")
        time.sleep(0.2)
    ctl = Control(port, token)
    install_trigger(ctl)
    yield ctl
    try:
        ctl.call("app.quit")
    except (OSError, ControlError):
        pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


@dataclass
class Photo:
    name: str
    path: str
    w: int
    h: int


def _open_photo(app, exchange, fixture_name):
    name = f"{Path(fixture_name).stem}-{uuid.uuid4().hex[:8]}.jpg"
    shutil.copy(FIXTURES / fixture_name, exchange / name)
    opened = app.call("app.open", {"path": name})
    doc = app.run("document.inspect")
    return Photo(opened["name"], opened["path"], doc["width"], doc["height"])


def _close_photo(app, photo):
    for d in app.call("ui.inspect")["session"]["documents"]:
        if (d["name"], d.get("path")) == (photo.name, photo.path):
            app.run("file.close", {"document": d["index"]})
            return


@pytest.fixture
def photo(app, exchange):
    p = _open_photo(app, exchange, "portrait-hair.jpg")
    yield p
    _close_photo(app, p)


@pytest.fixture
def other_photo(app, exchange):
    p = _open_photo(app, exchange, "animal-fur.jpg")
    yield p
    _close_photo(app, p)
