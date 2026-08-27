"""Port of org.insvtools.frames.InfoFrame."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from ..extra_metadata_pb2 import ExtraMetadata
from ..records.gyro_raw import GyroRawRecord
from .frame import Frame

if TYPE_CHECKING:
    from ..metadata import InsvMetadata


class InfoFrame(Frame):
    """The INFO frame (type 1): a protobuf ExtraMetadata message.

    This must be parsed before any other frame, because the gyro frame's
    record size comes from the ``Gyro`` field here.
    """

    def __init__(self, header, payload: bytes):
        super().__init__(header, payload)
        self.extra_metadata: ExtraMetadata | None = None
        self.gyro_record: GyroRawRecord | None = None

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        # Version 1 is protobuf; anything else was JSON, which upstream never
        # implemented and no known file uses.
        if self.header.frame_ver != 1:
            raise ValueError(f"Unsupported InfoFrame version {self.header.frame_ver}")

        self.extra_metadata = ExtraMetadata()
        self.extra_metadata.ParseFromString(self.payload)

        gyro = self.extra_metadata.Gyro
        self.gyro_record = GyroRawRecord.parse(gyro, 0, len(gyro)) if gyro else None

        return True

    def _write_parsed(self, f: BinaryIO) -> int:
        assert self.extra_metadata is not None
        body = self.extra_metadata.SerializeToString()
        f.write(body)
        return len(body) + self.header.write(f, len(body))

    def _require_parsed(self) -> ExtraMetadata:
        if not self.parsed or self.extra_metadata is None:
            raise RuntimeError("Metadata is not parsed")
        return self.extra_metadata

    @property
    def gyro_timestamp(self) -> int:
        return -1 if self.gyro_record is None else self.gyro_record.timestamp

    @gyro_timestamp.setter
    def gyro_timestamp(self, timestamp: int) -> None:
        if self.gyro_record is None:
            return
        extra = self._require_parsed()
        self.gyro_record.timestamp = timestamp
        extra.Gyro = self.gyro_record.to_bytes()

    def set_file_size(self, file_size: int) -> None:
        self._require_parsed().FileSize = file_size

    def set_first_frame_timestamp(self, timestamp: int) -> None:
        self._require_parsed().FirstFrameTimestamp = timestamp

    def set_total_time(self, total_time: int) -> None:
        self._require_parsed().TotalTime = total_time

    def set_first_gps_timestamp(self, timestamp: int) -> None:
        self._require_parsed().FirstGpsTimestamp = timestamp
