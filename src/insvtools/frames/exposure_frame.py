"""Port of org.insvtools.frames.ExposureFrame."""

from __future__ import annotations

from ..records.exposure import ExposureRecord
from .timestamped_frame import TimestampedFrame


class ExposureFrame(TimestampedFrame):
    def _record_size(self) -> int:
        return ExposureRecord.SIZE

    def _parse_record(self, data: bytes, off: int) -> ExposureRecord:
        return ExposureRecord.parse(data, off)
