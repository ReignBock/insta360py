"""Port of org.insvtools.dump.

Reproduces what Gson emits when reflecting over the Java object graph, so the
output can be diffed against the reference tool. Two things are load-bearing:

* field order is most-derived class first, then superclasses;
* byte arrays are written as ``\\xNN`` escapes, which is not valid JSON but is
  what upstream's BytesAdapter produces.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.protobuf import json_format

from ..frames.frame import Frame
from ..frames.gyro_frame import GyroFrame
from ..frames.index_frame import IndexFrame
from ..frames.info_frame import InfoFrame
from ..frames.timestamped_frame import TimestampedFrame
from ..header import InsvHeader
from ..metadata import InsvMetadata
from ..records.exposure import ExposureRecord
from ..records.gps import GpsRecord
from ..records.gyro_raw import GyroRawRecord
from ..records.gyro_v1 import GyroV1Record
from ..records.gyro_v2 import GyroV2Record
from ..records.timelapse import TimelapseRecord
from ..records.timestamped import TimestampedRecord

INDENT = "  "


def _number(value: float) -> str:
    """Render a float for the dump.

    Python's repr is the shortest string that round-trips, which is also what
    Java's Double.toString aims for, so ordinary values render identically to
    the reference tool. The two disagree only on where to switch to
    exponent notation (Java does so beyond 1e7 and below 1e-3); no camera
    value comes close to either bound.
    """
    return repr(float(value))


def _gps_description(record: GpsRecord) -> str:
    """A one-line human-readable summary of a GPS fix."""
    when = datetime.fromtimestamp(record.timestamp, tz=timezone.utc)
    return (
        f"time {when:%Y-%m-%dT%H:%M:%SZ}"
        f" position {_number(record.latitude)}{record.north_south}"
        f" {_number(record.longitude)}{record.east_west}"
        f" speed {_number(record.speed)}"
        f" track {_number(record.track)}"
        f" altitude {_number(record.altitude)}"
    )


class Raw:  # pylint: disable=too-few-public-methods
    """A value written verbatim, bypassing JSON encoding."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


def _bytes_value(data: bytes) -> Raw:
    """Upstream's BytesAdapter: a quoted run of \\xNN escapes."""
    return Raw('"' + "".join(f"\\x{b:02X}" for b in data) + '"')


def _array_value(values, fmt) -> Raw:
    """Upstream's Shorts/DoublesAdapter: java.util.Arrays.toString()."""
    return Raw("[" + ", ".join(fmt(v) for v in values) + "]")


def _header_node(header: InsvHeader) -> dict[str, Any]:
    return {
        "unknownBuf": _bytes_value(header.unknown_buf),
        "version": header.version,
        "metaDataSize": header.metadata_size,
    }


def _frame_header_node(header) -> dict[str, Any]:
    node: dict[str, Any] = {"frameTypeCode": header.frame_type_code}
    # Gson omits nulls, so an unrecognised type code has no frameType at all.
    if header.frame_type is not None:
        node["frameType"] = header.frame_type.name
    node["frameVer"] = header.frame_ver
    node["frameSize"] = header.frame_size
    return node


def _record_node(record: TimestampedRecord) -> dict[str, Any]:
    node: dict[str, Any] = {}

    if isinstance(record, GpsRecord):
        node["payload"] = _bytes_value(record.payload)
        node["description"] = _gps_description(record)
    elif isinstance(record, GyroV1Record):
        node["payload"] = _array_value(record.payload, _number)
    elif isinstance(record, GyroV2Record):
        node["payload"] = _array_value(record.payload, str)
    elif isinstance(record, GyroRawRecord):
        node["payload"] = _bytes_value(record.payload)
    elif isinstance(record, ExposureRecord):
        node["shutterSpeed"] = Raw(_number(record.shutter_speed))
    elif not isinstance(record, TimelapseRecord):
        raise TypeError(f"Unsupported record type {type(record).__name__}")

    node["timestamp"] = record.timestamp
    return node


def _extra_metadata_node(frame: InfoFrame) -> Raw:
    """The protobuf message, indented by 8 spaces on every line."""
    text = json_format.MessageToJson(frame.extra_metadata, indent=2)
    indented = "\n".join(" " * 8 + line for line in text.splitlines())
    return Raw("\n" + indented)


def _frame_node(frame: Frame) -> dict[str, Any]:
    node: dict[str, Any] = {}

    if isinstance(frame, IndexFrame):
        node["framesIndex"] = [
            _frame_header_node(h) if h is not None else None for h in frame.frames_index
        ]
    elif isinstance(frame, InfoFrame):
        if frame.extra_metadata is not None:
            node["extraMetadata"] = _extra_metadata_node(frame)
        if frame.gyro_record is not None:
            node["gyroRecord"] = _record_node(frame.gyro_record)
    elif isinstance(frame, TimestampedFrame):
        if isinstance(frame, GyroFrame):
            node["recordSize"] = frame.record_size
        node["records"] = [_record_node(r) for r in frame.records]

    node["header"] = _frame_header_node(frame.header)
    return node


def _metadata_node(metadata: InsvMetadata) -> dict[str, Any]:
    return {
        "header": _header_node(metadata.header),
        "frames": [_frame_node(frame) for frame in metadata.frames],
    }


def _write(value: Any, indent: str) -> str:  # pylint: disable=too-many-return-statements
    """Render one value; the branches are a type dispatch, not logic."""
    if isinstance(value, Raw):
        return value.text
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + INDENT
        body = ",\n".join(
            f"{inner}{json.dumps(k)}: {_write(v, inner)}" for k, v in value.items()
        )
        return "{\n" + body + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = indent + INDENT
        body = ",\n".join(f"{inner}{_write(v, inner)}" for v in value)
        return "[\n" + body + "\n" + indent + "]"
    raise TypeError(f"Unsupported dump value {type(value).__name__}")


def dump(obj: InsvMetadata | Frame) -> str:
    """Serialize metadata or a single frame the way the Java tool does."""
    if isinstance(obj, InsvMetadata):
        node = _metadata_node(obj)
    elif isinstance(obj, Frame):
        node = _frame_node(obj)
    else:
        raise TypeError(f"Can't dump {type(obj).__name__}")

    return _write(node, "")
