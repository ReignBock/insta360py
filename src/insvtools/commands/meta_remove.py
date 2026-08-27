"""Port of org.insvtools.commands.MetaRemoveCommand."""

from __future__ import annotations

from ..header import InsvHeader
from .base import AbstractCommand


class MetaRemoveCommand(AbstractCommand):
    def run(self) -> None:
        with open(self.file_name, "r+b") as f:
            header = InsvHeader.read(f)

            if header is None:
                raise ValueError("Metadata not found")

            self.logger.info(f"Removing metadata from {self.file_name}")

            f.truncate(header.metadata_pos)
