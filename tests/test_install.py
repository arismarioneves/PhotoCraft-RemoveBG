import json
import re
import shutil
import subprocess

import pytest

from conftest import REPO

PACKAGE_FILES = ["install.ps1", "uninstall.ps1", "INSTALL.bat", "UNINSTALL.bat", "requirements.txt"]


def copy_repo_to(target):
    target.mkdir(parents=True)
    for name in PACKAGE_FILES:
        shutil.copy(REPO / name, target / name)
    shutil.copytree(REPO / "removebg", target / "removebg", ignore=shutil.ignore_patterns("__pycache__"))


def ps(script, *args, stdin=""):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                           *[str(a) for a in args]],
                          input=stdin, capture_output=True, text=True, encoding="oem", errors="replace",
                          timeout=1200)


@pytest.mark.slow
def test_install_from_awkward_folder_and_uninstall(tmp_path):
    pkg = tmp_path / "Área de Trabalho" / "pasta [x] & 100%" / "PhotoCraft-RemoveBG"
    copy_repo_to(pkg)
    data = tmp_path / "dados [y]"
    r = ps(pkg / "install.ps1", "-DataDir", data, "-NoShortcuts", "-NoModel")
    assert r.returncode == 0, r.stdout + r.stderr
    py = data / "venv" / "Scripts" / "python.exe"
    assert subprocess.run([str(py), "-c", "import onnxruntime, numpy, PIL"]).returncode == 0
    assert (sorted(p.name for p in (data / "app" / "removebg").glob("*.py"))
            == sorted(p.name for p in (REPO / "removebg").glob("*.py")))
    assert re.fullmatch(r"[0-9a-f]{64}", (data / "control.token").read_text())
    r = ps(pkg / "uninstall.ps1", "-DataDir", data)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not data.exists()


@pytest.mark.slow
def test_rmbg_without_acceptance_is_refused(tmp_path):
    data = tmp_path / "d"
    r = ps(REPO / "install.ps1", "-DataDir", data, "-NoShortcuts", "-NoModel", "-Model", "rmbg-1.4", stdin="no\n")
    assert r.returncode != 0 and "not accepted" in r.stdout
    config = data / "config.json"
    assert not config.exists() or json.loads(config.read_text()).get("model", "isnet") == "isnet"
    assert not (data / "venv").exists()


@pytest.mark.slow
def test_custom_data_dir_with_shortcuts_is_refused(tmp_path):
    r = ps(REPO / "install.ps1", "-DataDir", tmp_path / "d", "-NoModel")
    assert r.returncode != 0 and "-NoShortcuts" in r.stdout + r.stderr
    assert not (tmp_path / "d").exists()
