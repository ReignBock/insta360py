"""Reading frames from a file, and picking the class that understands each one.

This lives apart from :mod:`insvtools.frames.frame` so that the base class does
not have to import its own subclasses, which would be a circular import.
"""

from __future__ import annotations

from typing import BinaryIO

from .exposure_frame import ExposureFrame
from .frame import Frame
from .frame_header import FrameHeader
from .frame_type import FrameType
from .gps_frame import GpsFrame
from .gyro_frame import GyroFrame
from .index_frame import IndexFrame
from .info_frame import InfoFrame
from .timelapse_frame import TimelapseFrame

_BY_TYPE: dict[FrameType, type[Frame]] = {
    FrameType.INDEX: IndexFrame,
    FrameType.INFO: InfoFrame,
    FrameType.GYRO: GyroFrame,
    FrameType.EXPOSURE: ExposureFrame,
    FrameType.TIMELAPSE: TimelapseFrame,
    FrameType.GPS: GpsFrame,
}


def create(header: FrameHeader, payload: bytes) -> Frame:
    """Build the frame class for a header, or a plain Frame if we have none.

    An unknown type code gives a ``frame_type`` of None, which lands on the
    same plain Frame as a known type we have no special class for.
    """
    frame_type = header.frame_type
    cls = Frame if frame_type is None else _BY_TYPE.get(frame_type, Frame)
    return cls(header, payload)


def read(f: BinaryIO, header: FrameHeader) -> Frame:
    """Read the payload a header describes."""
    f.seek(header.frame_pos)
    payload = f.read(header.frame_size)

    if len(payload) != header.frame_size:
        raise ValueError(
            f"Truncated frame at {header.frame_pos}: expected {header.frame_size} "
            f"bytes, got {len(payload)}"
        )

    return create(header, payload)


def read_raw(f: BinaryIO, from_pos: int, to_pos: int) -> Frame:
    """Read [from_pos, to_pos) as a synthetic RAW frame."""
    return read(f, FrameHeader(FrameType.RAW.value, 0, to_pos - from_pos, from_pos))
