"""Gyro records, 20-byte form: timestamp plus six int16s."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<q6h")


@dataclass
class GyroV2Record(TimestampedRecord):
    """Six int16 gyro values, as written by newer firmware."""

    payload: tuple[int, ...]

    SIZE: ClassVar[int] = TS_SIZE + 6 * 2

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GyroV2Record":
        """Read six int16 values at ``off``."""
        timestamp, *payload = _REC.unpack_from(data, off)
        return cls(timestamp, tuple(payload))

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _REC.pack(self.timestamp, *self.payload)
