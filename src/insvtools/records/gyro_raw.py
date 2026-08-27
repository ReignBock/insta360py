"""Fallback for gyro record sizes we don't recognise: timestamp plus bytes."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")


@dataclass
class GyroRawRecord(TimestampedRecord):
    """Gyro values of an unrecognised size, kept as bytes."""

    payload: bytes

    @classmethod
    def parse(cls, data: bytes, off: int, record_size: int) -> "GyroRawRecord":
        """Read one record of ``record_size`` bytes, timestamp included."""
        (timestamp,) = _TS.unpack_from(data, off)
        return cls(timestamp, data[off + TS_SIZE : off + record_size])

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _TS.pack(self.timestamp) + self.payload
