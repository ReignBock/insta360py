"""Failure modes and the branches only a malformed or unusual input reaches."""

# pylint: disable=redefined-outer-name

import struct
from pathlib import Path

import pytest

from insvtools.cli import main
from insvtools.commands.cut import (
    VideoRange,
    _sample_ranges,
    _update_metadata,
    _snap_to_keyframe,
    cut,
    files_to_process,
    sync_sample_time,
)
from insvtools.commands.meta import compose_meta, decompose_meta, dump_meta, extract_meta
from insvtools.header import HEADER_SIZE, SIGNATURE, InsvHeader
from insvtools.metadata import InsvMetadata, read_metadata, strip_metadata
from insvtools.mp4.reader import Mp4File, Sample, Track


# --- header -----------------------------------------------------------------


def test_a_file_shorter_than_the_footer_has_no_metadata(tmp_path: Path) -> None:
    """Too small to hold a 72-byte footer, so there is nothing to read."""
    path = tmp_path / "tiny.mp4"
    path.write_bytes(b"x" * (HEADER_SIZE - 1))

    with path.open("rb") as f:
        assert InsvHeader.read(f) is None


def test_an_unsupported_version_is_rejected(tmp_path: Path) -> None:
    """Only version 3 is understood; a different one is an error, not a skip."""
    footer = bytes(32) + struct.pack("<ii", 72, 4) + SIGNATURE
    path = tmp_path / "v4.insv"
    path.write_bytes(footer)

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="Unsupported file version 4"):
            InsvHeader.read(f)


def test_reading_metadata_from_a_plain_mp4_is_an_error(tmp_path: Path) -> None:
    """read_metadata demands a trailer; read_metadata_optional does not."""
    path = tmp_path / "plain.mp4"
    path.write_bytes(b"\x00" * 200)

    with pytest.raises(ValueError, match="Metadata not found"):
        read_metadata(path)


def test_stripping_metadata_from_a_plain_mp4_is_an_error(tmp_path: Path) -> None:
    """There is no trailer to remove."""
    path = tmp_path / "plain.mp4"
    path.write_bytes(b"\x00" * 200)

    with pytest.raises(ValueError, match="Metadata not found"):
        strip_metadata(path)


def test_extract_meta_needs_a_trailer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing to extract from a plain MP4."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plain.mp4").write_bytes(b"\x00" * 200)

    with pytest.raises(ValueError, match="Metadata not found"):
        extract_meta("plain.mp4")


# --- meta commands ----------------------------------------------------------


def test_dump_meta_rejects_an_absent_frame_type(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking for a frame the file does not have is an error."""
    monkeypatch.chdir(sample_insv.parent)

    with pytest.raises(ValueError, match="Frame type 23 not found"):
        dump_meta(sample_insv.name, frame_type=23)


def test_compose_meta_needs_frame_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """compose-meta reads what decompose-meta wrote; without it there is nothing."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="Frame files not found"):
        compose_meta("nothing.insv")


def test_compose_meta_rejects_an_unparseable_frame_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frame file naming is the contract that carries type and version."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.insv.frame00.typeNONSENSE.meta").write_bytes(b"abc")

    with pytest.raises(ValueError, match="Wrong frame file name"):
        compose_meta("x.insv")


def test_decompose_then_compose_restores_an_indexed_trailer(
    x5_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The X5 trailer has RAW frames, which sample.insv does not.

    Those are the ones written as ``typeRaw`` and read back with no header.
    """
    monkeypatch.chdir(x5_insv.parent)
    original = read_metadata(x5_insv)
    original.parse()

    decompose_meta(x5_insv.name)

    raw_files = list(x5_insv.parent.glob("*.typeRaw.meta"))
    assert raw_files, "expected RAW frame files"

    compose_meta(x5_insv.name)
    rebuilt = read_metadata(x5_insv)

    assert [f.header.frame_type_code for f in rebuilt.frames] == [
        f.header.frame_type_code for f in original.frames
    ]


# --- cut --------------------------------------------------------------------


def test_cut_reports_a_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing input is reported before any output is created."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="not found"):
        cut("absent.insv", end_time=1.0)


def test_grouping_scans_the_file_s_own_directory(x5_insv: Path) -> None:
    """With no listing passed, siblings come from the file's own directory."""
    sibling = x5_insv.parent / "VID_20260620_173803_10_029.insv"
    sibling.write_bytes(b"")
    (x5_insv.parent / "unrelated.insv").write_bytes(b"")

    targets = files_to_process(x5_insv, None, True)

    assert set(targets) == {x5_insv, sibling}


def _track(durations: list[float], syncs: list[bool]) -> Track:
    samples = [
        Sample(offset=0, size=1, duration=int(d), cts_offset=0, sync=s, chunk=0)
        for d, s in zip(durations, syncs)
    ]
    return Track(
        box=None,  # type: ignore[arg-type]
        handler="vide",
        timescale=1,
        samples=samples,
        constant_sample_size=0,
        chunk_sample_description=[1],
        has_stss=True,
        has_ctts=False,
    )


def test_a_start_past_the_end_of_the_track_is_rejected() -> None:
    """There is no keyframe to snap back to beyond the last sample."""
    track = _track([1, 1, 1], [True, False, False])

    with pytest.raises(ValueError, match="more than track length"):
        sync_sample_time(track, 99.0)


def test_tracks_must_agree_on_the_cut_point() -> None:
    """Two tracks whose keyframes fall in different places cannot be cut together."""
    mp4 = Mp4File(
        boxes=[],
        moov=None,  # type: ignore[arg-type]
        tracks=[
            # The finer-grained track snaps first, to 3; the coarse one can
            # only offer 0, so the two disagree.
            _track([3, 3, 3, 3], [True, True, True, True]),
            _track([10, 10, 10], [True, False, False]),
        ],
        movie_timescale=1,
        limit=0,
    )

    with pytest.raises(ValueError, match="must share the same point of cut"):
        _snap_to_keyframe(mp4, 5.0, None)


def test_an_end_before_the_snapped_start_is_rejected() -> None:
    """Snapping back past the end time leaves nothing to cut."""
    mp4 = Mp4File(
        boxes=[],
        moov=None,  # type: ignore[arg-type]
        tracks=[_track([10, 10, 10], [True, True, True])],
        movie_timescale=1,
        limit=0,
    )

    with pytest.raises(ValueError, match="End time is more than adjusted start time"):
        _snap_to_keyframe(mp4, 25.0, 5.0)


# --- cli --------------------------------------------------------------------


def test_version_falls_back_when_the_package_is_not_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running from a source checkout has no installed distribution metadata."""
    from importlib.metadata import (  # pylint: disable=import-outside-toplevel
        PackageNotFoundError,
    )

    from insvtools import cli  # pylint: disable=import-outside-toplevel

    def boom(_name: str) -> str:
        raise PackageNotFoundError

    # cli imported the function by name, so that is what has to be replaced.
    monkeypatch.setattr(cli, "version", boom)

    assert cli._version() == "unknown"  # pylint: disable=protected-access

    with pytest.raises(SystemExit):
        main(["--version"])
    assert "unknown" in capsys.readouterr().out


def test_tracks_that_agree_on_the_cut_point_are_accepted() -> None:
    """The second track confirming the first is the ordinary case."""
    mp4 = Mp4File(
        boxes=[],
        moov=None,  # type: ignore[arg-type]
        tracks=[
            _track([5, 5, 5, 5], [True, False, True, False]),
            _track([5, 5, 5, 5], [True, False, True, False]),
        ],
        movie_timescale=1,
        limit=0,
    )

    assert _snap_to_keyframe(mp4, 12.0, None) == 10.0


def test_a_track_with_no_samples_has_no_first_sample() -> None:
    """There is nothing to start from, which is an error rather than an empty cut."""
    mp4 = Mp4File(
        boxes=[],
        moov=None,  # type: ignore[arg-type]
        tracks=[_track([], [])],
        movie_timescale=1,
        limit=0,
    )

    with pytest.raises(ValueError, match="Can't find first sample"):
        _sample_ranges(mp4, 0.0, None)


def test_updating_metadata_without_an_info_frame_does_nothing() -> None:
    """Without INFO there is no FileSize or timestamp to patch."""
    metadata = InsvMetadata(InsvHeader.dummy(), [])

    _update_metadata(metadata, 0.0, 100, VideoRange(0, 0, 0.0, 0.0), 1_000_000)

    assert metadata.frames == []
