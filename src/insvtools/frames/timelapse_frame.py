"""Port of org.insvtools.frames.TimelapseFrame."""

from __future__ import annotations

from ..records.timelapse import TimelapseRecord
from .timestamped_frame import TimestampedFrame


class TimelapseFrame(TimestampedFrame):
    """Sample-to-timestamp mapping, used by timelapse videos."""

    def _record_size(self) -> int:
        return TimelapseRecord.SIZE

    def _parse_record(self, data: bytes, off: int) -> TimelapseRecord:
        return TimelapseRecord.parse(data, off)
