"""Port of org.insvtools.commands.MetaComposeCommand."""

from __future__ import annotations

import re
from pathlib import Path

from ..frames.frame import Frame
from ..frames.frame_header import FrameHeader
from ..frames.frame_type import FrameType
from ..header import InsvHeader
from ..metadata import InsvMetadata
from .base import AbstractCommand

_TYPE_EXTRACTOR = re.compile(r".*type(\d+)(_(\d+))?\.meta$")


class MetaComposeCommand(AbstractCommand):
    """Rebuild a trailer from the per-frame files decompose-meta produced.

    Frame order comes from sorting the file names, which is why the ``%02d``
    index in those names matters.
    """

    def run(self) -> None:
        frame_file_prefix = f"{Path(self.file_name).name}.frame"

        self.logger.debug(
            f"Looking for files with prefix '{frame_file_prefix}' in the current directory"
        )

        files = sorted(
            (p for p in Path(".").iterdir() if p.name.startswith(frame_file_prefix)),
            key=lambda p: p.name,
        )

        self.logger.debug(f"Found {len(files)} files")

        if not files:
            raise ValueError("Frame files not found")

        frames: list[Frame] = []

        for frame_file in files:
            payload = frame_file.read_bytes()

            if "typeRaw.meta" in frame_file.name:
                self.logger.info(f"Adding raw frame from {frame_file.name} to {self.file_name}")
                frames.append(
                    Frame.create(FrameHeader(FrameType.RAW.value, 0, len(payload), 0), payload)
                )
                continue

            matcher = _TYPE_EXTRACTOR.match(frame_file.name)

            if matcher is None:
                raise ValueError(f"Wrong frame file name {frame_file.name}")

            type_code = int(matcher.group(1))
            version = int(matcher.group(3) or 0)

            self.logger.info(
                f"Adding frame (type={type_code},ver={matcher.group(3)}) "
                f"from {frame_file.name} to {self.file_name}"
            )

            frames.append(
                Frame.create(FrameHeader(type_code, version, len(payload), 0), payload)
            )

        metadata = InsvMetadata(InsvHeader.dummy(), frames)

        self.replace_meta(self.file_name, metadata)
