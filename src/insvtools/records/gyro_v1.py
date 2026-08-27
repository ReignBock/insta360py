"""Port of org.insvtools.records.GyroV1Record."""

from __future__ import annotations

import struct

from .timestamped import TS_SIZE, TimestampedRecord

_REC = struct.Struct("<q6d")


class GyroV1Record(TimestampedRecord):
    """Timestamp plus six doubles.

    Upstream does not commit to what the six values are (presumably
    acceleration and rotation triples), so they stay an opaque payload.
    """

    SIZE = TS_SIZE + 6 * 8

    __slots__ = ("payload",)

    def __init__(self, timestamp: int, payload: tuple[float, ...]):
        super().__init__(timestamp)
        self.payload = payload

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GyroV1Record":
        timestamp, *payload = _REC.unpack_from(data, off)
        return cls(timestamp, tuple(payload))

    def to_bytes(self) -> bytes:
        assert len(self.payload) == 6
        return _REC.pack(self.timestamp, *self.payload)
