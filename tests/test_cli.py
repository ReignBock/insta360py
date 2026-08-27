"""The command line surface."""

# pytest passes fixtures as arguments named after the fixture, which pylint
# reads as shadowing.
# pylint: disable=redefined-outer-name

import argparse
from pathlib import Path

import pytest

from insvtools.cli import build_parser, main, parse_time

COMMANDS = (
    "cut",
    "dump-meta",
    "decompose-meta",
    "compose-meta",
    "remove-meta",
    "extract-meta",
    "replace-meta",
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("10", 10.0), ("10.500", 10.5), ("1:40.124", 100.124), ("0:05", 5.0)],
)
def test_parse_time(text: str, expected: float) -> None:
    """Accepted time spellings."""
    assert parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["abc", "1:2:3", "10s", ""])
def test_parse_time_rejects_garbage(text: str) -> None:
    """Anything not [MM:]SS[.SSS] is refused."""
    with pytest.raises(argparse.ArgumentTypeError):
        parse_time(text)


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_takes_a_file(command: str) -> None:
    """Each subcommand takes the file as a positional."""
    args = build_parser().parse_args([command, "some.insv"])

    assert args.file_name == "some.insv"
    assert args.command == command


def test_unknown_command_is_a_usage_error() -> None:
    """An unknown subcommand exits 2."""
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate", "sample.insv"])

    assert exc.value.code == 2


def test_unknown_option_is_a_usage_error(sample_insv: Path) -> None:
    """An unknown option exits 2."""
    with pytest.raises(SystemExit) as exc:
        main(["dump-meta", "--nonsense=1", str(sample_insv)])

    assert exc.value.code == 2


def test_cut_needs_a_time_bound(sample_insv: Path) -> None:
    """cut without any bound is a usage error."""
    with pytest.raises(SystemExit) as exc:
        main(["cut", str(sample_insv)])

    assert exc.value.code == 2


def test_explicit_zero_start_time_is_accepted(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero is a real bound; only omitting both is an error."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--start-time=0", "sample.insv"]) == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["dump-meta", "--frame-type", "10", "sample.insv"],
        ["dump-meta", "--frame-type=10", "sample.insv"],
        ["dump-meta", "sample.insv", "--frame-type=10"],
    ],
)
def test_option_spellings(
    argv: list[str], sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Options work with =, with a space, and after the file."""
    monkeypatch.chdir(sample_insv.parent)

    assert main(argv) == 0
    assert (sample_insv.parent / "sample.insv.frame10.meta.json").exists()


def test_failure_returns_one_and_reports_on_stderr(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A failed command exits 1 and prints the reason, without a traceback."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["extract-meta", "sample.insv"]) == 0
    assert main(["extract-meta", "sample.insv"]) == 1

    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "Traceback" not in captured.err


def test_no_log_file_is_left_behind(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logging goes to stderr; the Java tool's insvtools.log is not recreated."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["dump-meta", "sample.insv"]) == 0

    assert not (sample_insv.parent / "insvtools.log").exists()
