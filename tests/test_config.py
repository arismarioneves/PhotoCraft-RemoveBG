import json
import re

import pytest

from removebg.config import Config, ConfigError, ensure_token, load_config, resolve_model, save_config


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.json")
    assert cfg == Config()


def test_round_trip_uses_camel_case_keys(tmp_path):
    p = tmp_path / "config.json"
    save_config(Config(model="rmbg-1.4", rmbg14_license_accepted="2026-10-20", control_port=9000), p)
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "model": "rmbg-1.4", "rmbg14LicenseAccepted": "2026-10-20",
        "photocraftExe": r"C:\Program Files\PhotoCraft\photocraft.exe",
        "controlPort": 9000, "lockPort": 7892}
    assert load_config(p).control_port == 9000


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"model": "isnet", "somethingElse": 1}', encoding="utf-8")
    assert load_config(p) == Config()


def test_invalid_json_raises_config_error_naming_the_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(ConfigError, match="config.json"):
        load_config(p)


def test_rmbg_without_license_falls_back_to_isnet():
    model, warning = resolve_model(Config(model="rmbg-1.4"))
    assert model == "isnet" and "install.ps1 -Model rmbg-1.4" in warning


def test_rmbg_with_license_is_used():
    assert resolve_model(Config(model="rmbg-1.4", rmbg14_license_accepted="2026-10-20")) == ("rmbg-1.4", None)


def test_unknown_model_falls_back_to_isnet():
    model, warning = resolve_model(Config(model="foo"))
    assert model == "isnet" and "foo" in warning


def test_ensure_token_creates_64_hex_once(tmp_path):
    t1 = ensure_token(tmp_path / "control.token")
    assert re.fullmatch(r"[0-9a-f]{64}", t1)
    assert ensure_token(tmp_path / "control.token") == t1


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_ensure_token_works_under_a_folder_with_accents(tmp_path):
    token = ensure_token(tmp_path / "Ação Éé" / "control.token")
    assert re.fullmatch(r"[0-9a-f]{64}", token)
