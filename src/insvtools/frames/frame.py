"""The base metadata frame."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from .frame_header import FrameHeader

if TYPE_CHECKING:
    from ..metadata import InsvMetadata


class Frame:
    """A metadata frame: a header plus an opaque payload.

    Subclasses interpret the payload, but only once :meth:`parse` succeeds.
    Until then - and permanently, for frame types we don't understand - the
    original bytes are what gets written back out. That is what makes
    round-tripping a file byte-exact.

    Use :mod:`insvtools.frames.factory` to build one from a file.
    """

    def __init__(self, header: FrameHeader, payload: bytes):
        self.header = header
        self.payload = payload
        self.parsed = False

    def write(self, f: BinaryIO) -> int:
        """Write the frame, returning total bytes written (payload + header)."""
        return self._write_parsed(f) if self.parsed else self._write_payload(f)

    def _write_parsed(self, f: BinaryIO) -> int:
        """Write from the interpreted form. Only called once parsed."""
        return self._write_payload(f)

    def _write_payload(self, f: BinaryIO) -> int:
        f.write(self.payload)
        return len(self.payload) + self.header.write(f, len(self.payload))

    def parse(self, metadata: "InsvMetadata") -> None:
        """Interpret the payload, if this frame type knows how."""
        if not self.parsed:
            self.parsed = self._parse_internal(metadata)

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        """Interpret the payload; return True if it was understood.

        The default leaves the payload opaque, which is how unknown frame
        types survive a round trip.
        """
        # pylint: disable=unused-argument
        return False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(header={self.header!r}, parsed={self.parsed})"
