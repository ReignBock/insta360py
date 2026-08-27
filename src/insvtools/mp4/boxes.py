"""Minimal ISO base media file format box handling.

Only enough to walk to the sample tables and put a file back together. Every
box we don't specifically rewrite is copied through byte for byte, which is
what keeps the output looking like what the camera wrote.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO

# Boxes whose payload is just more boxes.
CONTAINERS = frozenset(
    {
        b"moov",
        b"trak",
        b"mdia",
        b"minf",
        b"stbl",
        b"edts",
        b"dinf",
        b"udta",
        b"mvex",
        b"moof",
        b"traf",
    }
)

_U32 = struct.Struct(">I")
_U64 = struct.Struct(">Q")


@dataclass
class Box:
    """A parsed box: where it lives, and its children if it is a container."""

    type: bytes
    offset: int
    size: int
    header_size: int
    children: list["Box"] = field(default_factory=list)

    @property
    def end(self) -> int:
        """One past the last byte of this box."""
        return self.offset + self.size

    @property
    def payload_offset(self) -> int:
        """Where this box's contents start."""
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        """Size of the contents, excluding the header."""
        return self.size - self.header_size

    def find(self, *path: bytes) -> "Box | None":
        """Follow a path of box types, e.g. find(b'mdia', b'minf', b'stbl')."""
        node: Box | None = self
        for want in path:
            if node is None:
                return None
            node = next((c for c in node.children if c.type == want), None)
        return node

    def find_all(self, box_type: bytes) -> list["Box"]:
        """Every direct child of a given type."""
        return [c for c in self.children if c.type == box_type]

    def payload(self, f: BinaryIO) -> bytes:
        """Read this box's contents."""
        f.seek(self.payload_offset)
        return f.read(self.payload_size)

    def raw(self, f: BinaryIO) -> bytes:
        """Read this box whole, header included, for copying verbatim."""
        f.seek(self.offset)
        return f.read(self.size)


def parse_boxes(f: BinaryIO, start: int, end: int) -> list[Box]:
    """Parse the box list in [start, end).

    ``end`` matters: for an .insv it is the start of the metadata trailer, so
    the MP4 parser never sees the proprietary bytes appended after mdat.
    """
    boxes: list[Box] = []
    offset = start

    while offset + 8 <= end:
        f.seek(offset)
        header = f.read(8)
        if len(header) < 8:
            break

        (size,) = _U32.unpack_from(header, 0)
        box_type = header[4:8]
        header_size = 8

        if size == 1:
            (size,) = _U64.unpack(f.read(8))
            header_size = 16
        elif size == 0:
            # "to end of file" - here, to the end of the region we were given.
            size = end - offset

        if size < header_size or offset + size > end:
            raise ValueError(
                f"Malformed box {box_type!r} at {offset}: size {size} runs past {end}"
            )

        box = Box(box_type, offset, size, header_size)

        if box_type in CONTAINERS:
            box.children = parse_boxes(f, box.payload_offset, box.end)

        boxes.append(box)
        offset += size

    return boxes


def box_bytes(box_type: bytes, payload: bytes) -> bytes:
    """Serialize a box, using the 64-bit form only when it is needed."""
    size = len(payload) + 8
    if size <= 0xFFFFFFFF:
        return _U32.pack(size) + box_type + payload
    # Only a payload over 4 GiB gets here, which no test can reasonably build.
    return _U32.pack(1) + box_type + _U64.pack(size + 8) + payload  # pragma: no cover
