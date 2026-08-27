"""Injecting markers into an Insta360 Studio project as keyframes.

A Studio project (``footage_project.insprj``) is JSON. Its clip carries a
``key_frame_track.node_list`` alternating two kinds of node: ``node_type`` 0 is
a keyframe, ``node_type`` 1 is the transition between the two keyframes around
it. Adding a keyframe therefore means rebuilding the whole list so every
consecutive pair has a transition between them again.

Locating the project is Windows-only - the paths below exist nowhere else -
but everything that edits the JSON is plain data handling and runs anywhere,
which is what the tests exercise.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

PROJECT_FILE_NAME = "footage_project.insprj"
STARTUP_INI = Path("Insta360") / "Insta360 Studio" / "startup.ini"
DEFAULT_PROJECTS_DIR = Path("Insta360") / "Studio" / "FootageProject"

_LOCATION_PATTERN = re.compile(r"^\s*footage_project_location\s*=\s*(.+)$")

# Studio's own defaults, used only when the clip has no camera transform to
# take them from.
DEFAULT_FPS = 29.97002997
DEFAULT_DISTANCE = 0.949999988079071
DEFAULT_FOV = 1.3952149152755737

KEYFRAME_NODE = 0
TRANSITION_NODE = 1

# The values a generated keyframe inherits from the keyframes around it.
INTERPOLATED = ("pan", "tilt", "roll", "fov", "distance")


class StudioError(Exception):
    """Studio's project could not be located or is not what we expect."""


def _name_factory() -> str:
    return str(uuid.uuid4()).lower()


def find_projects_dir(local_app_data: Path | None = None,
                      documents: Path | None = None) -> Path:
    """Where Studio keeps its footage projects.

    Studio records the location in startup.ini, which the user can change; the
    Documents path is only the default.
    """
    if local_app_data is None:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    if documents is None:
        documents = Path.home() / "Documents"

    configured = _configured_projects_dir(local_app_data / STARTUP_INI)

    if configured is not None:
        return configured

    return documents / DEFAULT_PROJECTS_DIR


def _configured_projects_dir(startup_ini: Path) -> Path | None:
    """The footage_project_location from startup.ini, if it is usable."""
    if not startup_ini.is_file():
        return None

    for line in startup_ini.read_text(encoding="utf-8", errors="replace").splitlines():
        matched = _LOCATION_PATTERN.match(line)

        if matched is None:
            continue

        # Studio writes forward slashes even on Windows.
        candidate = Path(matched.group(1).strip().replace("\\", "/"))

        return candidate if candidate.is_dir() else None

    return None


def find_project_for_session(projects_dir: Path, session_id: str) -> Path:
    """The project file that mentions this recording session.

    Raises:
        StudioError: if the directory, or a project referring to the session,
            is missing - which is the normal state until the clip has been
            opened in Studio at least once.
    """
    if not projects_dir.is_dir():
        raise StudioError(f"Studio projects directory not found at: {projects_dir}")

    projects = sorted(projects_dir.rglob(PROJECT_FILE_NAME))

    if not projects:
        raise StudioError("No Studio project files found in directory.")

    for project in projects:
        text = project.read_text(encoding="utf-8", errors="replace")

        if session_id in text:
            return project

    raise StudioError("Project not found in Studio. (Open clip in Insta360 Studio first).")


def _lerp(at: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Straight-line interpolation, collapsing to ``y0`` for a zero interval."""
    if x1 == x0:
        return float(y0)

    factor = (float(at) - float(x0)) / (float(x1) - float(x0))

    return float(y0) + factor * (float(y1) - float(y0))


def _camera_defaults(clip: dict[str, Any]) -> tuple[float, float]:
    """The clip's own framing, falling back to Studio's defaults."""
    transform = clip.get("camera_transform") or {}
    distance = transform.get("distance")
    fov = (transform.get("fov") or {}).get("value")

    return (
        float(distance) if distance is not None else DEFAULT_DISTANCE,
        float(fov) if fov is not None else DEFAULT_FOV,
    )


def _framing_at(frame: int, existing: list[dict[str, Any]]) -> dict[str, float] | None:
    """The pan/tilt/roll/fov/distance a new keyframe at ``frame`` should take.

    Between two manual keyframes the values are interpolated; outside them the
    nearest one is copied, so a marker never yanks the camera somewhere the
    user did not put it. None means there is nothing to copy from.
    """
    if not existing:
        return None

    if len(existing) == 1:
        return {key: float(existing[0][key]) for key in INTERPOLATED}

    before = [node for node in existing if node["time"] < frame]
    after = [node for node in existing if node["time"] > frame]

    if before and after:
        left, right = before[-1], after[0]
        return {
            key: _lerp(frame, left["time"], right["time"], left[key], right[key])
            for key in INTERPOLATED
        }

    nearest = before[-1] if before else after[0] if after else None

    if nearest is None:
        return None

    return {key: float(nearest[key]) for key in INTERPOLATED}


def keyframe_nodes(
    clip: dict[str, Any],
    marker_seconds: Iterable[float],
    name_factory: Callable[[], str] = _name_factory,
) -> list[dict[str, Any]]:
    """The clip's keyframes plus one per marker, in time order.

    Markers are matched to the framing of the *user's* keyframes only, so
    adding one marker never influences the next.
    """
    fps = _clip_fps(clip)
    track = clip.get("key_frame_track") or {}
    existing = sorted(
        (node for node in track.get("node_list") or [] if node.get("node_type") == KEYFRAME_NODE),
        key=lambda node: node["time"],
    )

    default_distance, default_fov = _camera_defaults(clip)
    keyframes = list(existing)
    taken = {node["time"] for node in existing}

    for seconds in marker_seconds:
        frame = round(seconds * fps)

        if frame in taken:
            logger.debug("Marker at %ss already has a keyframe at frame %d", seconds, frame)
            continue

        taken.add(frame)
        node: dict[str, Any] = {
            "auto_fov": 0,
            "distance": default_distance,
            "fov": default_fov,
            "is_headtrack": 0,
            "name": name_factory(),
            "node_type": KEYFRAME_NODE,
            "pan": 0,
            "roll": 0,
            "src_time": frame,
            "state": 7,
            "tilt": 0,
            "time": frame,
        }
        node.update(_framing_at(frame, existing) or {})
        keyframes.append(node)

    return sorted(keyframes, key=lambda node: node["time"])


def _clip_fps(clip: dict[str, Any]) -> float:
    fps = clip.get("fps")

    return float(fps) if fps and float(fps) > 0 else DEFAULT_FPS


def interleave_transitions(keyframes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put a transition node between every consecutive pair of keyframes."""
    nodes: list[dict[str, Any]] = []

    for index, keyframe in enumerate(keyframes):
        if index:
            previous = keyframes[index - 1]
            nodes.append(
                {
                    "name": f"{previous['name']}-{keyframe['name']}",
                    "node_type": TRANSITION_NODE,
                    "point1X": 0.5,
                    "point1Y": 0.5,
                    "point2X": 0.5,
                    "point2Y": 0.5,
                    "type": 1,
                }
            )

        nodes.append(keyframe)

    return nodes


def add_markers_to_project(
    project: dict[str, Any],
    marker_seconds: Iterable[float],
    name_factory: Callable[[], str] = _name_factory,
) -> int:
    """Rewrite the project's keyframe track in place. Returns keyframes added.

    Raises:
        StudioError: if the project has no clip to add keyframes to.
    """
    projects = project.get("projects") or []

    if not projects or not projects[0].get("clip"):
        raise StudioError("Corrupted or invalid project structure.")

    clip = projects[0]["clip"]
    before = len(
        [
            node
            for node in (clip.get("key_frame_track") or {}).get("node_list") or []
            if node.get("node_type") == KEYFRAME_NODE
        ]
    )

    keyframes = keyframe_nodes(clip, marker_seconds, name_factory)

    clip["enable_user_keyframe"] = True
    clip.setdefault("key_frame_track", {})["node_list"] = interleave_transitions(keyframes)

    return len(keyframes) - before


def inject_keyframes(
    project_path: Path,
    marker_seconds: Iterable[float],
    name_factory: Callable[[], str] = _name_factory,
) -> int:
    """Add markers to a project file, backing it up first.

    Studio must not be running: it holds the project in memory and would write
    it back out over these changes on exit.
    """
    project = json.loads(project_path.read_text(encoding="utf-8-sig"))
    added = add_markers_to_project(project, marker_seconds, name_factory)

    shutil.copyfile(project_path, project_path.with_suffix(project_path.suffix + ".bak"))
    project_path.write_text(
        json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return added
