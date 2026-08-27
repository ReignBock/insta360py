"""Port of org.insvtools.records.GpsRecord."""

from __future__ import annotations

import struct
from datetime import datetime, timezone

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")
# 3 unknown bytes, then lat, N/S, lon, E/W, speed, track, altitude.
_BODY = struct.Struct("<3xdcdcddd")


def _java_instant(seconds: int) -> str:
    """Format like java.time.Instant.toString().

    Java omits the seconds component when it is zero, so "...T20:15Z" rather
    than "...T20:15:00Z". The dump output is compared against the Java's, so
    that quirk has to be reproduced.
    """
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    if dt.second:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _java_double(value: float) -> str:
    """Format a float the way Java's Double.toString() would."""
    if value != value or value in (float("inf"), float("-inf")):
        return {float("inf"): "Infinity", float("-inf"): "-Infinity"}.get(value, "NaN")
    text = repr(float(value))
    if "e" in text or "E" in text:
        # Python uses e-05 where Java uses E-5.
        mantissa, _, exponent = text.partition("e")
        return f"{mantissa}E{int(exponent)}"
    return text


class GpsRecord(TimestampedRecord):
    """A GPS fix.

    The payload is kept verbatim and written back unchanged; the decoded
    fields exist only for the human-readable dump.
    """

    SIZE = TS_SIZE + 45

    __slots__ = ("payload", "description")

    def __init__(self, timestamp: int, payload: bytes, description: str):
        super().__init__(timestamp)
        self.payload = payload
        self.description = description

    @classmethod
    def parse(cls, data: bytes, off: int) -> "GpsRecord":
        (timestamp,) = _TS.unpack_from(data, off)
        payload = data[off + TS_SIZE : off + cls.SIZE]
        latitude, ns, longitude, ew, speed, track, altitude = _BODY.unpack_from(
            data, off + TS_SIZE
        )
        description = (
            f"time {_java_instant(timestamp)}"
            f" position {_java_double(latitude)}{ns.decode('latin1')}"
            f" {_java_double(longitude)}{ew.decode('latin1')}"
            f" speed {_java_double(speed)}"
            f" track {_java_double(track)}"
            f" altitude {_java_double(altitude)}"
        )
        return cls(timestamp, payload, description)

    def to_bytes(self) -> bytes:
        return _TS.pack(self.timestamp) + self.payload
