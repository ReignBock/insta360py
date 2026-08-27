"""Port of org.insvtools.frames.TimestampedFrame."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from ..records.timestamped import TimestampedRecord
from .frame import Frame

if TYPE_CHECKING:
    from ..metadata import InsvMetadata


class TimestampedFrame(Frame):
    """A frame whose payload is a flat array of fixed-size records."""

    def __init__(self, header, payload: bytes):
        super().__init__(header, payload)
        self.records: list[TimestampedRecord] = []

    def _record_size(self) -> int:
        raise NotImplementedError

    def _parse_record(self, data: bytes, off: int) -> TimestampedRecord:
        raise NotImplementedError

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        size = self._record_size()
        off = 0
        # Trailing bytes shorter than one record are left behind, exactly as
        # upstream's "while remaining >= recordSize" loop does.
        while len(self.payload) - off >= size:
            self.records.append(self._parse_record(self.payload, off))
            off += size
        return True

    def _write_parsed(self, f: BinaryIO) -> int:
        body = b"".join(record.to_bytes() for record in self.records)
        f.write(body)
        return len(body) + self.header.write(f, len(body))
