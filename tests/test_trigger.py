import base64
import json
import subprocess

import pytest
from PIL import Image, ImageChops

from conftest import FIXTURES
from removebg.trigger import MENU_NAME, PLUGIN_ID, build_trigger


def test_module_header_and_manifest():
    wasm = build_trigger("1.2.3")
    assert wasm[:8] == b"\x00asm\x01\x00\x00\x00"
    manifest = json.loads(wasm[wasm.index(b'{"id"'):wasm.rindex(b"}") + 1])
    assert manifest["id"] == "photocraft-removebg" and manifest["name"] == "Remove Background (AI)"
    assert manifest["version"] == "1.2.3" and manifest["kind"] == "filter"
    assert len(wasm) < 2048


def _run(cli, args):
    out = subprocess.run([str(cli), "run", *args], capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines()]


@pytest.mark.photocraft
def test_trigger_installs_and_changes_no_pixels(photocraft_cli, tmp_path):
    photo = str(FIXTURES / "portrait-hair.jpg")
    data = base64.b64encode(build_trigger()).decode()
    with_trigger = _run(photocraft_cli, [
        photo, "--cmd", "plugin.install", "--params", json.dumps({"data": data}),
        "--cmd", "plugin.run", "--params", json.dumps({"id": PLUGIN_ID}),
        "--cmd", "document.inspect", "--out", str(tmp_path / "a.png")])
    _run(photocraft_cli, [photo, "--cmd", "document.inspect", "--out", str(tmp_path / "b.png")])
    history = with_trigger[-1]["result"]["history"]
    assert history[-1] == MENU_NAME
    assert ImageChops.difference(Image.open(tmp_path / "a.png"), Image.open(tmp_path / "b.png")).getbbox() is None
