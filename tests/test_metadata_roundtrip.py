"""Reading a trailer and writing it straight back must be byte-exact.

This is the load-bearing test for the whole metadata layer: it exercises the
backwards frame walk, RAW gap preservation, and the index-frame path in one
shot. If it passes, unknown frames survive a round trip untouched.
"""

from pathlib import Path

from insvtools.frames.frame_type import FrameType
from insvtools.header import HEADER_SIZE, InsvHeader
from insvtools.metadata import InsvMetadata


def test_roundtrip_is_byte_identical(sample_insv: Path, tmp_path: Path) -> None:
    out = tmp_path / "roundtrip.insv"

    with sample_insv.open("rb") as f:
        metadata = InsvMetadata.read(f)
        assert metadata is not None
        f.seek(0)
        container = f.read(metadata.header.metadata_pos)

    with out.open("wb") as f:
        f.write(container)
        metadata.write(f)

    assert out.read_bytes() == sample_insv.read_bytes()


def test_roundtrip_after_parse_drops_only_the_partial_gyro_record(
    sample_insv: Path, tmp_path: Path
) -> None:
    """Parsing then writing is byte-exact except for one documented quirk.

    sample.insv's GYRO payload is 23561 bytes with a 20-byte record size, so
    the last byte is a partial record. Re-serializing writes whole records
    only and drops it - upstream does exactly the same (its cut output has a
    23560-byte GYRO frame), so this is parity, not a bug.
    """
    out = tmp_path / "roundtrip.insv"

    with sample_insv.open("rb") as f:
        metadata = InsvMetadata.read(f)
        assert metadata is not None
        metadata.parse()
        f.seek(0)
        container = f.read(metadata.header.metadata_pos)

    with out.open("wb") as f:
        f.write(container)
        metadata.write(f)

    original = sample_insv.read_bytes()
    written = out.read_bytes()

    assert len(written) == len(original) - 1

    with out.open("rb") as f:
        rewritten = InsvMetadata.read(f)

    assert rewritten is not None
    sizes = {fr.header.frame_type_code: fr.header.frame_size for fr in rewritten.frames}
    assert sizes[FrameType.GYRO] == 23561 - 1
    # Every other frame is untouched.
    with sample_insv.open("rb") as f:
        before = InsvMetadata.read(f)
    assert before is not None
    for old, new_frame in zip(before.frames, rewritten.frames):
        if old.header.frame_type is FrameType.GYRO:
            continue
        assert old.payload == new_frame.payload, old.header


def test_header_fields(sample_insv: Path) -> None:
    with sample_insv.open("rb") as f:
        header = InsvHeader.read(f)

    assert header is not None
    assert header.version == 3
    assert header.metadata_size == 28384
    assert header.metadata_pos == sample_insv.stat().st_size - 28384


def test_no_signature_is_not_an_error(tmp_path: Path) -> None:
    """A plain MP4 has no trailer; that must read as None, not raise."""
    plain = tmp_path / "plain.mp4"
    plain.write_bytes(b"\x00" * (HEADER_SIZE * 2))

    with plain.open("rb") as f:
        assert InsvHeader.read(f) is None
        assert InsvMetadata.read(f) is None


def test_frames_are_in_file_order(sample_insv: Path) -> None:
    """Frames come back oldest-first, matching how the Java numbers them."""
    with sample_insv.open("rb") as f:
        metadata = InsvMetadata.read(f)

    assert metadata is not None
    codes = [frame.header.frame_type_code for frame in metadata.frames]
    assert codes == [12, 11, 10, 9, 7, 6, 5, 4, 3, 2, 1]
    assert metadata.find_frame(FrameType.INFO) is not None
    assert metadata.frames[-1].header.frame_ver == 1
