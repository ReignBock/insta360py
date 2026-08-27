"""The marker extractor's command line surface."""

# pylint: disable=redefined-outer-name

import json
from pathlib import Path

import pytest

from insvmarkers.cli import build_parser, main

MARKER_LINES = ["Marker 01 : 00:04:52", "Marker 02 : 00:18:13", "Marker 03 : 00:29:16"]


def _studio_project(root: Path, session: str) -> Path:
    """A Studio project directory holding one project for ``session``."""
    directory = root / "FootageProject" / "clip1"
    directory.mkdir(parents=True)
    path = directory / "footage_project.insprj"
    path.write_text(
        json.dumps(
            {"projects": [{"clip": {"fps": 30.0, "path": f"VID_{session}_00_029.insv"}}]}
        )
    )
    return path


def test_markers_are_listed_for_each_session(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline output: one line per marker, in timeline order."""
    assert main([str(session_dir), "--no-inject"]) == 0

    out = capsys.readouterr().out
    assert "Sequence: VID_20260620_173803 (2 files)" in out
    for line in MARKER_LINES:
        assert line in out


def test_a_file_can_be_named_directly(
    x5_insv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dropping one chapter still reports the whole session it belongs to."""
    assert main([str(x5_insv), "--no-inject"]) == 0

    assert MARKER_LINES[0] in capsys.readouterr().out


def test_nothing_to_do_is_reported_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty directory is a mistake worth a non-zero exit."""
    assert main([str(tmp_path)]) == 1

    assert "No .insv or .lrv files found." in capsys.readouterr().err


def test_a_session_without_markers_is_summarised(
    unmarked_session: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Listing nothing per file would drown the sessions that do have markers."""
    assert main([str(unmarked_session), "--no-inject"]) == 0

    out = capsys.readouterr().out
    assert "No markers found in 1 sequence(s)." in out
    assert "Marker" not in out


def test_a_file_whose_session_has_vanished_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The name carries a session id but nothing in the directory matches it."""
    odd = tmp_path / "GPS_20260620_173803_00_029.insv"
    odd.write_bytes(b"\x00" * 200)

    assert main([str(odd), "--no-inject"]) == 0
    assert "Marker" not in capsys.readouterr().out


def test_an_unreadable_first_file_reports_the_session_and_carries_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One broken session must not abandon the others."""
    broken = tmp_path / "VID_20260620_173803_00_029.insv"
    broken.write_bytes(b"\x00" * 200)

    assert main([str(broken), "--no-inject"]) == 0

    captured = capsys.readouterr()
    assert "Sequence: VID_20260620_173803" in captured.out
    assert "Base timestamp extraction failed" in captured.err


def test_markers_are_injected_into_the_studio_project(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of the tool: markers become editable keyframes."""
    projects = tmp_path / "studio"
    project = _studio_project(projects, "20260620_173803")

    assert main([str(session_dir), "--projects-dir", str(projects)]) == 0

    assert "Injected 3 keyframe(s)" in capsys.readouterr().out

    clip = json.loads(project.read_text())["projects"][0]["clip"]
    keyframes = [n for n in clip["key_frame_track"]["node_list"] if n["node_type"] == 0]
    assert clip["enable_user_keyframe"] is True
    assert [n["time"] for n in keyframes] == [8778, 32813, 52691]
    assert project.with_suffix(".insprj.bak").exists()


def test_a_missing_studio_project_is_reported_not_fatal(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Markers are still listed when Studio has never opened the clip."""
    assert main([str(session_dir), "--projects-dir", str(tmp_path / "absent")]) == 0

    out = capsys.readouterr().out
    assert "Studio Project:" in out
    assert MARKER_LINES[0] in out


def test_an_unwritable_project_is_reported_not_fatal(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project Studio still has open, or a read-only disk."""
    projects = tmp_path / "studio"
    _studio_project(projects, "20260620_173803")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("in use by another process")

    monkeypatch.setattr("insvmarkers.cli.inject_keyframes", refuse)

    assert main([str(session_dir), "--projects-dir", str(projects)]) == 0
    assert "could not be updated" in capsys.readouterr().out


def test_verbosity_flags_are_mutually_exclusive() -> None:
    """-v and -q together is a usage error, not a silent precedence rule."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["x", "-v", "-q"])


@pytest.mark.parametrize("flag", ["-v", "-q"])
def test_verbosity_flags_are_accepted(
    flag: str, session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logging level is the only thing they change."""
    assert main([str(session_dir), "--no-inject", flag]) == 0

    assert MARKER_LINES[0] in capsys.readouterr().out


def test_markers_can_be_written_to_a_text_file(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The file carries the raw seconds too, since HH:MM:SS truncates."""
    out = tmp_path / "markers.txt"

    assert main([str(session_dir), "--no-inject", "-o", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    assert "Sequence: VID_20260620_173803 (2 files)" in text
    assert "Marker 01 : 00:04:52       292.60s" in text
    assert "Marker 03 : 00:29:16      1756.38s" in text
    assert f"Wrote markers to {out}" in capsys.readouterr().out


def test_every_session_lands_in_one_file(
    session_dir: Path, unmarked_session: Path, tmp_path: Path
) -> None:
    """Sessions accumulate, and one without markers contributes nothing."""
    out = tmp_path / "markers.txt"

    assert main([str(session_dir), str(unmarked_session), "--no-inject", "-o", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    assert text.count("Sequence:") == 1
    assert "20221218_231825" not in text


def test_a_file_that_cannot_be_written_is_reported_not_fatal(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The markers were still printed, so this is a warning, not a failure."""
    unwritable = tmp_path / "no-such-dir" / "markers.txt"

    assert main([str(session_dir), "--no-inject", "-o", str(unwritable)]) == 0

    captured = capsys.readouterr()
    assert "Could not write" in captured.err
    assert MARKER_LINES[0] in captured.out
