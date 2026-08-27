"""Port of org.insvtools.commands.MetaDecomposeCommand."""

from __future__ import annotations

from pathlib import Path

from ..frames.frame_type import FrameType
from .base import AbstractCommand


class MetaDecomposeCommand(AbstractCommand):
    """Write one file per frame.

    The naming is a contract with compose-meta, which reads the files back
    sorted by name: ``{file}.frame{NN:02d}.type{code}[_{ver}].meta``, with RAW
    frames using ``typeRaw``.
    """

    def __init__(self, file_name: str, frame_type: int):
        super().__init__(file_name)
        self.frame_type = frame_type

    def run(self) -> None:
        metadata = self.read_metadata(self.file_name)

        file_name = Path(self.file_name).name

        for i, frame in enumerate(metadata.frames):
            if self.frame_type > 0 and frame.header.frame_type_code != self.frame_type:
                continue

            if frame.header.frame_type is FrameType.RAW:
                type_part = "Raw"
            else:
                type_part = str(frame.header.frame_type_code)
                if frame.header.frame_ver > 0:
                    type_part += f"_{frame.header.frame_ver}"

            frame_file_name = f"{file_name}.frame{i:02d}.type{type_part}.meta"
            frame_file = Path(frame_file_name)

            if frame_file.exists():
                raise ValueError(f"File {frame_file_name} already exists")

            self.logger.info(
                f"Storing frame (typeCode={frame.header.frame_type_code},"
                f"ver={frame.header.frame_ver}) from {file_name} to {frame_file_name}"
            )

            frame_file.write_bytes(frame.payload)
