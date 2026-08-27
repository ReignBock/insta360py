"""Port of org.insvtools.commands.MetaReplaceCommand."""

from __future__ import annotations

from pathlib import Path

from .base import AbstractCommand


class MetaReplaceCommand(AbstractCommand):
    def __init__(self, file_name: str, meta_file_name: str | None):
        super().__init__(file_name)
        self.meta_file_name = meta_file_name or f"{Path(file_name).name}.meta"

    def run(self) -> None:
        metadata = self.read_metadata(self.meta_file_name)

        self.logger.info(f"Replacing metadata from {self.file_name} to {self.meta_file_name}")

        self.replace_meta(self.file_name, metadata)
