"""GPS fixes.

The payload is kept verbatim and written back unchanged; the decoded fields
exist so callers don't have to unpack it again.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")
# 3 unknown bytes, then lat, N/S, lon, E/W, speed, track, altitude.
_BODY = struct.Struct("<3xdcdcddd")


@dataclass
class GpsRecord(TimestampedRecord):  # pylint: disable=too-many-instance-attributes
    """A GPS fix: position, speed, track and altitude."""

    payload: bytes
    latitude: float
    north_south: str
    longitude: float
    east_west: str
    speed: float
    track: float
    altitude: float

    SIZE: ClassVar[int] = TS_SIZE + 45

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GpsRecord":
        """Read a GPS fix at ``off``."""
        (timestamp,) = _TS.unpack_from(data, off)
        payload = data[off + TS_SIZE : off + cls.SIZE]
        latitude, ns, longitude, ew, speed, track, altitude = _BODY.unpack_from(
            data, off + TS_SIZE
        )
        return cls(
            timestamp,
            payload,
            latitude,
            ns.decode("latin1"),
            longitude,
            ew.decode("latin1"),
            speed,
            track,
            altitude,
        )

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _TS.pack(self.timestamp) + self.payload
