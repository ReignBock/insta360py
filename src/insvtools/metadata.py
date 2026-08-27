"""Port of org.insvtools.InsvMetadata."""

from __future__ import annotations

import os
from typing import BinaryIO, TypeVar

from .frames import factory
from .frames.frame import Frame
from .frames.frame_header import FRAME_HEADER_SIZE, FrameHeader
from .frames.frame_type import FrameType
from .frames.index_frame import IndexFrame
from .frames.info_frame import InfoFrame
from .header import HEADER_SIZE, InsvHeader

_F = TypeVar("_F", bound=Frame)


class InsvMetadata:
    """The metadata trailer: a header plus an ordered list of frames.

    Frames are stored newest-first in the file and each frame's header follows
    its payload, so reading walks backwards from the footer and reverses the
    result at the end.
    """

    def __init__(self, header: InsvHeader, frames: list[Frame]):
        self.header = header
        self.frames = frames

    @classmethod
    def read(cls, f: BinaryIO) -> "InsvMetadata | None":
        """Read metadata from a file, or return None if it has none."""
        header = InsvHeader.read(f)

        if header is None:
            return None

        frames: list[Frame] = []
        metadata = cls(header, frames)

        f.seek(0, 2)
        cur_pos = f.tell() - HEADER_SIZE

        while cur_pos > header.metadata_pos:
            f.seek(cur_pos)
            frame_header = FrameHeader.read(f)
            frame = factory.read(f, frame_header)
            frames.append(frame)

            if isinstance(frame, IndexFrame):
                # An index frame ends the walk: everything below it is located
                # by offset instead.
                frame.parse(metadata)
                frames.extend(cls._read_indexed_frames(f, frame))
                break

            cur_pos = cur_pos - frame_header.frame_size - FRAME_HEADER_SIZE

        if frames:
            last_frame = frames[-1]
            if last_frame.header.frame_pos > header.metadata_pos:
                frames.append(
                    factory.read_raw(f, header.metadata_pos, last_frame.header.frame_pos)
                )

        # Frames were read last-to-first, so put them back in file order.
        frames.reverse()

        return metadata

    @staticmethod
    def _read_indexed_frames(f: BinaryIO, index_frame: IndexFrame) -> list[Frame]:
        """Read the frames an INDEX frame points at, preserving the gaps.

        Anything between two indexed frames is carried through as a RAW frame
        so that writing the trailer back reproduces it byte for byte.
        """
        frames = [
            factory.read(f, frame_header)
            for frame_header in index_frame.frames_index
            if frame_header is not None
        ]
        frames.sort(key=lambda frame: -frame.header.frame_pos)

        result: list[Frame] = []
        prev_pos = index_frame.header.frame_pos

        for frame in frames:
            frame_end_pos = frame.header.frame_pos + frame.header.frame_size + FRAME_HEADER_SIZE

            if frame_end_pos < prev_pos:
                result.append(factory.read_raw(f, frame_end_pos, prev_pos))

            result.append(frame)
            prev_pos = frame.header.frame_pos

        return result

    def parse(self) -> None:
        """Interpret every frame's payload.

        INFO goes first: the gyro frame needs its record size from there.
        """
        info_frame = self.find_frame_of(InfoFrame)

        if info_frame is not None:
            info_frame.parse(self)

        for frame in self.frames:
            if frame is not info_frame:
                frame.parse(self)

    def write(self, f: BinaryIO) -> None:
        """Write every frame followed by the footer."""
        if self.find_frame_of(IndexFrame) is not None:
            self._write_indexed(f)
            return

        size = sum(frame.write(f) for frame in self.frames)

        self.header.write(f, size + HEADER_SIZE)

    def _write_indexed(self, f: BinaryIO) -> None:
        """Write frames, then rebuild the index frame to match where they landed."""
        max_type = max(
            max(frame_type.value for frame_type in FrameType),
            max(frame.header.frame_type_code for frame in self.frames),
        )
        headers: list[FrameHeader | None] = [None] * (max_type + 1)

        index_frame: IndexFrame | None = None
        size = 0
        metadata_pos = f.tell()

        for frame in self.frames:
            header = frame.header

            if isinstance(frame, IndexFrame):
                index_frame = frame
                continue

            pos = f.tell()
            frame_size = frame.write(f)
            size += frame_size

            if header.frame_type is FrameType.RAW:
                continue

            # Offsets in the index are relative to the start of the metadata.
            headers[header.frame_type_code] = FrameHeader(
                header.frame_type_code,
                header.frame_ver,
                frame_size - FRAME_HEADER_SIZE,
                pos - metadata_pos,
            )

        assert index_frame is not None

        index_frame.frames_index[:] = headers
        size += index_frame.write(f)

        self.header.write(f, size + HEADER_SIZE)

    def find_frame(self, frame_type: FrameType | int) -> Frame | None:
        """Find the first frame of a type, by FrameType or by raw type code."""
        if isinstance(frame_type, FrameType):
            return next(
                (f for f in self.frames if f.header.frame_type is frame_type), None
            )
        return next(
            (f for f in self.frames if f.header.frame_type_code == frame_type), None
        )

    def find_frame_of(self, frame_class: type[_F]) -> _F | None:
        """Find the first frame of a class, keeping that class in the type.

        :meth:`find_frame` can only promise the base Frame, so callers that
        want a subclass's fields had to assume the mapping in
        :mod:`insvtools.frames.factory` held. Searching by class states it
        instead. Only frame types the factory maps to a class can be found
        this way; everything else stays a plain Frame and needs
        :meth:`find_frame`.
        """
        return next((f for f in self.frames if isinstance(f, frame_class)), None)


def read_metadata(path: str | os.PathLike[str]) -> InsvMetadata:
    """Read a file's metadata, raising if it has none."""
    metadata = read_metadata_optional(path)

    if metadata is None:
        raise ValueError("Metadata not found")

    return metadata


def read_metadata_optional(path: str | os.PathLike[str]) -> InsvMetadata | None:
    """Read a file's metadata, or None if it is a plain MP4."""
    with open(path, "rb") as f:
        return InsvMetadata.read(f)


def replace_metadata(path: str | os.PathLike[str], metadata: InsvMetadata) -> None:
    """Truncate any existing trailer and append this one."""
    with open(path, "r+b") as f:
        header = InsvHeader.read(f)

        if header is not None:
            f.truncate(header.metadata_pos)

        f.seek(0, 2)
        metadata.write(f)


def strip_metadata(path: str | os.PathLike[str]) -> None:
    """Remove the trailer, leaving a plain MP4."""
    with open(path, "r+b") as f:
        header = InsvHeader.read(f)

        if header is None:
            raise ValueError("Metadata not found")

        f.truncate(header.metadata_pos)
