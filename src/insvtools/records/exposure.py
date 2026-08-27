"""Port of org.insvtools.records.ExposureRecord."""

from __future__ import annotations

import struct

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<qd")


class ExposureRecord(TimestampedRecord):
    SIZE = TS_SIZE + 8

    __slots__ = ("shutter_speed",)

    def __init__(self, timestamp: int, shutter_speed: float):
        super().__init__(timestamp)
        self.shutter_speed = shutter_speed

    @classmethod
    def parse(cls, data: bytes, off: int) -> "ExposureRecord":
        timestamp, shutter_speed = _REC.unpack_from(data, off)
        return cls(timestamp, shutter_speed)

    def to_bytes(self) -> bytes:
        return _REC.pack(self.timestamp, self.shutter_speed)
