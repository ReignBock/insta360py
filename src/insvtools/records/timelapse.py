"""Port of org.insvtools.records.TimelapseRecord."""

from __future__ import annotations

import struct

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")


class TimelapseRecord(TimestampedRecord):
    """Sample-to-timestamp mapping: one record per video sample."""

    SIZE = TS_SIZE

    __slots__ = ()

    @classmethod
    def parse(cls, data: bytes, off: int) -> "TimelapseRecord":
        (timestamp,) = _TS.unpack_from(data, off)
        return cls(timestamp)
