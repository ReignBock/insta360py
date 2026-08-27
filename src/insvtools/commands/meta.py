"""The metadata commands: dump, decompose, compose, remove, extract, replace.

Each is a plain function - they take arguments, do one thing and raise on
failure. The CLI is the only thing that turns a failure into an exit code.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from ..dump.dumper import dump
from ..frames import factory
from ..frames.frame import Frame
from ..frames.frame_header import FrameHeader
from ..frames.frame_type import FrameType
from ..header import InsvHeader
from ..metadata import (
    InsvMetadata,
    read_metadata,
    replace_metadata,
    strip_metadata,
)

logger = logging.getLogger(__name__)

_TYPE_EXTRACTOR = re.compile(r".*type(\d+)(_(\d+))?\.meta$")


def _refuse_to_overwrite(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"File {path} already exists")


def dump_meta(file_name: str, frame_type: int = 0, out_file: str | None = None) -> None:
    """Write the metadata as JSON."""
    metadata = read_metadata(file_name)
    metadata.parse()

    name = Path(file_name).name

    if frame_type > 0:
        frame = metadata.find_frame(frame_type)

        if frame is None:
            raise ValueError(f"Frame type {frame_type} not found")

        target = Path(out_file or f"{name}.frame{frame_type}.meta.json")
        subject: InsvMetadata | Frame = frame
    else:
        target = Path(out_file or f"{name}.meta.json")
        subject = metadata

    _refuse_to_overwrite(target)

    logger.info("Dumping metadata to %s", target)

    target.write_text(dump(subject) + "\n", encoding="utf-8")


def decompose_meta(file_name: str, frame_type: int = 0) -> None:
    """Write one file per metadata frame.

    The names are a contract with :func:`compose_meta`, which reads them back
    in sorted order: ``{file}.frame{NN:02d}.type{code}[_{ver}].meta``, with RAW
    frames using ``typeRaw``.
    """
    metadata = read_metadata(file_name)
    name = Path(file_name).name

    for index, frame in enumerate(metadata.frames):
        if frame_type > 0 and frame.header.frame_type_code != frame_type:
            continue

        if frame.header.frame_type is FrameType.RAW:
            type_part = "Raw"
        else:
            type_part = str(frame.header.frame_type_code)
            if frame.header.frame_ver > 0:
                type_part += f"_{frame.header.frame_ver}"

        target = Path(f"{name}.frame{index:02d}.type{type_part}.meta")
        _refuse_to_overwrite(target)

        logger.info(
            "Storing frame (typeCode=%d,ver=%d) from %s to %s",
            frame.header.frame_type_code,
            frame.header.frame_ver,
            name,
            target,
        )

        target.write_bytes(frame.payload)


def compose_meta(file_name: str) -> None:
    """Rebuild a trailer from the per-frame files decompose_meta produced."""
    prefix = f"{Path(file_name).name}.frame"

    logger.debug("Looking for files with prefix '%s' in the current directory", prefix)

    # Frame order comes from the sorted names, which is why decompose_meta
    # zero-pads the index.
    files = sorted(
        (p for p in Path(".").iterdir() if p.name.startswith(prefix)),
        key=lambda p: p.name,
    )

    logger.debug("Found %d files", len(files))

    if not files:
        raise FileNotFoundError("Frame files not found")

    frames: list[Frame] = []

    for frame_file in files:
        payload = frame_file.read_bytes()

        if "typeRaw.meta" in frame_file.name:
            logger.info("Adding raw frame from %s to %s", frame_file.name, file_name)
            header = FrameHeader(FrameType.RAW.value, 0, len(payload), 0)
        else:
            matcher = _TYPE_EXTRACTOR.match(frame_file.name)

            if matcher is None:
                raise ValueError(f"Wrong frame file name {frame_file.name}")

            type_code = int(matcher.group(1))
            version = int(matcher.group(3) or 0)

            logger.info(
                "Adding frame (type=%d,ver=%d) from %s to %s",
                type_code,
                version,
                frame_file.name,
                file_name,
            )
            header = FrameHeader(type_code, version, len(payload), 0)

        frames.append(factory.create(header, payload))

    replace_metadata(file_name, InsvMetadata(InsvHeader.dummy(), frames))


def remove_meta(file_name: str) -> None:
    """Strip the trailer, leaving a plain MP4."""
    logger.info("Removing metadata from %s", file_name)
    strip_metadata(file_name)


def extract_meta(file_name: str, meta_file: str | None = None) -> None:
    """Copy the trailer out to its own file."""
    target = Path(meta_file or f"{Path(file_name).name}.meta")
    _refuse_to_overwrite(target)

    with open(file_name, "rb") as f:
        header = InsvHeader.read(f)

        if header is None:
            raise ValueError("Metadata not found")

        f.seek(header.metadata_pos)

        logger.info("Extracting metadata from %s to %s", file_name, target)

        with target.open("wb") as out:
            shutil.copyfileobj(f, out)


def replace_meta(file_name: str, meta_file: str | None = None) -> None:
    """Replace a file's trailer with one from a previously extracted file."""
    source = meta_file or f"{Path(file_name).name}.meta"

    logger.info("Replacing metadata from %s to %s", file_name, source)

    replace_metadata(file_name, read_metadata(source))
