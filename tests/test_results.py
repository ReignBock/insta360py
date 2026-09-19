"""Scanning footage and arranging recordings under the folders searched."""

# pylint: disable=redefined-outer-name

import shutil
from pathlib import Path

from insvmarkers.extractor import expand_paths
from insvmarkers.results import FolderNode, SessionResult, group_by_folder, scan

RESOURCES = Path(__file__).parent / "resources"


def _results(searched: Path) -> list[SessionResult]:
    """Every recording under a folder, read."""
    return scan(expand_paths([searched], recursive=True))


def _names(folders: list[FolderNode]) -> list[str]:
    """The folder names of one level of the tree."""
    return [folder.path.name for folder in folders]


def test_the_tree_shows_each_folder_on_the_way_to_a_recording(nested_footage: Path) -> None:
    """From the searched folder down to the recording, one node per folder."""
    roots, loose = group_by_folder(_results(nested_footage), [nested_footage])

    assert not loose
    assert [root.path for root in roots] == [nested_footage]

    card = roots[0].folders[0]
    assert _names(roots[0].folders) == ["card1", "card2"]
    assert _names(card.folders) == ["DCIM"]
    assert _names(card.folders[0].folders) == ["Camera01"]
    assert len(card.folders[0].folders[0].sessions) == 1


def test_folders_without_footage_are_left_out(nested_footage: Path) -> None:
    """``Notes`` and ``empty`` lead nowhere, so they do not appear."""
    roots, _ = group_by_folder(_results(nested_footage), [nested_footage])

    shown = {folder.path.name for card in roots[0].folders for folder in card.folders}
    assert shown == {"DCIM"}


def test_a_folder_counts_the_recordings_beneath_it(nested_footage: Path) -> None:
    """The count covers every level below, not just the folder itself."""
    roots, _ = group_by_folder(_results(nested_footage), [nested_footage])

    assert roots[0].recording_count == 2
    assert roots[0].folders[0].recording_count == 1


def test_recordings_in_one_folder_share_a_node(tmp_path: Path) -> None:
    """A second recording in the same place does not add a second folder."""
    for stamp in ("20260620_173803", "20260621_090000"):
        shutil.copy(RESOURCES / "x5_indexed.insv", tmp_path / f"VID_{stamp}_00_029.insv")

    roots, _ = group_by_folder(_results(tmp_path), [tmp_path])

    assert not roots[0].folders
    assert len(roots[0].sessions) == 2


def test_files_added_one_by_one_are_not_under_any_folder(x5_insv: Path) -> None:
    """With no folder searched, the recording stands alone."""
    roots, loose = group_by_folder(scan([x5_insv]), [])

    assert not roots
    assert len(loose) == 1


def test_a_recording_goes_under_the_closest_searched_folder(nested_footage: Path) -> None:
    """Searching a card and the folder above it puts the card's footage under the card."""
    card = nested_footage / "card1"

    roots, loose = group_by_folder(_results(nested_footage), [nested_footage, card])

    assert not loose
    assert [root.path for root in roots] == [nested_footage, card]
    assert roots[0].recording_count == 1
    assert roots[1].recording_count == 1


def test_a_searched_folder_with_no_recordings_is_omitted(nested_footage: Path, tmp_path: Path) -> None:
    """Only folders that lead to footage are shown."""
    bare = tmp_path / "bare"
    bare.mkdir()

    roots, _ = group_by_folder(_results(nested_footage), [bare, nested_footage])

    assert [root.path for root in roots] == [nested_footage]


def test_naming_a_folder_twice_lists_it_once(nested_footage: Path) -> None:
    """A repeated folder must not repeat its footage."""
    roots, _ = group_by_folder(_results(nested_footage), [nested_footage, nested_footage])

    assert len(roots) == 1
    assert roots[0].recording_count == 2


def test_recordings_in_sibling_folders_share_their_parent(tmp_path: Path) -> None:
    """Two cameras under one DCIM folder give one DCIM node with two children."""
    for camera, stamp in (("Camera01", "20260620_173803"), ("Camera02", "20260621_090000")):
        folder = tmp_path / "DCIM" / camera
        folder.mkdir(parents=True)
        shutil.copy(RESOURCES / "x5_indexed.insv", folder / f"VID_{stamp}_00_029.insv")

    roots, _ = group_by_folder(_results(tmp_path), [tmp_path])

    assert _names(roots[0].folders) == ["DCIM"]
    assert _names(roots[0].folders[0].folders) == ["Camera01", "Camera02"]
