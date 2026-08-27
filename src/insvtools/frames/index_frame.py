"""Port of org.insvtools.frames.IndexFrame."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, BinaryIO

from .frame import Frame
from .frame_header import FrameHeader

if TYPE_CHECKING:
    from ..metadata import InsvMetadata

INDEX_ENTRY_SIZE = 1 + 1 + 4 + 4

# type, version, size, offset (offset is relative to the metadata start)
_ENTRY = struct.Struct("<bbii")
_EMPTY_ENTRY = bytes(INDEX_ENTRY_SIZE)


class IndexFrame(Frame):
    """The INDEX frame (type 0): a directory of the other frames.

    When present it replaces the backwards walk - remaining frames are found
    by offset instead. An all-zero entry means that frame type is absent.
    """

    def __init__(self, header, payload: bytes):
        super().__init__(header, payload)
        self.frames_index: list[FrameHeader | None] = []

    def _parse_internal(self, metadata: "InsvMetadata") -> bool:
        if len(self.payload) % INDEX_ENTRY_SIZE != 0:
            raise ValueError(f"Unexpected INDEX frame size: {len(self.payload)}")

        for off in range(0, len(self.payload), INDEX_ENTRY_SIZE):
            type_code, version, size, offset = _ENTRY.unpack_from(self.payload, off)

            if type_code != 0 or version != 0 or size != 0:
                self.frames_index.append(
                    FrameHeader(type_code, version, size, metadata.header.metadata_pos + offset)
                )
            else:
                self.frames_index.append(None)

        return True

    def write(self, f: BinaryIO) -> int:
        body = bytearray()
        for header in self.frames_index:
            if header is None:
                body += _EMPTY_ENTRY
            else:
                body += _ENTRY.pack(
                    header.frame_type_code,
                    header.frame_ver,
                    header.frame_size,
                    header.frame_pos,
                )

        f.write(bytes(body))
        return len(body) + self.header.write(f, len(body))
