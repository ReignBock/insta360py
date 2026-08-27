"""Sample-table variants that the two real fixtures happen not to contain.

sample.insv and x5_indexed.insv between them cover stco, co64 in the source
file, ctts and stss. The compact stz2 table, constant-size stsz, 64-bit box
headers and sdtp have no fixture, so they are exercised directly here.
"""

import io
import struct

import pytest

from insvtools.mp4 import reader as rd
from insvtools.mp4 import writer as wr
from insvtools.mp4.boxes import Box, box_bytes, parse_boxes
from insvtools.mp4.reader import Sample


def _sample(size: int, offset: int = 0, *, sync: bool = True) -> Sample:
    return Sample(offset=offset, size=size, duration=1, cts_offset=0, sync=sync, chunk=0)


def _stz2(count: int, body: bytes, field_size: int) -> bytes:
    """version/flags, three reserved bytes, the field size, then the count."""
    return (
        bytes(4)
        + bytes(3)
        + bytes([field_size])
        + struct.pack(">I", count)
        + body
    )


# --- stsz / stz2 ------------------------------------------------------------


def test_stsz_constant_size_expands_to_one_size_per_sample() -> None:
    """A non-zero sample_size means the table itself is empty."""
    payload = b"\x00\x00\x00\x00" + struct.pack(">II", 1024, 3)

    constant, sizes = rd._read_stsz(payload)  # pylint: disable=protected-access

    assert constant == 1024
    assert sizes == [1024, 1024, 1024]


def test_stz2_4_bit_fields_pack_two_sizes_per_byte() -> None:
    """The high nibble is the earlier sample."""
    payload = _stz2(3, bytes([0x12, 0x30]), field_size=4)

    constant, sizes = rd._read_stz2(payload)  # pylint: disable=protected-access

    assert constant == 0
    assert sizes == [1, 2, 3]


def test_stz2_8_bit_fields() -> None:
    """One byte per sample size."""
    payload = _stz2(3, bytes([7, 8, 9]), field_size=8)

    _, sizes = rd._read_stz2(payload)  # pylint: disable=protected-access

    assert sizes == [7, 8, 9]


def test_stz2_16_bit_fields() -> None:
    """Two bytes per sample size, big-endian."""
    payload = _stz2(2, struct.pack(">HH", 300, 400), field_size=16)

    _, sizes = rd._read_stz2(payload)  # pylint: disable=protected-access

    assert sizes == [300, 400]


def test_stz2_rejects_an_unknown_field_size() -> None:
    """Only 4, 8 and 16 are defined."""
    payload = _stz2(1, b"\x00", field_size=12)

    with pytest.raises(ValueError, match="field size 12"):
        rd._read_stz2(payload)  # pylint: disable=protected-access


def test_writer_keeps_a_constant_size_table_constant() -> None:
    """Uniform samples round-trip back into the compact form."""
    box = wr._stsz([_sample(512), _sample(512)], 512)  # pylint: disable=protected-access

    constant, sizes = rd._read_stsz(box[8:])  # pylint: disable=protected-access

    assert box[4:8] == b"stsz"
    assert constant == 512
    assert sizes == [512, 512]


def test_writer_falls_back_to_a_full_table_when_sizes_differ() -> None:
    """One size per sample once they stop matching."""
    box = wr._stsz([_sample(512), _sample(513)], 512)  # pylint: disable=protected-access

    constant, sizes = rd._read_stsz(box[8:])  # pylint: disable=protected-access

    assert constant == 0
    assert sizes == [512, 513]


# --- chunk offsets ----------------------------------------------------------


def test_offsets_past_4gb_are_written_as_co64() -> None:
    """The X5 files are tens of GB, so this is the normal case for them."""
    chunks = [
        wr._Chunk(0, [_sample(1)], 0, 0, new_offset=0x1_0000_0000),  # pylint: disable=protected-access
        wr._Chunk(0, [_sample(1)], 0, 0, new_offset=0x1_0000_0010),  # pylint: disable=protected-access
    ]

    box = wr._chunk_offset_box(chunks)  # pylint: disable=protected-access
    parsed = rd._read_chunk_offsets(  # pylint: disable=protected-access
        Box(b"co64", 0, len(box), 8), box[8:]
    )

    assert box[4:8] == b"co64"
    assert parsed == [0x1_0000_0000, 0x1_0000_0010]


def test_offsets_within_4gb_stay_stco() -> None:
    """32-bit offsets keep the compact box."""
    chunks = [wr._Chunk(0, [_sample(1)], 0, 0, new_offset=32)]  # pylint: disable=protected-access

    box = wr._chunk_offset_box(chunks)  # pylint: disable=protected-access
    parsed = rd._read_chunk_offsets(  # pylint: disable=protected-access
        Box(b"stco", 0, len(box), 8), box[8:]
    )

    assert box[4:8] == b"stco"
    assert parsed == [32]


# --- sdtp -------------------------------------------------------------------


def test_sdtp_is_clipped_to_the_kept_samples() -> None:
    """One byte per sample follows the version/flags word."""
    payload = b"\x00\x00\x00\x00" + bytes([10, 11, 12, 13, 14])

    clipped = wr._sdtp(payload, 1, 4)  # pylint: disable=protected-access

    assert clipped[4:8] == b"sdtp"
    assert clipped[8:12] == b"\x00\x00\x00\x00"
    assert clipped[12:] == bytes([11, 12, 13])


# --- durations --------------------------------------------------------------


def test_patch_duration_handles_the_64_bit_header_form() -> None:
    """Version 1 mdhd/mvhd keep the duration in a 64-bit field."""
    payload = bytearray(b"\x01\x00\x00\x00" + bytes(28))
    patched = wr._patch_duration(bytes(payload), 2**33, (20, 24))  # pylint: disable=protected-access

    assert struct.unpack_from(">Q", patched, 24)[0] == 2**33


def test_patch_duration_saturates_the_32_bit_form() -> None:
    """A duration too large for the field is clamped, not truncated."""
    payload = bytes(32)
    patched = wr._patch_duration(payload, 2**33, (20, 24))  # pylint: disable=protected-access

    assert struct.unpack_from(">I", patched, 20)[0] == 0xFFFFFFFF


# --- box headers ------------------------------------------------------------


def test_64_bit_box_header_is_parsed() -> None:
    """size == 1 means the real size follows the type as a 64-bit value."""
    payload = b"payload!"
    raw = struct.pack(">I", 1) + b"free" + struct.pack(">Q", 16 + len(payload)) + payload
    f = io.BytesIO(raw)

    boxes = parse_boxes(f, 0, len(raw))

    assert [b.type for b in boxes] == [b"free"]
    assert boxes[0].header_size == 16
    assert boxes[0].payload(f) == payload


def test_zero_size_box_runs_to_the_end_of_the_region() -> None:
    """size == 0 means 'to the end', which here is the region's end."""
    raw = struct.pack(">I", 0) + b"mdat" + b"abcd"
    f = io.BytesIO(raw)

    boxes = parse_boxes(f, 0, len(raw))

    assert boxes[0].size == len(raw)


def test_box_running_past_the_region_is_rejected() -> None:
    """A size that overruns the region is corruption, not a box."""
    raw = struct.pack(">I", 999) + b"mdat"
    f = io.BytesIO(raw)

    with pytest.raises(ValueError, match="runs past"):
        parse_boxes(f, 0, len(raw))


def test_a_truncated_header_ends_the_walk() -> None:
    """Trailing bytes too short to be a header are simply not a box."""
    raw = box_bytes(b"free", b"") + b"\x00\x00\x00"
    f = io.BytesIO(raw)

    assert [b.type for b in parse_boxes(f, 0, len(raw))] == [b"free"]


def test_find_returns_none_for_a_missing_path() -> None:
    """A path that runs out gives None rather than raising."""
    f = io.BytesIO(box_bytes(b"moov", box_bytes(b"mvhd", b"")))
    moov = parse_boxes(f, 0, len(f.getvalue()))[0]

    assert moov.find(b"mvhd") is not None
    assert moov.find(b"trak") is None
    assert moov.find(b"mvhd", b"nope") is None
