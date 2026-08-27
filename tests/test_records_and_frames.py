"""Frame and record variants no fixture reaches.

sample.insv carries 20-byte (V2) gyro records and the X5 fixture carries none
at all, so the 56-byte V1 form and the unrecognised-size fallback are built
here from their on-disk bytes.
"""

import struct

import pytest

from insvtools.frames import factory
from insvtools.frames.frame import Frame
from insvtools.frames.frame_header import FrameHeader
from insvtools.frames.frame_type import FrameType
from insvtools.frames.gyro_frame import GyroFrame
from insvtools.frames.index_frame import IndexFrame
from insvtools.frames.info_frame import InfoFrame
from insvtools.header import InsvHeader
from insvtools.metadata import InsvMetadata
from insvtools.records.gyro_raw import GyroRawRecord
from insvtools.records.gyro_v1 import GyroV1Record
from insvtools.records.gyro_v2 import GyroV2Record

# ExtraMetadata.Gyro is field 14, wire type 2 (length-delimited).
_GYRO_FIELD = bytes([14 << 3 | 2])


def _info_payload(gyro: bytes) -> bytes:
    """An ExtraMetadata message carrying just a Gyro blob."""
    return _GYRO_FIELD + bytes([len(gyro)]) + gyro


def _metadata_with_gyro(sample_gyro: bytes, gyro_payload: bytes) -> InsvMetadata:
    """A two-frame trailer: INFO defining the record size, then GYRO."""
    info_payload = _info_payload(sample_gyro)
    info = InfoFrame(FrameHeader(FrameType.INFO.value, 1, len(info_payload), 0), info_payload)
    gyro = GyroFrame(
        FrameHeader(FrameType.GYRO.value, 0, len(gyro_payload), 0), gyro_payload
    )
    return InsvMetadata(InsvHeader.dummy(), [info, gyro])


def test_gyro_v1_records_are_six_doubles() -> None:
    """56 bytes: an int64 timestamp and six doubles."""
    values = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    record = struct.pack("<q6d", 12345, *values)

    metadata = _metadata_with_gyro(bytes(GyroV1Record.SIZE), record * 2)
    metadata.parse()
    gyro = metadata.find_frame_of(GyroFrame)

    assert gyro is not None
    assert gyro.record_size == 56
    assert len(gyro.records) == 2
    assert isinstance(gyro.records[0], GyroV1Record)
    assert gyro.records[0].timestamp == 12345
    assert gyro.records[0].payload == values
    assert gyro.records[0].to_bytes() == record


def test_gyro_v2_records_are_six_shorts() -> None:
    """20 bytes: an int64 timestamp and six int16 values."""
    record = struct.pack("<q6h", 999, 1, 2, 3, 4, 5, 6)

    metadata = _metadata_with_gyro(bytes(GyroV2Record.SIZE), record)
    metadata.parse()
    gyro = metadata.find_frame_of(GyroFrame)

    assert gyro is not None
    assert isinstance(gyro.records[0], GyroV2Record)
    assert gyro.records[0].to_bytes() == record


def test_an_unrecognised_record_size_falls_back_to_raw_bytes() -> None:
    """Neither 56 nor 20: the values stay opaque but records still split."""
    record = struct.pack("<q", 7) + b"\xaa" * 16

    metadata = _metadata_with_gyro(bytes(24), record * 3)
    metadata.parse()
    gyro = metadata.find_frame_of(GyroFrame)

    assert gyro is not None
    assert gyro.record_size == 24
    assert len(gyro.records) == 3
    assert isinstance(gyro.records[0], GyroRawRecord)
    assert gyro.records[0].payload == b"\xaa" * 16
    assert gyro.records[0].to_bytes() == record


def test_gyro_without_an_info_frame_stays_opaque() -> None:
    """The record size lives in INFO, so there is nothing to parse without it."""
    payload = b"\x00" * 56
    gyro = GyroFrame(FrameHeader(FrameType.GYRO.value, 0, len(payload), 0), payload)
    metadata = InsvMetadata(InsvHeader.dummy(), [gyro])

    metadata.parse()

    assert not gyro.parsed
    assert not gyro.records


def test_info_frame_rejects_a_non_protobuf_version() -> None:
    """Version != 1 meant JSON, which upstream never implemented."""
    info = InfoFrame(FrameHeader(FrameType.INFO.value, 2, 0, 0), b"")
    metadata = InsvMetadata(InsvHeader.dummy(), [info])

    with pytest.raises(ValueError, match="Unsupported InfoFrame version 2"):
        metadata.parse()


def test_gyro_timestamp_reads_and_rewrites_the_sample_blob() -> None:
    """Setting it has to re-encode the blob the record came from."""
    sample = struct.pack("<q", 4242) + b"\x01" * 12
    info = InfoFrame(
        FrameHeader(FrameType.INFO.value, 1, 0, 0), _info_payload(sample)
    )
    metadata = InsvMetadata(InsvHeader.dummy(), [info])
    metadata.parse()

    assert info.gyro_timestamp == 4242

    info.gyro_timestamp = 99
    assert info.gyro_timestamp == 99
    assert info.extra_metadata is not None
    assert info.extra_metadata.Gyro == struct.pack("<q", 99) + b"\x01" * 12


def test_gyro_timestamp_is_minus_one_without_a_sample() -> None:
    """An empty Gyro - what the X5 writes - has no timestamp to report."""
    info = InfoFrame(FrameHeader(FrameType.INFO.value, 1, 0, 0), b"")
    metadata = InsvMetadata(InsvHeader.dummy(), [info])
    metadata.parse()

    assert info.gyro_timestamp == -1

    info.gyro_timestamp = 5  # silently ignored: nothing to re-encode
    assert info.gyro_timestamp == -1


def test_index_frame_rejects_a_ragged_payload() -> None:
    """The payload must be a whole number of 10-byte entries."""
    index = IndexFrame(FrameHeader(FrameType.INDEX.value, 0, 7, 0), b"x" * 7)
    metadata = InsvMetadata(InsvHeader.dummy(), [index])

    with pytest.raises(ValueError, match="Unexpected INDEX frame size: 7"):
        metadata.parse()


def test_reading_a_truncated_frame_is_an_error(tmp_path) -> None:
    """A header promising more bytes than the file holds must not pass silently."""
    path = tmp_path / "short.bin"
    path.write_bytes(b"only-ten!!")

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="Truncated frame"):
            factory.read(f, FrameHeader(FrameType.GPS.value, 0, 999, 0))


def test_an_unparsed_frame_writes_its_original_bytes(tmp_path) -> None:
    """The base class has no interpreted form to write back."""
    frame = Frame(FrameHeader(99, 0, 4, 0), b"abcd")
    frame.parsed = True  # nothing overrode _write_parsed

    path = tmp_path / "out.bin"
    with path.open("wb") as f:
        written = frame.write(f)

    assert written == 4 + 6
    assert path.read_bytes()[:4] == b"abcd"


def test_frame_repr_names_the_class_and_parse_state() -> None:
    """Enough to identify a frame in a traceback."""
    frame = Frame(FrameHeader(FrameType.GPS.value, 0, 0, 0), b"")

    assert "Frame" in repr(frame)
    assert "parsed=False" in repr(frame)
