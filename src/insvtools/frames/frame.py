"""Port of org.insvtools.frames.Frame."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from .frame_header import FrameHeader
from .frame_type import FrameType

if TYPE_CHECKING:
    from ..metadata import InsvMetadata


class Frame:
    """A metadata frame: a header plus an opaque payload.

    Subclasses interpret the payload, but only once :meth:`parse` succeeds.
    Until then - and permanently, for frame types we don't understand - the
    original bytes are what gets written back out. That is what makes
    round-tripping a file byte-exact.
    """

    def __init__(self, header: FrameHeader, payload: bytes):
        self.header = header
        self.payload = payload
        self.parsed = False

    @staticmethod
    def read(f: BinaryIO, header: FrameHeader) -> "Frame":
        f.seek(header.frame_pos)
        payload = f.read(header.frame_size)
        if len(payload) != header.frame_size:
            raise ValueError(
                f"Truncated frame at {header.frame_pos}: expected {header.frame_size} "
                f"bytes, got {len(payload)}"
            )
        return _create(header, payload)

    @staticmethod
    def create(header: FrameHeader, payload: bytes) -> "Frame":
        """Build the right Frame subclass for a header and payload."""
        return _create(header, payload)

    @staticmethod
    def read_raw(f: BinaryIO, from_pos: int, to_pos: int) -> "Frame":
        """Read [from_pos, to_pos) as a synthetic RAW frame."""
        return Frame.read(
            f, FrameHeader(FrameType.RAW.value, 0, to_pos - from_pos, from_pos)
        )

    def write(self, f: BinaryIO) -> int:
        """Write the frame, returning total bytes written (payload + header)."""
        return self._write_parsed(f) if self.parsed else self._write_payload(f)

    def _write_parsed(self, f: BinaryIO) -> int:
        return self._write_payload(f)

    def _write_payload(self, f: BinaryIO) -> int:
        f.write(self.payload)
        return len(self.payload) + self.header.write(f, len(self.payload))

    def parse(self, metadata: "InsvMetadata") -> None:
        if self.parsed:
            return
        self.parsed = self._parse_internal(metadata)

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        """Interpret the payload; return True if it was understood.

        The default leaves the payload opaque.
        """
        return False

    def __repr__(self) -> str:
        return f"{type(self).__name__}{{header={self.header!r}, parsed={self.parsed}}}"


def _create(header: FrameHeader, payload: bytes) -> Frame:
    """Instantiate the right Frame subclass for a header.

    Imported lazily: the subclasses import Frame, so a module-level import
    here would be circular.
    """
    from .exposure_frame import ExposureFrame
    from .gps_frame import GpsFrame
    from .gyro_frame import GyroFrame
    from .index_frame import IndexFrame
    from .info_frame import InfoFrame
    from .timelapse_frame import TimelapseFrame

    cls = {
        FrameType.INDEX: IndexFrame,
        FrameType.INFO: InfoFrame,
        FrameType.GYRO: GyroFrame,
        FrameType.EXPOSURE: ExposureFrame,
        FrameType.TIMELAPSE: TimelapseFrame,
        FrameType.GPS: GpsFrame,
    }.get(header.frame_type, Frame)

    return cls(header, payload)
