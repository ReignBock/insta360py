"""Compare every metadata command against the Java reference output.

The golden files come from tools/refgen.sh, which builds the upstream jar in
Docker and runs it on the same sample. Byte equality is the bar: these
commands exist to move camera metadata around without perturbing it.
"""

from pathlib import Path

import pytest

from insvtools.cli import run


@pytest.fixture
def workdir(sample_insv: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(sample_insv.parent)
    return sample_insv.parent


def test_dump_meta_matches_java(workdir: Path, golden: Path) -> None:
    assert run("dump-meta", "sample.insv") == 0

    produced = (workdir / "sample.insv.meta.json").read_bytes()
    assert produced == (golden / "sample.insv.meta.json").read_bytes()


def test_extract_meta_matches_java(workdir: Path, golden: Path) -> None:
    assert run("extract-meta", "sample.insv") == 0

    produced = (workdir / "sample.insv.meta").read_bytes()
    assert produced == (golden / "sample.insv.meta").read_bytes()


def test_decompose_meta_matches_java(workdir: Path, golden: Path) -> None:
    assert run("decompose-meta", "sample.insv") == 0

    expected = sorted(p.name for p in golden.glob("sample.insv.frame*.meta"))
    produced = sorted(p.name for p in workdir.glob("sample.insv.frame*.meta"))
    assert produced == expected

    for name in expected:
        assert (workdir / name).read_bytes() == (golden / name).read_bytes(), name


def test_decompose_meta_single_frame_type(workdir: Path, golden: Path) -> None:
    assert run("decompose-meta", "--frame-type=10", "sample.insv") == 0

    produced = sorted(p.name for p in workdir.glob("sample.insv.frame*.meta"))
    assert produced == ["sample.insv.frame02.type10.meta"]
    assert (workdir / produced[0]).read_bytes() == (
        golden / "sample.insv.frame02.type10.meta"
    ).read_bytes()


def test_decompose_then_compose_restores_the_file(workdir: Path) -> None:
    original = (workdir / "sample.insv").read_bytes()

    assert run("decompose-meta", "sample.insv") == 0
    assert run("remove-meta", "sample.insv") == 0
    assert (workdir / "sample.insv").stat().st_size < len(original)

    assert run("compose-meta", "sample.insv") == 0
    assert (workdir / "sample.insv").read_bytes() == original


def test_extract_then_replace_restores_the_file(workdir: Path) -> None:
    original = (workdir / "sample.insv").read_bytes()

    assert run("extract-meta", "sample.insv") == 0
    assert run("remove-meta", "sample.insv") == 0
    assert run("replace-meta", "sample.insv") == 0

    assert (workdir / "sample.insv").read_bytes() == original


def test_remove_meta_leaves_a_plain_mp4(workdir: Path) -> None:
    assert run("remove-meta", "sample.insv") == 0

    data = (workdir / "sample.insv").read_bytes()
    assert not data.endswith(b"8db42d694ccc418790edff439fe026bf")
    # Removing it twice is an error, not a silent no-op.
    assert run("remove-meta", "sample.insv") != 0
