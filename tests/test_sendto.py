import shutil
from pathlib import Path

import pytest
from PIL import Image

from conftest import FIXTURES
from removebg.sendto import collect, main, output_path


def test_collect_recurses_skips_cutouts_and_dedupes(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/b.PNG").write_bytes(b"")
    (tmp_path / "cutouts").mkdir()
    (tmp_path / "cutouts/a.png").write_bytes(b"")
    (tmp_path / "n.txt").write_bytes(b"")
    assert collect([str(tmp_path), str(tmp_path / "a.jpg")]) == [tmp_path / "a.jpg", tmp_path / "sub/b.PNG"]


def test_file_inside_cutouts_given_directly_is_accepted(tmp_path):
    (tmp_path / "cutouts").mkdir()
    f = tmp_path / "cutouts" / "a.png"
    f.write_bytes(b"")
    assert collect([str(f)]) == [f]


def test_missing_path_is_reported_and_skipped(tmp_path, capsys):
    (tmp_path / "a.jpg").write_bytes(b"")
    assert collect([str(tmp_path / "nope.jpg"), str(tmp_path / "a.jpg")]) == [tmp_path / "a.jpg"]
    assert "nope.jpg" in capsys.readouterr().out


def test_output_path():
    assert output_path(Path(r"C:\x\foto.jpeg")) == Path(r"C:\x\cutouts\foto.png")


def test_nothing_to_do_returns_1(tmp_path):
    (tmp_path / "n.txt").write_bytes(b"")
    assert main([str(tmp_path)]) == 1


@pytest.mark.model
def test_main_writes_transparent_png(tmp_path, shared_models):
    src = tmp_path / "p.jpg"
    shutil.copy(FIXTURES / "portrait-hair.jpg", src)
    assert main([str(src)]) == 0
    out = Image.open(tmp_path / "cutouts" / "p.png")
    assert out.mode == "RGBA" and out.getpixel((out.width - 1, 0))[3] == 0


@pytest.mark.model
def test_broken_image_fails_alone(tmp_path, shared_models, capsys):
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    shutil.copy(FIXTURES / "low-contrast.jpg", tmp_path / "good.jpg")
    assert main([str(tmp_path)]) == 0
    assert (tmp_path / "cutouts" / "good.png").is_file()
    assert "FAILED" in capsys.readouterr().out
