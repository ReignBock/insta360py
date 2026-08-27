"""Port of org.insvtools.frames.InfoFrame."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

# protobuf 7.x builds message classes at runtime via _builder, so no static
# analyser can see this name; pylint-protobuf does not resolve it either.
from ..extra_metadata_pb2 import ExtraMetadata  # pylint: disable=no-name-in-module
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

    @property
    def gyro_timestamp(self) -> int:
        """The timestamp of the sample gyro record, or -1 if there is none."""
        return -1 if self.gyro_record is None else self.gyro_record.timestamp

    @gyro_timestamp.setter
    def gyro_timestamp(self, timestamp: int) -> None:
        # Setting this has to re-encode the blob it was read from.
        if self.gyro_record is None or self.extra_metadata is None:
            return

        self.gyro_record.timestamp = timestamp
        self.extra_metadata.Gyro = self.gyro_record.to_bytes()
