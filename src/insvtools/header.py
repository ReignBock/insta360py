"""Port of org.insvtools.InsvHeader."""

from __future__ import annotations

import struct
from typing import BinaryIO

SIGNATURE = b"8db42d694ccc418790edff439fe026bf"
HEADER_SIZE = 72

# 32 unknown bytes, metadata size, version, 32-byte signature
_HEADER = struct.Struct("<32sii32s")


class InsvHeader:
    """The 72-byte footer at the very end of an .insv file.

    Its absence is not an error: a plain MP4 simply has no metadata trailer.
    """

    __slots__ = ("unknown_buf", "version", "metadata_size", "metadata_pos")

    def __init__(self, unknown_buf: bytes, version: int, metadata_size: int, metadata_pos: int):
        self.unknown_buf = unknown_buf
        self.version = version
        self.metadata_size = metadata_size
        self.metadata_pos = metadata_pos

    @classmethod
    def dummy(cls) -> "InsvHeader":
        """A synthetic header, for composing metadata from loose frame files."""
        return cls(bytes(32), 3, 0, -1)

    @classmethod
    def read(cls, f: BinaryIO) -> "InsvHeader | None":
        """Read the footer, or return None if this file has no metadata."""
        f.seek(0, 2)
        length = f.tell()

        if length < HEADER_SIZE:
            return None

        f.seek(length - HEADER_SIZE)
        unknown_buf, metadata_size, version, signature = _HEADER.unpack(f.read(HEADER_SIZE))

        if signature != SIGNATURE:
            return None  # No header.

        if version != 3:
            raise ValueError(f"Unsupported file version {version}")

        return cls(unknown_buf, version, metadata_size, length - metadata_size)

    def write(self, f: BinaryIO, size: int) -> None:
        f.write(_HEADER.pack(self.unknown_buf, size, self.version, SIGNATURE))
