"""Port of org.insvtools.commands.AbstractCommand and Command."""

from __future__ import annotations

from pathlib import Path

from ..header import InsvHeader
from ..logger import get_logger
from ..metadata import InsvMetadata


class Command:
    def run(self) -> None:
        raise NotImplementedError


class AbstractCommand(Command):
    def __init__(self, file_name: str):
        self.file_name = file_name
        self.logger = get_logger(type(self).__name__)

    @staticmethod
    def read_metadata_optional(file_name: str | Path) -> InsvMetadata | None:
        with open(file_name, "rb") as f:
            return InsvMetadata.read(f)

    @staticmethod
    def read_metadata(file_name: str | Path) -> InsvMetadata:
        metadata = AbstractCommand.read_metadata_optional(file_name)

        if metadata is None:
            raise ValueError("Metadata not found")

        return metadata

    @staticmethod
    def replace_meta(file_name: str | Path, metadata: InsvMetadata) -> None:
        """Truncate any existing trailer and append this one."""
        with open(file_name, "r+b") as f:
            header = InsvHeader.read(f)

            if header is not None:
                f.truncate(header.metadata_pos)

            f.seek(0, 2)
            metadata.write(f)
