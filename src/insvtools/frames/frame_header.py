"""Port of org.insvtools.frames.FrameHeader."""

from __future__ import annotations

import struct
from typing import BinaryIO

from .frame_type import FrameType

FRAME_HEADER_SIZE = 6

# version (signed byte), type code (signed byte), payload size (int32 LE)
_HEADER = struct.Struct("<bbi")


class FrameHeader:
    """A frame's 6-byte header.

    The header sits *after* its payload in the file, so reading walks
    backwards: ``read`` is given the position one past the end of the header.
    """

    __slots__ = ("frame_type_code", "frame_type", "frame_ver", "frame_size", "frame_pos")

    def __init__(self, frame_type_code: int, frame_ver: int, frame_size: int, frame_pos: int):
        self.frame_type_code = frame_type_code
        self.frame_type = FrameType.from_code(frame_type_code)
        self.frame_ver = frame_ver
        self.frame_size = frame_size
        self.frame_pos = frame_pos

    @classmethod
    def read(cls, f: BinaryIO) -> "FrameHeader":
        """Read the header whose last byte is at the current position - 1."""
        pos = f.tell()
        f.seek(pos - FRAME_HEADER_SIZE)
        frame_ver, frame_type_code, frame_size = _HEADER.unpack(f.read(FRAME_HEADER_SIZE))
        return cls(frame_type_code, frame_ver, frame_size, pos - frame_size - FRAME_HEADER_SIZE)

    def write(self, f: BinaryIO, frame_size: int) -> int:
        """Write the header, returning the number of bytes written.

        RAW frames have no header - their payload is raw filler - so this
        writes nothing and returns 0 for them.
        """
        if self.frame_type is FrameType.RAW:
            return 0

        f.write(_HEADER.pack(self.frame_ver, self.frame_type_code, frame_size))
        return FRAME_HEADER_SIZE

    def __repr__(self) -> str:
        name = self.frame_type.name if self.frame_type is not None else f"<{self.frame_type_code}>"
        ver = f".{self.frame_ver}" if self.frame_ver else ""
        return f"FrameHeader {{{name}{ver}, size={self.frame_size}, pos={self.frame_pos}}}"
