"""Port of org.insvtools.commands.MetaExtractCommand."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..header import InsvHeader
from .base import AbstractCommand


class MetaExtractCommand(AbstractCommand):
    def __init__(self, file_name: str, meta_file_name: str | None):
        super().__init__(file_name)
        self.meta_file_name = meta_file_name or f"{Path(file_name).name}.meta"

    def run(self) -> None:
        meta_file = Path(self.meta_file_name)

        if meta_file.exists():
            raise ValueError(f"File {self.meta_file_name} already exists")

        with open(self.file_name, "rb") as f:
            header = InsvHeader.read(f)

            if header is None:
                raise ValueError("Metadata not found")

            f.seek(header.metadata_pos)

            self.logger.info(
                f"Extracting metadata from {self.file_name} to {self.meta_file_name}"
            )

            with meta_file.open("wb") as out:
                shutil.copyfileobj(f, out)
