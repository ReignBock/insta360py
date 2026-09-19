"""Scanning paths for markers, shared by the command line and the window.

Nothing here prints or draws. The command line and the GUI each present a
:class:`SessionResult` their own way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .extractor import (
    Sequence,
    find_sessions,
    format_timestamp,
    sequence_for,
    session_markers,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionResult:
    """What reading one recording session produced.

    ``error`` is set when the session could not be read, and then ``markers``
    is empty. A session with no error and no markers simply has none.
    """

    sequence: Sequence
    markers: tuple[float, ...]
    error: str | None = None

    @property
    def title(self) -> str:
        """The session's name as the camera wrote it."""
        return f"{self.sequence.prefix}_{self.sequence.session_id}"


def scan(files: list[Path]) -> list[SessionResult]:
    """Read the markers of every session the video files belong to.

    Pass the output of :func:`insvmarkers.extractor.expand_paths`. Sessions come
    back in the order their files were found.
    """
    results: list[SessionResult] = []

    for session_id, directory in find_sessions(files).items():
        sequence = sequence_for(session_id, directory)

        if sequence is None:
            logger.debug("No sequence files for session %s", session_id)
            continue

        try:
            markers = tuple(session_markers(sequence))
        except ValueError as error:
            results.append(SessionResult(sequence, (), str(error)))
            continue

        results.append(SessionResult(sequence, markers))

    return results


def report_lines(result: SessionResult) -> list[str]:
    """The text report for one session, with the raw seconds beside each time.

    The console keeps upstream's HH:MM:SS; a file to check times against is
    more use with the position it came from, since the display truncates.
    """
    lines = [
        f"Sequence: {result.title} ({len(result.sequence.files)} files)",
        "-" * 40,
    ]
    lines += [
        f"Marker {index:02d} : {format_timestamp(seconds)}   {seconds:10.2f}s"
        for index, seconds in enumerate(result.markers, start=1)
    ]
    lines.append("")

    return lines
