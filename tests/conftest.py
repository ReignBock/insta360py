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
def golden() -> Path:
    """The reference outputs, or skip if they have not been generated."""
    if not (GOLDEN / "PROVENANCE").exists():
        pytest.skip("golden outputs missing - run tools/refgen.sh (needs Docker)")
    return GOLDEN
