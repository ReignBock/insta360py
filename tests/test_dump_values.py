"""The JSON writer's type dispatch and the nodes no golden dump reaches.

sample.insv's dump covers the common shapes. The INDEX node, V1 gyro records
and the primitive branches of the writer need their own inputs.
"""

# pylint: disable=protected-access,redefined-outer-name

import struct
from pathlib import Path

import pytest

from insvtools.dump.dumper import Raw, _record_node, _write, dump
from insvtools.frames.frame import Frame
from insvtools.frames.frame_header import FrameHeader
from insvtools.frames.frame_type import FrameType
from insvtools.frames.index_frame import IndexFrame
from insvtools.metadata import read_metadata
from insvtools.records.gyro_v1 import GyroV1Record
from insvtools.records.timestamped import TimestampedRecord


def test_index_frame_dump_lists_every_slot(x5_insv: Path) -> None:
    """Absent frame types show up as null, present ones as a header object."""
    metadata = read_metadata(x5_insv)
    metadata.parse()
    index = metadata.find_frame_of(IndexFrame)
    assert index is not None

    text = dump(index)

    assert '"framesIndex"' in text
    assert "null" in text  # slots for types this file has no frame of
    assert '"frameType"' in text


def test_v1_gyro_records_dump_as_doubles() -> None:
    """Six doubles, rendered the way java.util.Arrays.toString would."""
    record = GyroV1Record(123, (1.5, 2.0, 3.0, 4.0, 5.0, 6.0))

    node = _record_node(record)

    assert node["timestamp"] == 123
    assert node["payload"].text == "[1.5, 2.0, 3.0, 4.0, 5.0, 6.0]"


def test_an_unknown_record_type_is_rejected() -> None:
    """A record the dumper has no branch for is an error, not a silent skip."""

    class Mystery(TimestampedRecord):  # pylint: disable=too-few-public-methods
        """Not one of the record types the dumper knows."""

        def to_bytes(self) -> bytes:
            return b""

    with pytest.raises(TypeError, match="Unsupported record type Mystery"):
        _record_node(Mystery(0))


def test_dump_rejects_something_that_is_neither_metadata_nor_a_frame() -> None:
    """dump takes metadata or one frame, nothing else."""
    with pytest.raises(TypeError, match="Can't dump int"):
        dump(42)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (7, "7"),
        (1.5, "1.5"),
        ("hi", '"hi"'),
        ({}, "{}"),
        ([], "[]"),
        (Raw("<verbatim>"), "<verbatim>"),
    ],
)
def test_primitive_values_render_like_gson(value: object, expected: str) -> None:
    """Each scalar renders the way the Java dump does."""
    assert _write(value, "") == expected


def test_booleans_are_not_rendered_as_integers() -> None:
    """bool is a subclass of int, so the order of the checks matters."""
    assert _write({"flag": True}, "") == '{\n  "flag": true\n}'


def test_an_unsupported_value_type_is_rejected() -> None:
    """A value the writer has no branch for is an error, not a guess."""
    with pytest.raises(TypeError, match="Unsupported dump value set"):
        _write({1, 2}, "")


def test_a_frame_with_no_special_node_dumps_only_its_header() -> None:
    """Unknown frame types still dump, just without an interpreted body."""
    frame = Frame(FrameHeader(FrameType.THUMBNAIL.value, 0, 4, 16), b"abcd")

    text = dump(frame)

    assert '"frameType": "THUMBNAIL"' in text
    assert '"framesIndex"' not in text


def test_gyro_v1_roundtrips_through_its_dump_payload() -> None:
    """The doubles in the dump are the ones that came off disk."""
    raw = struct.pack("<q6d", 1, 0.5, -1.5, 2.25, 0.0, 100.0, -0.125)
    record = GyroV1Record.parse(raw, 0)

    assert _record_node(record)["payload"].text == "[0.5, -1.5, 2.25, 0.0, 100.0, -0.125]"
