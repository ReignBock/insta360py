"""The X5 file shape: indexed frames, an inst box, markers, unknown types.

sample.insv is a ONE R and covers none of this. See tools/mkfixture.py for how
this fixture was derived from a real recording.
"""

# pylint: disable=redefined-outer-name

import io
import struct
from pathlib import Path

import pytest

from insvtools.cli import main
from insvtools.frames.anchors_frame import marker_seconds, parse_anchors
from insvtools.frames.frame_type import FrameType
from insvtools.frames.gyro_frame import GyroFrame
from insvtools.frames.index_frame import INDEX_ENTRY_SIZE, IndexFrame
from insvtools.frames.info_frame import InfoFrame
from insvtools.header import INST_BOX_TYPE, InsvHeader
from insvtools.metadata import InsvMetadata, read_metadata, write_trailer


def _trailer_bytes(path: Path) -> bytes:
    """Everything from the inst box header to end of file."""
    with path.open("rb") as f:
        header = InsvHeader.read(f)
        assert header is not None
        f.seek(header.container_end)
        return f.read()


def test_inst_box_wraps_the_trailer(x5_insv: Path) -> None:
    """The trailer is a real MP4 box, so the file parses as MP4 to the end."""
    with x5_insv.open("rb") as f:
        header = InsvHeader.read(f)
        assert header is not None
        assert header.boxed
        assert header.container_end == header.metadata_pos - 8

        f.seek(header.container_end)
        size, box_type = struct.unpack(">I4s", f.read(8))

    assert box_type == INST_BOX_TYPE
    # The box covers its own header plus the whole trailer.
    assert size == header.metadata_size + 8


def test_plain_trailer_is_not_boxed(sample_insv: Path) -> None:
    """A ONE R writes the trailer bare; the eight bytes before it are padding."""
    with sample_insv.open("rb") as f:
        header = InsvHeader.read(f)

    assert header is not None
    assert not header.boxed
    assert header.container_end == header.metadata_pos


def test_roundtrip_is_byte_identical(x5_insv: Path) -> None:
    """The indexed layout and its inst box survive a read/write cycle."""
    metadata = read_metadata(x5_insv)
    metadata.parse()

    buf = io.BytesIO()
    write_trailer(buf, metadata, boxed=True)

    assert buf.getvalue() == _trailer_bytes(x5_insv)


def test_index_frame_indexes_the_other_frames(x5_insv: Path) -> None:
    """Every indexed entry points at the frame it claims to."""
    with x5_insv.open("rb") as f:
        header = InsvHeader.read(f)
        assert header is not None
        metadata = InsvMetadata.read(f)

    assert metadata is not None
    metadata.parse()
    index = metadata.find_frame_of(IndexFrame)
    assert index is not None

    by_type = {
        frame.header.frame_type_code: frame.header
        for frame in metadata.frames
        if frame.header.frame_type is not FrameType.RAW
    }

    for entry in index.frames_index:
        if entry is None:
            continue
        actual = by_type[entry.frame_type_code]
        assert entry.frame_size == actual.frame_size
        assert entry.frame_pos == actual.frame_pos


def test_index_keeps_its_slot_count(x5_insv: Path) -> None:
    """Rebuilding must not shrink an index that is longer than our frame types.

    The camera sizes the index by its own highest type, which is beyond both
    the types we know and the types present in the file.
    """
    original = read_metadata(x5_insv)
    original.parse()
    index = original.find_frame_of(IndexFrame)
    assert index is not None

    slots = len(index.frames_index)
    highest_present = max(f.header.frame_type_code for f in original.frames)
    assert slots > highest_present + 1

    buf = io.BytesIO()
    write_trailer(buf, original, boxed=True)
    written = buf.getvalue()

    # Locate the rebuilt index frame and check it kept its length.
    rebuilt = read_metadata(x5_insv)
    rebuilt.parse()
    rebuilt_index = rebuilt.find_frame_of(IndexFrame)
    assert rebuilt_index is not None
    assert len(rebuilt_index.frames_index) == slots
    assert written == _trailer_bytes(x5_insv)


def test_unknown_frame_types_stay_opaque(x5_insv: Path) -> None:
    """Types past the documented 24 are carried through untouched."""
    metadata = read_metadata(x5_insv)
    metadata.parse()

    unknown = [f for f in metadata.frames if f.header.frame_type is None]
    codes = sorted(f.header.frame_type_code for f in unknown)

    assert codes == [27, 28, 29]
    assert all(not f.parsed for f in unknown)
    assert all(type(f).__name__ == "Frame" for f in unknown)


def test_gyro_stays_opaque_when_the_sample_is_empty(x5_insv: Path) -> None:
    """The X5 leaves ExtraMetadata.Gyro empty, so the record size is unknown."""
    metadata = read_metadata(x5_insv)
    metadata.parse()

    info = metadata.find_frame_of(InfoFrame)
    gyro = metadata.find_frame_of(GyroFrame)

    assert info is not None and info.extra_metadata is not None
    assert len(info.extra_metadata.Gyro) == 0
    assert gyro is not None
    assert not gyro.parsed
    assert gyro.records == []


def test_markers_are_64_bit(x5_insv: Path) -> None:
    """Marker timestamps outgrow 32 bits on a long recording.

    The PowerShell reads them as uint32; every marker here would be wrong
    under that reading, and none of them land inside the clip.
    """
    metadata = read_metadata(x5_insv)
    metadata.parse()

    info = metadata.find_frame_of(InfoFrame)
    anchors = metadata.find_frame(FrameType.ANCHORS)
    assert info is not None and info.extra_metadata is not None
    assert anchors is not None

    sections = parse_anchors(anchors.payload)
    section = next(s for s in sections if s.kind == 1)

    assert [s.kind for s in sections] == [1, 2, 3, 4, 0x10, 0x11, 0x12]
    assert len(section.timestamps) == 3
    assert all(t > 0xFFFFFFFF for t in section.timestamps)

    seconds = marker_seconds(anchors.payload, info.extra_metadata.FirstFrameTimestamp)
    assert seconds == pytest.approx([292.597074, 1093.755729, 1756.382436])


def test_cut_preserves_the_inst_box(x5_insv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cut X5 file is still wrapped, and FileSize still points at the trailer."""
    monkeypatch.chdir(x5_insv.parent)
    assert main(["cut", "--end-time=0.1", "--no-group", x5_insv.name]) == 0

    out = x5_insv.parent / "VID_20260620_173803_00_029.cut.insv"
    with out.open("rb") as f:
        header = InsvHeader.read(f)

    assert header is not None
    assert header.boxed

    metadata = read_metadata(out)
    metadata.parse()
    info = metadata.find_frame_of(InfoFrame)
    assert info is not None and info.extra_metadata is not None

    # FileSize counts up to the trailer proper, past the inst box header.
    assert info.extra_metadata.FileSize == header.metadata_pos
    assert out.stat().st_size == header.metadata_pos + header.metadata_size


def test_cut_output_decodes_cleanly(x5_insv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ffmpeg reads the cut container without complaint."""
    ffmpeg = pytest.importorskip("shutil").which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")

    monkeypatch.chdir(x5_insv.parent)
    assert main(["cut", "--end-time=0.1", "--no-group", x5_insv.name]) == 0

    import subprocess  # pylint: disable=import-outside-toplevel

    out = x5_insv.parent / "VID_20260620_173803_00_029.cut.insv"
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(out), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_index_entry_size_matches_the_frame(x5_insv: Path) -> None:
    """The INDEX payload is a whole number of fixed-size entries."""
    metadata = read_metadata(x5_insv)
    metadata.parse()
    index = metadata.find_frame_of(IndexFrame)

    assert index is not None
    assert len(index.payload) % INDEX_ENTRY_SIZE == 0
    assert len(index.payload) // INDEX_ENTRY_SIZE == len(index.frames_index)
