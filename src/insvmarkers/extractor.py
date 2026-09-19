"""Finding recording sessions and the markers in them.

Nothing here is Windows-specific; the Studio half lives in
:mod:`insvmarkers.studio`.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from insvtools.frames.anchors_frame import marker_seconds
from insvtools.frames.frame_type import FrameType
from insvtools.frames.info_frame import InfoFrame
from insvtools.metadata import read_metadata_optional

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = (".insv", ".lrv")

# One recording session, shared by every chapter and both lenses. This is a
# looser key than insvtools' own grouping, which also keys on the prefix and
# the trailing number - deliberately so: the markers of every chapter belong
# to one timeline.
SESSION_PATTERN = re.compile(r"(\d{8}_\d{6})")

# Markers are compared and reported to this many decimal places, which is what
# collapses the same marker seen through several files of one session.
MARKER_PRECISION = 2


@dataclass(frozen=True)
class Sequence:
    """The files of one recording session, in timeline order."""

    session_id: str
    prefix: str
    files: tuple[Path, ...]


def videos_below(folder: Path) -> list[Path]:
    """Every video file in a folder and all the folders beneath it.

    Hidden folders and files (a leading dot) are skipped. On a Mac drive those
    are the trash, Spotlight's index and the ``._`` copies of each file, none
    of which is footage. Order is depth first with names sorted, so a repeated
    search of the same folder lists files the same way.
    """
    found: list[Path] = []

    for directory, subdirectories, names in os.walk(folder):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
        found.extend(
            Path(directory, name)
            for name in sorted(names)
            if not name.startswith(".") and Path(name).suffix.lower() in VIDEO_SUFFIXES
        )

    return found


def expand_paths(paths: list[Path], recursive: bool = False) -> list[Path]:
    """Resolve the arguments to video files.

    A folder contributes the video files directly inside it, or with
    ``recursive`` every video file beneath it.
    """
    found: list[Path] = []

    for path in paths:
        if path.is_dir() and recursive:
            found.extend(videos_below(path))
        elif path.is_dir():
            found.extend(
                sorted(
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in VIDEO_SUFFIXES
                )
            )
        elif path.is_file():
            found.append(path)
        else:
            logger.warning("Skipping %s: not a file or directory", path)

    return found


def find_sessions(paths: list[Path]) -> dict[str, Path]:
    """Map each session id in ``paths`` to the directory it was found in.

    A session is identified by the ``yyyyMMdd_HHmmss`` stamp in the file name.
    The first directory a session is seen in wins, which is where its other
    chapters are then looked for.
    """
    sessions: dict[str, Path] = {}

    for path in paths:
        matched = SESSION_PATTERN.search(path.name)

        if matched is None:
            logger.debug("No session id in %s", path.name)
            continue

        sessions.setdefault(matched.group(1), path.parent or Path("."))

    return sessions


def sequence_for(session_id: str, directory: Path) -> Sequence | None:
    """Every file of one session, preferring the full-resolution originals.

    The proxies are only consulted when no .insv is present: both carry the
    same markers, so reading both would just double them up.
    """
    for prefix, suffix in (("VID", ".insv"), ("LRV", ".lrv")):
        files = sorted(directory.glob(f"{prefix}_{session_id}*{suffix}"))

        if files:
            return Sequence(session_id, prefix, tuple(files))

    return None


def first_frame_timestamp(path: Path) -> int | None:
    """The session clock reading at the first frame, or None if unreadable.

    This is the origin every marker in the session is measured from. It comes
    from the *first* file, and the camera's clock keeps running across
    chapters, so later chapters' markers land at their true session offset
    without any per-file adjustment.
    """
    metadata = read_metadata_optional(path)

    if metadata is None:
        logger.debug("%s has no metadata trailer", path.name)
        return None

    info = metadata.find_frame_of(InfoFrame)

    if info is None:
        logger.debug("%s has no INFO frame", path.name)
        return None

    info.parse(metadata)

    if info.extra_metadata is None:  # pragma: no cover
        # InfoFrame either parses or raises, so this cannot happen today; the
        # field is optional and the guard is what keeps that honest.
        return None

    return info.extra_metadata.FirstFrameTimestamp


def markers_in(path: Path, base_timestamp: int) -> list[float]:
    """Marker positions in one file, in seconds from the session start."""
    metadata = read_metadata_optional(path)

    if metadata is None:
        return []

    anchors = metadata.find_frame(FrameType.ANCHORS)

    if anchors is None:
        logger.debug("%s has no ANCHORS frame", path.name)
        return []

    return marker_seconds(anchors.payload, base_timestamp)


def session_markers(sequence: Sequence) -> list[float]:
    """Every distinct marker of a session, in seconds, in order.

    Raises:
        ValueError: if the first file has no readable timestamp to measure from.
    """
    base = first_frame_timestamp(sequence.files[0])

    if base is None:
        raise ValueError(f"Base timestamp extraction failed for {sequence.files[0].name}")

    seconds = [
        second for path in sequence.files for second in markers_in(path, base)
    ]

    return sorted({round(second, MARKER_PRECISION) for second in seconds})


def format_timestamp(seconds: float) -> str:
    """Render a marker position as ``HH:MM:SS``, dropping the fraction."""
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
