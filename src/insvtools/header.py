"""Port of org.insvtools.InsvHeader."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

SIGNATURE = b"8db42d694ccc418790edff439fe026bf"
HEADER_SIZE = 72

# Newer cameras (X5, fw v1.11) wrap the whole trailer in an MP4 box so the file
# stays a structurally valid MP4 to the end. The box header sits immediately
# before the trailer and covers it exactly: size == metadata_size + 8.
INST_BOX_TYPE = b"inst"
INST_BOX_HEADER_SIZE = 8

# 32 unknown bytes, metadata size, version, 32-byte signature
_HEADER = struct.Struct("<32sii32s")
# MP4 box headers are big-endian, unlike everything else in an .insv.
_BOX_HEADER = struct.Struct(">I4s")


@dataclass
class InsvHeader:
    """The 72-byte footer at the very end of an .insv file.

    Its absence is not an error: a plain MP4 simply has no metadata trailer.
    """

    unknown_buf: bytes
    version: int
    metadata_size: int
    metadata_pos: int
    boxed: bool = False
    """Whether an ``inst`` box wraps the trailer (see INST_BOX_TYPE)."""

    @property
    def container_end(self) -> int:
        """Where the MP4 content stops.

        The trailer is not part of the container, so the MP4 parser must stop
        before it - and before the ``inst`` box header too, when there is one,
        or it would read those 8 bytes as a truncated box.
        """
        if self.boxed:
            return self.metadata_pos - INST_BOX_HEADER_SIZE

        return self.metadata_pos

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

        metadata_pos = length - metadata_size

        return cls(
            unknown_buf,
            version,
            metadata_size,
            metadata_pos,
            _has_inst_box(f, metadata_pos, metadata_size),
        )

    def write(self, f: BinaryIO, size: int) -> None:
        """Write the footer, recording the trailer's total size."""
        f.write(_HEADER.pack(self.unknown_buf, size, self.version, SIGNATURE))


def _has_inst_box(f: BinaryIO, metadata_pos: int, metadata_size: int) -> bool:
    """Whether an ``inst`` box header sits just before the trailer.

    Both the type and the size must match: eight bytes of ordinary padding
    could otherwise be mistaken for a box header.
    """
    if metadata_pos < INST_BOX_HEADER_SIZE:
        return False

    f.seek(metadata_pos - INST_BOX_HEADER_SIZE)
    box_size, box_type = _BOX_HEADER.unpack(f.read(INST_BOX_HEADER_SIZE))

    return box_type == INST_BOX_TYPE and box_size == metadata_size + INST_BOX_HEADER_SIZE


def write_inst_box_header(f: BinaryIO, trailer_size: int) -> None:
    """Write the ``inst`` box header that wraps a trailer of ``trailer_size``."""
    f.write(_BOX_HEADER.pack(trailer_size + INST_BOX_HEADER_SIZE, INST_BOX_TYPE))
