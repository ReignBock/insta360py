"""Port of org.insvtools.frames.GpsFrame."""

from __future__ import annotations

from ..records.gps import GpsRecord
from .timestamped_frame import TimestampedFrame


class GpsFrame(TimestampedFrame):
    def _record_size(self) -> int:
        return GpsRecord.SIZE

    def _parse_record(self, data: bytes, off: int) -> GpsRecord:
        return GpsRecord.parse(data, off)
