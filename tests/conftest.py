from pathlib import Path

import pytest

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
