"""The argument contract, which is upstream's rather than argparse's."""

from pathlib import Path

import pytest

from insvtools.cli import parse_time, run


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10", 10.0),
        ("10.500", 10.5),
        ("1:40.124", 100.124),
        ("0:05", 5.0),
        (None, 0.0),
    ],
)
def test_parse_time(text: str | None, expected: float) -> None:
    assert parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["abc", "1:2:3", "10s", ""])
def test_parse_time_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_time(text)


def test_usage_when_too_few_arguments(capsys: pytest.CaptureFixture) -> None:
    assert run() == 0
    assert run("dump-meta") == 0
    assert "Toolkit for working with Insta360" in capsys.readouterr().out


def test_unknown_command_fails(sample_insv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_insv.parent)
    assert run("frobnicate", "sample.insv") != 0


def test_unknown_parameter_fails(sample_insv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_insv.parent)
    assert run("dump-meta", "--nonsense=1", "sample.insv") != 0
    assert not (sample_insv.parent / "sample.insv.meta.json").exists()


def test_space_separated_values_are_rejected(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only --key=value is accepted; a bare token is an error."""
    monkeypatch.chdir(sample_insv.parent)
    assert run("dump-meta", "--frame-type", "10", "sample.insv") != 0


def test_cut_requires_a_time_bound(sample_insv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_insv.parent)
    assert run("cut", "sample.insv") != 0


def test_refuses_to_overwrite_existing_output(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_insv.parent)
    assert run("extract-meta", "sample.insv") == 0
    assert run("extract-meta", "sample.insv") != 0
