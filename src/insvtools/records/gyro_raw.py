"""Port of org.insvtools.records.GyroRawRecord."""

from __future__ import annotations

import struct

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")


class GyroRawRecord(TimestampedRecord):
    """Fallback for gyro record sizes we don't recognise: timestamp + bytes."""

    __slots__ = ("payload",)

    def __init__(self, timestamp: int, payload: bytes):
        super().__init__(timestamp)
        self.payload = payload

    @property
    def SIZE(self) -> int:  # noqa: N802 - mirrors the constant on siblings
        return TS_SIZE + len(self.payload)

    @classmethod
    def parse(cls, data: bytes, off: int, record_size: int) -> "GyroRawRecord":
        (timestamp,) = _TS.unpack_from(data, off)
        return cls(timestamp, data[off + TS_SIZE : off + record_size])

    def to_bytes(self) -> bytes:
        return _TS.pack(self.timestamp) + self.payload
