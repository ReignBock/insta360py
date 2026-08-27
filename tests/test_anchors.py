"""ANCHORS frame decoding.

sample.insv has no markers, so these cover the empty case against the real
payload and the populated case against a synthetic one. Marked clearly:
the layout is inferred and needs a file with real markers to confirm.
"""

import struct
from pathlib import Path

import pytest

from insvtools.frames.anchors_frame import marker_seconds, parse_anchors
from insvtools.frames.frame_type import FrameType
from insvtools.metadata import InsvMetadata


def test_sample_anchors_frame_is_seven_empty_sections(sample_insv: Path) -> None:
    with sample_insv.open("rb") as f:
        metadata = InsvMetadata.read(f)

    assert metadata is not None
    anchors = metadata.find_frame(FrameType.ANCHORS)
    assert len(anchors.payload) == 35

    sections = parse_anchors(anchors.payload)

    assert [s.kind for s in sections] == [1, 2, 3, 4, 0x10, 0x11, 0x12]
    assert all(s.timestamps == [] for s in sections)
    assert marker_seconds(anchors.payload, 309468418) == []


def test_populated_section() -> None:
    payload = (
        struct.pack("<BI", 1, 2)
        + struct.pack("<II", 310_000_000, 0)
        + struct.pack("<II", 311_500_000, 0)
        + struct.pack("<BI", 2, 0)
    )

    sections = parse_anchors(payload)

    assert [s.kind for s in sections] == [1, 2]
    assert sections[0].timestamps == [310_000_000, 311_500_000]
    assert marker_seconds(payload, 309_468_418) == pytest.approx([0.531582, 2.031582])


def test_impossible_count_is_rejected() -> None:
    """A bad count must fail loudly rather than read past the payload."""
    with pytest.raises(ValueError, match="claims 99 records"):
        parse_anchors(struct.pack("<BI", 1, 99))


def test_anchors_frame_stays_opaque_in_the_write_path(sample_insv: Path) -> None:
    """Nothing in read/write depends on this inferred layout."""
    with sample_insv.open("rb") as f:
        metadata = InsvMetadata.read(f)
        metadata.parse()

    anchors = metadata.find_frame(FrameType.ANCHORS)
    assert type(anchors).__name__ == "Frame"
    assert not anchors.parsed
