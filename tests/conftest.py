"""Shared fixtures: a scratch copy of the sample file and the golden outputs."""

import shutil
from pathlib import Path

import pytest

RESOURCES = Path(__file__).parent / "resources"
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture
def sample_insv(tmp_path: Path) -> Path:
    """A writable copy of the sample file, in an empty directory.

    Commands write their output into the current directory and refuse to
    overwrite, so each test gets its own.
    """
    dest = tmp_path / "sample.insv"
    shutil.copy(RESOURCES / "sample.insv", dest)
    return dest


@pytest.fixture
def x5_insv(tmp_path: Path) -> Path:
    """A writable copy of the X5 fixture: indexed layout, inst box, markers.

    Built by tools/mkfixture.py from a real recording; see that script for
    what was truncated and scrubbed.
    """
    dest = tmp_path / "VID_20260620_173803_00_029.insv"
    shutil.copy(RESOURCES / "x5_indexed.insv", dest)
    return dest


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """A directory of one two-chapter X5 session, both chapters marked.

    Both copies carry the same three markers; the second is a stand-in for a
    later chapter, so the session's markers are the union of the two.
    """
    for chapter in ("029", "030"):
        shutil.copy(
            RESOURCES / "x5_indexed.insv",
            tmp_path / f"VID_20260620_173803_00_{chapter}.insv",
        )
    return tmp_path


@pytest.fixture
def unmarked_session(tmp_path: Path) -> Path:
    """A session whose ANCHORS frame holds nothing - the ONE R sample."""
    shutil.copy(RESOURCES / "sample.insv", tmp_path / "VID_20221218_231825_00_677.insv")
    return tmp_path


@pytest.fixture
def golden() -> Path:
    """The reference outputs, or skip if they have not been generated."""
    if not (GOLDEN / "PROVENANCE").exists():
        pytest.skip("golden outputs missing - run tools/refgen.sh (needs Docker)")
    return GOLDEN
