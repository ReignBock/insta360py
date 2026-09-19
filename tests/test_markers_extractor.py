"""Finding sessions and reading their markers."""

# pylint: disable=redefined-outer-name

import shutil
from pathlib import Path

import pytest

from insvtools.frames.frame_type import FrameType
from insvtools.metadata import read_metadata, replace_metadata

from insvmarkers.extractor import (
    Sequence,
    expand_paths,
    find_sessions,
    first_frame_timestamp,
    format_timestamp,
    markers_in,
    sequence_for,
    session_markers,
)

# The fixture's own markers, in seconds from the start of the session.
MARKERS = [292.6, 1093.76, 1756.38]


def test_a_directory_expands_to_the_video_files_inside_it(session_dir: Path) -> None:
    """Only .insv and .lrv are picked up; anything else is left alone."""
    (session_dir / "notes.txt").write_text("ignore me")
    (session_dir / "LRV_20260620_173803_01_029.lrv").write_bytes(b"")

    found = expand_paths([session_dir])

    assert {p.suffix for p in found} == {".insv", ".lrv"}
    assert len(found) == 3


def test_a_named_file_is_taken_as_given(session_dir: Path) -> None:
    """A file argument is used whether or not it looks like a video."""
    target = session_dir / "VID_20260620_173803_00_029.insv"

    assert expand_paths([target]) == [target]


def test_a_path_that_does_not_exist_is_skipped(tmp_path: Path) -> None:
    """A dropped file that has since moved should not stop the run."""
    assert not expand_paths([tmp_path / "gone.insv"])


def test_sessions_are_keyed_by_the_recording_stamp(session_dir: Path) -> None:
    """Every chapter and lens of one recording shares a session id."""
    sessions = find_sessions(expand_paths([session_dir]))

    assert sessions == {"20260620_173803": session_dir}


def test_files_without_a_stamp_have_no_session(tmp_path: Path) -> None:
    """sample.insv and friends are simply not part of a session."""
    (tmp_path / "sample.insv").write_bytes(b"")

    assert not find_sessions([tmp_path / "sample.insv"])


def test_the_first_directory_a_session_appears_in_wins(tmp_path: Path) -> None:
    """The session's other chapters are looked for beside the first file seen."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    name = "VID_20260620_173803_00_029.insv"
    (first / name).write_bytes(b"")
    (second / name).write_bytes(b"")

    assert find_sessions([first / name, second / name]) == {"20260620_173803": first}


def test_the_full_resolution_files_are_preferred(session_dir: Path) -> None:
    """Proxies carry the same markers, so reading both would double them."""
    shutil.copy(
        session_dir / "VID_20260620_173803_00_029.insv",
        session_dir / "LRV_20260620_173803_01_029.lrv",
    )

    sequence = sequence_for("20260620_173803", session_dir)

    assert sequence is not None
    assert sequence.prefix == "VID"
    assert all(p.suffix == ".insv" for p in sequence.files)


def test_proxies_are_used_when_no_original_is_present(tmp_path: Path) -> None:
    """A card that only has LRVs still yields markers."""
    (tmp_path / "LRV_20260620_173803_01_029.lrv").write_bytes(b"")

    sequence = sequence_for("20260620_173803", tmp_path)

    assert sequence is not None
    assert sequence.prefix == "LRV"


def test_a_session_with_no_files_has_no_sequence(tmp_path: Path) -> None:
    """The directory the session was seen in no longer holds it."""
    assert sequence_for("20260620_173803", tmp_path) is None


def test_the_base_timestamp_comes_from_the_info_frame(x5_insv: Path) -> None:
    """It is the clock reading at the first frame, not a wall-clock time."""
    assert first_frame_timestamp(x5_insv) == 6722816692


def test_a_plain_mp4_has_no_base_timestamp(tmp_path: Path) -> None:
    """Without a trailer there is nothing to measure markers against."""
    path = tmp_path / "plain.mp4"
    path.write_bytes(b"\x00" * 200)

    assert first_frame_timestamp(path) is None


def test_markers_are_measured_from_the_session_start(x5_insv: Path) -> None:
    """Each file's markers are offsets into the whole session, not the file."""
    base = first_frame_timestamp(x5_insv)
    assert base is not None

    assert markers_in(x5_insv, base) == pytest.approx([292.597074, 1093.755729, 1756.382436])


def test_a_plain_mp4_contributes_no_markers(tmp_path: Path) -> None:
    """No trailer means no ANCHORS frame to read."""
    path = tmp_path / "plain.mp4"
    path.write_bytes(b"\x00" * 200)

    assert markers_in(path, 0) == []


def test_a_session_reports_each_marker_once(session_dir: Path) -> None:
    """Both chapters here carry the same markers; the session lists them once."""
    sequence = sequence_for("20260620_173803", session_dir)
    assert sequence is not None

    assert len(sequence.files) == 2
    assert session_markers(sequence) == MARKERS


def test_a_session_whose_first_file_is_unreadable_is_an_error(tmp_path: Path) -> None:
    """Without the base timestamp every marker would be meaningless."""
    path = tmp_path / "VID_20260620_173803_00_029.insv"
    path.write_bytes(b"\x00" * 200)

    with pytest.raises(ValueError, match="Base timestamp extraction failed"):
        session_markers(Sequence("20260620_173803", "VID", (path,)))


def test_a_session_with_an_empty_anchors_frame_has_no_markers(
    unmarked_session: Path,
) -> None:
    """The ONE R sample's ANCHORS frame is seven empty sections."""
    sequence = sequence_for("20221218_231825", unmarked_session)
    assert sequence is not None

    assert session_markers(sequence) == []


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "00:00:00"),
        (292.6, "00:04:52"),
        (1756.38, "00:29:16"),
        (3661.0, "01:01:01"),
        (59.999, "00:00:59"),
    ],
)
def test_markers_are_reported_as_hours_minutes_seconds(
    seconds: float, expected: str
) -> None:
    """The fraction is dropped rather than rounded, as upstream does."""
    assert format_timestamp(seconds) == expected


def _trailer_without(source: Path, target: Path, frame_type: FrameType) -> Path:
    """A copy of ``source`` with every frame of one type removed."""
    shutil.copy(source, target)
    metadata = read_metadata(target)
    metadata.frames = [
        frame for frame in metadata.frames if frame.header.frame_type is not frame_type
    ]
    replace_metadata(target, metadata)
    return target


def test_a_trailer_without_an_info_frame_has_no_base_timestamp(
    sample_insv: Path, tmp_path: Path
) -> None:
    """There is a trailer, but nothing in it says when the clip started."""
    path = _trailer_without(sample_insv, tmp_path / "no_info.insv", FrameType.INFO)

    assert first_frame_timestamp(path) is None


def test_a_trailer_without_an_anchors_frame_contributes_no_markers(
    sample_insv: Path, tmp_path: Path
) -> None:
    """Older firmware may not write the frame at all."""
    path = _trailer_without(sample_insv, tmp_path / "no_anchors.insv", FrameType.ANCHORS)

    assert markers_in(path, 0) == []


def test_a_recursive_search_finds_footage_at_any_depth(nested_footage: Path) -> None:
    """Both recordings turn up, however many folders down they sit."""
    found = expand_paths([nested_footage], recursive=True)

    assert [path.name for path in found] == [
        "VID_20260620_173803_00_029.insv",
        "VID_20260621_090000_00_029.insv",
    ]


def test_a_recursive_search_skips_hidden_folders_and_files(nested_footage: Path) -> None:
    """The trash folder and the ``._`` copies are not footage."""
    found = expand_paths([nested_footage], recursive=True)

    assert not [path for path in found if path.name.startswith(".")]
    assert not [path for path in found if ".Trashes" in path.parts]


def test_the_default_search_stays_one_level_deep(nested_footage: Path) -> None:
    """The command line keeps looking only inside the folder it is given."""
    assert not expand_paths([nested_footage])


def test_a_recursive_search_still_takes_named_files_as_given(x5_insv: Path) -> None:
    """Recursion only changes what a folder means."""
    assert expand_paths([x5_insv], recursive=True) == [x5_insv]


def test_a_recursive_search_lists_files_in_a_stable_order(nested_footage: Path) -> None:
    """The same folder gives the same list every time."""
    assert expand_paths([nested_footage], recursive=True) == expand_paths([nested_footage], recursive=True)
