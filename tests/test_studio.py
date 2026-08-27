"""Injecting keyframes into an Insta360 Studio project.

Locating the project is Windows-only, but everything that edits the JSON is
plain data handling, so all of it is exercised here on temporary files.
"""

# pylint: disable=redefined-outer-name,protected-access

import json
from pathlib import Path
from typing import Any

import pytest

from insvmarkers.studio import (
    DEFAULT_DISTANCE,
    DEFAULT_FOV,
    DEFAULT_FPS,
    StudioError,
    add_markers_to_project,
    find_project_for_session,
    find_projects_dir,
    inject_keyframes,
    _framing_at,
    _lerp,
    interleave_transitions,
    keyframe_nodes,
)

SESSION = "20260620_173803"


def _keyframe(time: int, name: str, **values: float) -> dict[str, Any]:
    node = {
        "name": name,
        "node_type": 0,
        "time": time,
        "src_time": time,
        "pan": 0.0,
        "tilt": 0.0,
        "roll": 0.0,
        "fov": 1.0,
        "distance": 0.9,
    }
    node.update(values)
    return node


def _clip(nodes: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    clip: dict[str, Any] = {"fps": 30.0}
    if nodes is not None:
        clip["key_frame_track"] = {"node_list": nodes}
    clip.update(extra)
    return clip


def _names() -> Any:
    """A deterministic stand-in for the uuid generator."""
    counter = iter(f"new-{i}" for i in range(100))
    return lambda: next(counter)


# --- locating the project ---------------------------------------------------


def test_the_configured_project_location_is_used(tmp_path: Path) -> None:
    """Studio records the directory in startup.ini, and the user can change it."""
    projects = tmp_path / "elsewhere"
    projects.mkdir()
    ini = tmp_path / "Insta360" / "Insta360 Studio" / "startup.ini"
    ini.parent.mkdir(parents=True)
    # Studio writes forward slashes even on Windows.
    ini.write_text(f"[General]\nfootage_project_location={projects.as_posix()}\n")

    assert find_projects_dir(tmp_path, tmp_path / "Documents") == projects


def test_a_configured_location_that_no_longer_exists_falls_back(tmp_path: Path) -> None:
    """The directory can be deleted after Studio recorded it."""
    ini = tmp_path / "Insta360" / "Insta360 Studio" / "startup.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("footage_project_location=/gone\n")

    found = find_projects_dir(tmp_path, tmp_path / "Documents")

    assert found == tmp_path / "Documents" / "Insta360" / "Studio" / "FootageProject"


def test_an_ini_without_the_key_falls_back(tmp_path: Path) -> None:
    """startup.ini exists but records no project location."""
    ini = tmp_path / "Insta360" / "Insta360 Studio" / "startup.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[General]\nsomething_else=1\n")

    assert find_projects_dir(tmp_path, tmp_path / "Docs").name == "FootageProject"


def test_no_ini_at_all_falls_back_to_documents(tmp_path: Path) -> None:
    """A fresh install, or Studio never having been run."""
    assert find_projects_dir(tmp_path, tmp_path / "Docs").name == "FootageProject"


def test_the_environment_supplies_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Called with nothing, the Windows locations are read from the environment."""
    monkeypatch.setenv("LOCALAPPDATA", "/nowhere")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/someone")))

    assert find_projects_dir() == Path(
        "/home/someone/Documents/Insta360/Studio/FootageProject"
    )


def _project_file(directory: Path, session: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "footage_project.insprj"
    path.write_text(json.dumps({"projects": [{"clip": {"path": f"VID_{session}_00_029.insv"}}]}))
    return path


def test_the_project_naming_the_session_is_chosen(tmp_path: Path) -> None:
    """Studio keeps one project directory per clip, so several may exist."""
    _project_file(tmp_path / "other", "20200101_000000")
    wanted = _project_file(tmp_path / "wanted", SESSION)

    assert find_project_for_session(tmp_path, SESSION) == wanted


def test_a_missing_projects_directory_is_reported(tmp_path: Path) -> None:
    """Studio has never run, or its directory was moved."""
    with pytest.raises(StudioError, match="directory not found"):
        find_project_for_session(tmp_path / "absent", SESSION)


def test_a_directory_with_no_projects_is_reported(tmp_path: Path) -> None:
    """The directory exists but Studio has opened nothing."""
    with pytest.raises(StudioError, match="No Studio project files found"):
        find_project_for_session(tmp_path, SESSION)


def test_a_session_studio_has_not_opened_is_reported(tmp_path: Path) -> None:
    """Until the clip is opened once, Studio has no project for it."""
    _project_file(tmp_path / "other", "20200101_000000")

    with pytest.raises(StudioError, match="Open clip in Insta360 Studio first"):
        find_project_for_session(tmp_path, SESSION)


# --- building the keyframes -------------------------------------------------


def test_markers_become_keyframes_at_the_matching_frame() -> None:
    """Seconds are converted through the clip's own frame rate."""
    nodes = keyframe_nodes(_clip(), [1.0, 2.0], _names())

    assert [n["time"] for n in nodes] == [30, 60]
    assert [n["src_time"] for n in nodes] == [30, 60]
    assert all(n["node_type"] == 0 and n["state"] == 7 for n in nodes)


def test_a_clip_without_a_frame_rate_uses_studios_default() -> None:
    """29.97002997, which is what Studio assumes."""
    nodes = keyframe_nodes({"fps": 0}, [1.0], _names())

    assert nodes[0]["time"] == round(DEFAULT_FPS)


def test_a_marker_on_an_existing_keyframe_is_left_alone() -> None:
    """The user's own keyframe wins; nothing is duplicated or overwritten."""
    existing = _keyframe(30, "mine", pan=42.0)

    nodes = keyframe_nodes(_clip([existing]), [1.0], _names())

    assert len(nodes) == 1
    assert nodes[0]["name"] == "mine"
    assert nodes[0]["pan"] == 42.0


def test_two_markers_landing_on_one_frame_produce_one_keyframe() -> None:
    """Rounding to the same frame must not create a duplicate."""
    nodes = keyframe_nodes(_clip(), [1.0, 1.001], _names())

    assert [n["time"] for n in nodes] == [30]


def test_without_any_keyframes_the_clips_framing_is_used() -> None:
    """The camera_transform is what Studio is currently showing."""
    clip = _clip(camera_transform={"distance": 0.5, "fov": {"value": 1.1}})

    node = keyframe_nodes(clip, [1.0], _names())[0]

    assert node["distance"] == 0.5
    assert node["fov"] == 1.1
    assert node["pan"] == 0 and node["tilt"] == 0 and node["roll"] == 0


def test_without_a_camera_transform_studios_defaults_are_used() -> None:
    """A clip Studio has not framed yet falls back to its own constants."""
    node = keyframe_nodes(_clip(), [1.0], _names())[0]

    assert node["distance"] == DEFAULT_DISTANCE
    assert node["fov"] == DEFAULT_FOV


def test_a_single_keyframe_is_copied_to_every_marker() -> None:
    """One manual keyframe means the user framed the whole clip that way."""
    existing = _keyframe(0, "mine", pan=10.0, tilt=20.0, roll=30.0, fov=1.2, distance=0.8)

    nodes = keyframe_nodes(_clip([existing]), [1.0], _names())
    added = next(n for n in nodes if n["name"] != "mine")

    assert (added["pan"], added["tilt"], added["roll"]) == (10.0, 20.0, 30.0)
    assert (added["fov"], added["distance"]) == (1.2, 0.8)


def test_a_marker_between_two_keyframes_is_interpolated() -> None:
    """Halfway between them in time means halfway in framing."""
    left = _keyframe(0, "left", pan=0.0, tilt=0.0, roll=0.0, fov=1.0, distance=1.0)
    right = _keyframe(60, "right", pan=10.0, tilt=20.0, roll=-10.0, fov=2.0, distance=2.0)

    nodes = keyframe_nodes(_clip([left, right]), [1.0], _names())
    added = next(n for n in nodes if n["name"].startswith("new-"))

    assert added["time"] == 30
    assert added["pan"] == pytest.approx(5.0)
    assert added["tilt"] == pytest.approx(10.0)
    assert added["roll"] == pytest.approx(-5.0)
    assert added["fov"] == pytest.approx(1.5)
    assert added["distance"] == pytest.approx(1.5)


def test_a_marker_past_the_last_keyframe_clamps_to_it() -> None:
    """Beyond the user's keyframes there is nothing to interpolate towards."""
    left = _keyframe(0, "left", pan=1.0)
    right = _keyframe(30, "right", pan=9.0)

    nodes = keyframe_nodes(_clip([left, right]), [10.0], _names())
    added = next(n for n in nodes if n["name"].startswith("new-"))

    assert added["time"] == 300
    assert added["pan"] == 9.0


def test_a_marker_before_the_first_keyframe_clamps_to_it() -> None:
    """Before the user's keyframes there is nothing to interpolate from."""
    left = _keyframe(60, "left", pan=1.0)
    right = _keyframe(90, "right", pan=9.0)

    nodes = keyframe_nodes(_clip([left, right]), [1.0], _names())
    added = next(n for n in nodes if n["name"].startswith("new-"))

    assert added["time"] == 30
    assert added["pan"] == 1.0


def test_duplicate_keyframe_times_use_the_last_one_before_the_marker() -> None:
    """Two keyframes at one time is degenerate; the later wins, as when sorted."""
    clip = _clip(
        [_keyframe(30, "a", pan=3.0), _keyframe(30, "b", pan=9.0), _keyframe(90, "c", pan=99.0)]
    )

    nodes = keyframe_nodes(clip, [2.0], _names())
    added = next(n for n in nodes if n["name"].startswith("new-"))

    # Interpolated from b at frame 30 to c at frame 90, halfway.
    assert added["pan"] == pytest.approx(54.0)


def test_interpolating_across_a_zero_length_interval_takes_the_left_value() -> None:
    """Unreachable through the keyframe search, which brackets strictly."""
    assert _lerp(5, 10, 10, 1.0, 99.0) == 1.0


def test_keyframes_all_sitting_on_the_marker_give_nothing_to_copy() -> None:
    """Nothing lies either side, so the clip's own framing is left in place.

    keyframe_nodes never asks this - it skips a frame that already has a
    keyframe - but the search itself has to answer for it.
    """
    assert _framing_at(30, [_keyframe(30, "a"), _keyframe(30, "b")]) is None


def test_generated_keyframes_do_not_influence_each_other() -> None:
    """Each marker is placed against the user's keyframes, not the new ones."""
    left = _keyframe(0, "left", pan=0.0)
    right = _keyframe(100, "right", pan=100.0)

    nodes = keyframe_nodes(_clip([left, right]), [1.0, 2.0], _names())
    added = sorted(
        (n for n in nodes if n["name"].startswith("new-")), key=lambda n: n["time"]
    )

    assert [n["pan"] for n in added] == pytest.approx([30.0, 60.0])


def test_keyframes_come_back_in_time_order() -> None:
    """Markers may arrive out of order relative to existing keyframes."""
    existing = _keyframe(45, "mine")

    nodes = keyframe_nodes(_clip([existing]), [2.0, 0.5], _names())

    assert [n["time"] for n in nodes] == [15, 45, 60]


def test_transition_nodes_sit_between_every_pair() -> None:
    """Studio's node list alternates keyframe, transition, keyframe."""
    nodes = interleave_transitions(
        [_keyframe(0, "a"), _keyframe(30, "b"), _keyframe(60, "c")]
    )

    assert [n["node_type"] for n in nodes] == [0, 1, 0, 1, 0]
    assert [n["name"] for n in nodes if n["node_type"] == 1] == ["a-b", "b-c"]
    assert all(n["point1X"] == 0.5 for n in nodes if n["node_type"] == 1)


def test_a_single_keyframe_needs_no_transition() -> None:
    """A transition joins two keyframes; one keyframe joins nothing."""
    assert [n["node_type"] for n in interleave_transitions([_keyframe(0, "a")])] == [0]


# --- writing the project ----------------------------------------------------


def test_adding_markers_enables_user_keyframes() -> None:
    """Studio ignores the track unless this is set."""
    project = {"projects": [{"clip": _clip()}]}

    added = add_markers_to_project(project, [1.0, 2.0], _names())

    clip = project["projects"][0]["clip"]
    assert added == 2
    assert clip["enable_user_keyframe"] is True
    assert len(clip["key_frame_track"]["node_list"]) == 3  # two keyframes, one transition


def test_a_project_with_no_clip_is_rejected() -> None:
    """Better to refuse than to write a project Studio cannot open."""
    with pytest.raises(StudioError, match="Corrupted or invalid"):
        add_markers_to_project({"projects": []}, [1.0], _names())


def test_injecting_backs_the_project_up_first(tmp_path: Path) -> None:
    """The original is kept, because Studio must be able to get back to it."""
    path = tmp_path / "footage_project.insprj"
    original = {"projects": [{"clip": _clip()}]}
    path.write_text(json.dumps(original))

    added = inject_keyframes(path, [1.0], _names())

    backup = tmp_path / "footage_project.insprj.bak"
    assert added == 1
    assert json.loads(backup.read_text()) == original
    assert json.loads(path.read_text())["projects"][0]["clip"]["enable_user_keyframe"]


def test_a_project_saved_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    """The PowerShell version writes one, so its output must round-trip."""
    path = tmp_path / "footage_project.insprj"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"projects": [{"clip": _clip()}]}).encode())

    assert inject_keyframes(path, [1.0], _names()) == 1
