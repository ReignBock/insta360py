"""Gyro records, 56-byte form: timestamp plus six doubles."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<q6d")


@dataclass
class GyroV1Record(TimestampedRecord):
    """Upstream does not commit to what the six values mean (presumably
    acceleration and rotation triples), so they stay an opaque payload."""

    payload: tuple[float, ...]

    SIZE: ClassVar[int] = TS_SIZE + 6 * 8

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GyroV1Record":
        """Read six doubles at ``off``."""
        timestamp, *payload = _REC.unpack_from(data, off)
        return cls(timestamp, tuple(payload))

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _REC.pack(self.timestamp, *self.payload)
