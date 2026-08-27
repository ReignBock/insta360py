"""Exposure records: timestamp plus shutter speed."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<qd")


@dataclass
class ExposureRecord(TimestampedRecord):
    """A shutter speed reading."""

    shutter_speed: float

    SIZE: ClassVar[int] = TS_SIZE + 8

    @classmethod
    def parse(cls, data: bytes, off: int) -> "ExposureRecord":
        """Read a shutter speed reading at ``off``."""
        timestamp, shutter_speed = _REC.unpack_from(data, off)
        return cls(timestamp, shutter_speed)

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _REC.pack(self.timestamp, self.shutter_speed)
