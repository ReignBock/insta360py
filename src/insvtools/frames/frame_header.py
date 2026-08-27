"""The 6-byte header that follows each metadata frame's payload."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

from .frame_type import FrameType

FRAME_HEADER_SIZE = 6

# version (signed byte), type code (signed byte), payload size (int32 LE)
_HEADER = struct.Struct("<bbi")


@dataclass
class FrameHeader:
    """Where a frame lives and what it claims to be.

    The header sits *after* its payload in the file, so reading walks
    backwards: :meth:`read` is given the position one past the end of the
    header.
    """

    frame_type_code: int
    frame_ver: int
    frame_size: int
    frame_pos: int

    @property
    def frame_type(self) -> FrameType | None:
        """The known type, or None for a code we don't recognise."""
        return FrameType.from_code(self.frame_type_code)

    @classmethod
    def read(cls, f: BinaryIO) -> "FrameHeader":
        """Read the header whose last byte is just before the current position."""
        pos = f.tell()
        f.seek(pos - FRAME_HEADER_SIZE)
        frame_ver, frame_type_code, frame_size = _HEADER.unpack(f.read(FRAME_HEADER_SIZE))
        return cls(frame_type_code, frame_ver, frame_size, pos - frame_size - FRAME_HEADER_SIZE)

    def write(self, f: BinaryIO, frame_size: int) -> int:
        """Write the header, returning the bytes written.

        RAW frames are raw filler with no header, so this writes nothing for
        them.
        """
        if self.frame_type is FrameType.RAW:
            return 0

        f.write(_HEADER.pack(self.frame_ver, self.frame_type_code, frame_size))
        return FRAME_HEADER_SIZE
