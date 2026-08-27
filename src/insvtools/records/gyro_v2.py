"""Port of org.insvtools.records.GyroV2Record."""

from __future__ import annotations

import struct

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<q6h")


class GyroV2Record(TimestampedRecord):
    """Timestamp plus six int16s."""

    SIZE = TS_SIZE + 6 * 2

    __slots__ = ("payload",)

    def __init__(self, timestamp: int, payload: tuple[int, ...]):
        super().__init__(timestamp)
        self.payload = payload

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GyroV2Record":
        timestamp, *payload = _REC.unpack_from(data, off)
        return cls(timestamp, tuple(payload))

    def to_bytes(self) -> bytes:
        assert len(self.payload) == 6
        return _REC.pack(self.timestamp, *self.payload)
