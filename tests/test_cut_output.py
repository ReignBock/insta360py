"""End-to-end checks on what cut actually writes.

The bar is higher than "it plays": the trailer must match the Java byte for
byte, and the container must keep the shape the camera wrote.
"""

# pytest passes fixtures as arguments named after the fixture, which pylint
# reads as shadowing.
# pylint: disable=redefined-outer-name

import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import insvtools.commands.cut as cut_module
from insvtools.cli import main
from insvtools.frames.frame_type import FrameType
from insvtools.header import InsvHeader
from insvtools.metadata import InsvMetadata
from insvtools.mp4.reader import Mp4File
from insvtools.mp4.writer import write_clipped

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def _metadata_pos(data: bytes) -> int:
    return len(data) - struct.unpack_from("<i", data, len(data) - 40)[0]


def _top_level_boxes(data: bytes, limit: int) -> list[tuple[str, int]]:
    boxes = []
    offset = 0
    while offset + 8 <= limit:
        (size,) = struct.unpack_from(">I", data, offset)
        boxes.append((data[offset + 4 : offset + 8].decode("latin1"), size))
        offset += size
    return boxes


def test_full_range_rewrite_is_byte_identical(sample_insv: Path, tmp_path: Path) -> None:
    """Rewriting every sample must reproduce the container exactly.

    This is the strongest statement available about the box layer: it proves
    the tables we regenerate are bit-for-bit what the camera wrote, and that
    everything else is passed through untouched.
    """
    out = tmp_path / "full.mp4"

    with sample_insv.open("rb") as f:
        header = InsvHeader.read(f)
        assert header is not None
        mp4 = Mp4File.read(f, header.metadata_pos)
        with out.open("wb") as dest:
            write_clipped(f, mp4, [(0, len(t.samples)) for t in mp4.tracks], dest)

    expected = sample_insv.read_bytes()[: header.metadata_pos]
    assert out.read_bytes() == expected


def test_cut_trailer_matches_java(
    sample_insv: Path, golden: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cut file's trailer must match the reference exactly."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--end-time=1", "sample.insv"]) == 0

    produced = (sample_insv.parent / "sample.cut.insv").read_bytes()
    expected = (golden / "sample.cut.insv").read_bytes()

    assert len(produced) == len(expected)
    assert produced[_metadata_pos(produced):] == expected[_metadata_pos(expected):]


def test_cut_container_differs_from_java_only_in_timestamps(
    sample_insv: Path, golden: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mp4parser rewrites creation/modification times; we preserve them.

    Four boxes carry them - mvhd and one tkhd per track - at 8 bytes each.
    Preserving the camera's values is a deliberate improvement on the
    reference, so the difference is pinned here rather than treated as drift.
    """
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--end-time=1", "sample.insv"]) == 0

    produced = (sample_insv.parent / "sample.cut.insv").read_bytes()
    expected = (golden / "sample.cut.insv").read_bytes()

    differing = [i for i in range(len(produced)) if produced[i] != expected[i]]
    assert len(differing) == 32

    # And ours is the one that matches the camera.
    source = sample_insv.read_bytes()
    assert produced[: _metadata_pos(produced)] == source[: _metadata_pos(source)]


def test_cut_clips_at_the_preceding_keyframe(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sample.insv's video has sync samples at 0.0000 and 0.5005."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--start-time=0.9", "sample.insv"]) == 0

    cut = sample_insv.parent / "sample.cut.insv"

    with cut.open("rb") as f:
        header = InsvHeader.read(f)
        assert header is not None
        mp4 = Mp4File.read(f, header.metadata_pos)

    video = next(t for t in mp4.tracks if t.handler == "vide")
    assert len(video.samples) == 15
    assert video.samples[0].sync

    # Layout stays what the camera writes: no added boxes, moov before mdat.
    data = cut.read_bytes()
    assert [name for name, _ in _top_level_boxes(data, header.metadata_pos)] == [
        "ftyp",
        "moov",
        "mdat",
    ]


def test_cut_slices_timelapse_records(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timelapse records follow the video sample range."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--start-time=0.9", "sample.insv"]) == 0

    with (sample_insv.parent / "sample.cut.insv").open("rb") as f:
        metadata = InsvMetadata.read(f)
        assert metadata is not None
        metadata.parse()

    timelapse = metadata.find_frame(FrameType.TIMELAPSE)
    info = metadata.find_frame(FrameType.INFO)

    # One record per remaining video sample.
    assert len(timelapse.records) == 15
    # Truncation matches upstream's (long)(time * scale), floats and all.
    assert info.extra_metadata.FirstFrameTimestamp == 309468418 + 500499
    assert info.extra_metadata.FileSize == _metadata_pos(
        (sample_insv.parent / "sample.cut.insv").read_bytes()
    )


def test_text_track_survives_unchanged(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The QuickTime `text` track keeps its sample entry and sample count."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--end-time=1", "sample.insv"]) == 0

    with (sample_insv.parent / "sample.cut.insv").open("rb") as f:
        header = InsvHeader.read(f)
        mp4 = Mp4File.read(f, header.metadata_pos)
        text = next(t for t in mp4.tracks if t.handler == "text")
        stsd = text.box.find(b"mdia", b"minf", b"stbl", b"stsd")
        entry_type = stsd.payload(f)[12:16]

    assert len(text.samples) == 11
    assert entry_type == b"text"


@requires_ffmpeg
def test_cut_output_decodes_cleanly(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg must decode the result without complaint."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--start-time=0.9", "sample.insv"]) == 0

    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "sample.cut.insv", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_cut_refuses_to_overwrite(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing output file is never clobbered."""
    monkeypatch.chdir(sample_insv.parent)
    assert main(["cut", "--end-time=1", "sample.insv"]) == 0
    assert main(["cut", "--end-time=1", "sample.insv"]) != 0


def test_partial_output_is_removed_on_failure(
    sample_insv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure mid-write must not leave a truncated file behind."""
    monkeypatch.chdir(sample_insv.parent)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(cut_module, "write_clipped", boom)

    assert main(["cut", "--end-time=1", "sample.insv"]) != 0
    assert not (sample_insv.parent / "sample.cut.insv").exists()
