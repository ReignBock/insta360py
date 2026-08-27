"""Port of org.insvtools.commands.MetaDumpCommand."""

from __future__ import annotations

from pathlib import Path

from ..dump.dumper import dump
from .base import AbstractCommand


class MetaDumpCommand(AbstractCommand):
    def __init__(self, file_name: str, frame_type: int, out_file_name: str | None):
        super().__init__(file_name)
        self.frame_type = frame_type
        self.out_file_name = out_file_name

    def run(self) -> None:
        metadata = self.read_metadata(self.file_name)
        metadata.parse()

        file_name = Path(self.file_name).name

        if self.frame_type > 0:
            frame = metadata.find_frame(self.frame_type)

            if frame is None:
                raise ValueError(f"Frame type {self.frame_type} not found")

            out_file_name = (
                self.out_file_name or f"{file_name}.frame{self.frame_type}.meta.json"
            )
            dump_object = frame
        else:
            out_file_name = self.out_file_name or f"{file_name}.meta.json"
            dump_object = metadata

        if Path(out_file_name).exists():
            raise ValueError(f"File {out_file_name} already exists")

        self.logger.info(f"Dumping metadata to {out_file_name}")

        Path(out_file_name).write_text(dump(dump_object) + "\n", encoding="utf-8")
