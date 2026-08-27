"""Port of org.insvtools.records.TimestampedRecord."""

from __future__ import annotations

import struct

TS_SIZE = 8
_TS = struct.Struct("<q")


class TimestampedRecord:
    """Base for the record types that all begin with an int64 timestamp."""

    SIZE = TS_SIZE

    __slots__ = ("timestamp",)

    def __init__(self, timestamp: int):
        self.timestamp = timestamp

    @classmethod
    def parse(cls, data: bytes, off: int) -> "TimestampedRecord":
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        return _TS.pack(self.timestamp)
