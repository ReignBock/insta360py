"""Scanning paths for markers, shared by the command line and the window.

Nothing here prints or draws. The command line and the GUI each present a
:class:`SessionResult` their own way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
    ``pending`` marks a session that was found but not read yet; its markers
    are empty until :func:`read_session` replaces it.
    """

    sequence: Sequence
    markers: tuple[float, ...]
    error: str | None = None
    pending: bool = False

    @property
    def title(self) -> str:
        """The session's name as the camera wrote it."""
        return f"{self.sequence.prefix}_{self.sequence.session_id}"


def find_recordings(files: list[Path]) -> list[SessionResult]:
    """List the sessions the video files belong to, without reading any of them.

    Pass the output of :func:`insvmarkers.extractor.expand_paths`. Each result is
    pending. Sessions come back in the order their files were found.
    """
    found: list[SessionResult] = []

    for session_id, directory in find_sessions(files).items():
        sequence = sequence_for(session_id, directory)

        if sequence is None:
            logger.debug("No sequence files for session %s", session_id)
            continue

        found.append(SessionResult(sequence, (), pending=True))

    return found


def read_session(sequence: Sequence) -> SessionResult:
    """Read the markers of one session."""
    try:
        return SessionResult(sequence, tuple(session_markers(sequence)))
    except ValueError as error:
        return SessionResult(sequence, (), str(error))


def scan(files: list[Path]) -> list[SessionResult]:
    """Read the markers of every session the video files belong to."""
    return [read_session(found.sequence) for found in find_recordings(files)]


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


@dataclass
class FolderNode:
    """A folder on the way from a searched folder down to a recording.

    Only folders that lead to at least one recording exist as nodes, so the
    tree shows the route to the footage and nothing else.
    """

    path: Path
    folders: list[FolderNode] = field(default_factory=list)
    sessions: list[SessionResult] = field(default_factory=list)

    @property
    def recording_count(self) -> int:
        """Recordings in this folder and every folder beneath it."""
        return len(self.sessions) + sum(folder.recording_count for folder in self.folders)

    def child(self, name: str) -> FolderNode:
        """The subfolder called ``name``, added the first time it is needed."""
        for folder in self.folders:
            if folder.path.name == name:
                return folder

        folder = FolderNode(self.path / name)
        self.folders.append(folder)
        return folder


def group_by_folder(
    results: list[SessionResult], searched: list[Path]
) -> tuple[list[FolderNode], list[SessionResult]]:
    """Arrange recordings under the folders that were searched.

    Returns the searched folders that hold recordings, each with the folders
    between it and the footage, and the recordings that lie under none of
    them (files that were added one by one). A recording under several
    searched folders goes under the closest.
    """
    given = list(dict.fromkeys(folder.absolute() for folder in searched))
    closest_first = sorted(given, key=lambda folder: len(folder.parts), reverse=True)
    roots: dict[Path, FolderNode] = {}
    loose: list[SessionResult] = []

    for result in results:
        directory = result.sequence.files[0].parent.absolute()
        root = next((folder for folder in closest_first if folder in (directory, *directory.parents)), None)

        if root is None:
            loose.append(result)
            continue

        node = roots.setdefault(root, FolderNode(root))
        for name in directory.relative_to(root).parts:
            node = node.child(name)
        node.sessions.append(result)

    return [roots[folder] for folder in given if folder in roots], loose
