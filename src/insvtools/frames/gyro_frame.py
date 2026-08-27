"""Port of org.insvtools.frames.GyroFrame."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..records.gyro_raw import GyroRawRecord
from ..records.gyro_v1 import GyroV1Record
from ..records.gyro_v2 import GyroV2Record
from ..records.timestamped import TimestampedRecord
from .frame_type import FrameType
from .timestamped_frame import TimestampedFrame

if TYPE_CHECKING:
    from ..metadata import InsvMetadata


class GyroFrame(TimestampedFrame):
    """Gyro samples.

    The record size is not stored anywhere in this frame: it is the length of
    the sample gyro blob in the INFO frame. Without a parsed INFO frame there
    is no way to split the payload, so it stays opaque.
    """

    def __init__(self, header, payload: bytes):
        super().__init__(header, payload)
        self.record_size = 0

    def _record_size(self) -> int:
        return self.record_size

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        info = metadata.find_frame(FrameType.INFO)

        if info is None or not info.parsed or info.extra_metadata is None:
            return False

        self.record_size = len(info.extra_metadata.Gyro)
        if self.record_size == 0:
            return False

        return super()._parse_internal(metadata)

    def _parse_record(self, data: bytes, off: int) -> TimestampedRecord:
        if self.record_size == GyroV1Record.SIZE:
            return GyroV1Record.parse(data, off)
        if self.record_size == GyroV2Record.SIZE:
            return GyroV2Record.parse(data, off)
        return GyroRawRecord.parse(data, off, self.record_size)
