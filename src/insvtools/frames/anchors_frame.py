"""The ANCHORS frame (type 10) - the timeline markers a user presses record on.

Not part of the upstream Java, which leaves type 10 as an opaque payload. This
exists for the Insv-Marker-Extractor port, which currently gets markers by
running `decompose-meta --frame-type=10` and re-reading the bytes off disk.

The payload is a run of sections, each a 5-byte header (``uint8 kind,
uint32 count``) followed by ``count`` 8-byte records. Kinds 1, 2, 3, 4, 0x10,
0x11 and 0x12 appear, in that order, whether or not they hold anything - an
empty frame is 35 bytes of nothing but headers::

    01 00000000 | 02 00000000 | 03 00000000 | 04 00000000
    | 10 00000000 | 11 00000000 | 12 00000000

Only section 1 has ever been seen with records in it. The PowerShell reads a
count at offset 1 and records from offset 5, which works only because
section 1 comes first; it would misread markers of any other kind.

Records are a single ``uint64`` timestamp on the same monotonic clock as
``ExtraMetadata.FirstFrameTimestamp``. The PowerShell reads them as
``uint32``, which is wrong for any recording whose clock has passed ~71
minutes of uptime - confirmed against X5 files whose markers are all above
2**32.

This frame is deliberately *not* registered in the frame factory: nothing in
the read/write path depends on it, so it cannot corrupt a file being cut or
recomposed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SECTION_HEADER_SIZE = 5
RECORD_SIZE = 8

_SECTION = struct.Struct("<BI")
_TIMESTAMP = struct.Struct("<Q")


@dataclass
class AnchorSection:
    """One run of markers of a single kind."""

    kind: int
    timestamps: list[int] = field(default_factory=list)


def parse_anchors(payload: bytes) -> list[AnchorSection]:
    """Decode an ANCHORS payload into its sections.

    Trailing bytes too short for a section header are ignored, matching how
    the record-oriented frames treat a partial trailing record.
    """
    sections: list[AnchorSection] = []
    offset = 0

    while len(payload) - offset >= SECTION_HEADER_SIZE:
        kind, count = _SECTION.unpack_from(payload, offset)
        offset += SECTION_HEADER_SIZE

        available = (len(payload) - offset) // RECORD_SIZE
        if count > available:
            raise ValueError(
                f"ANCHORS section {kind} claims {count} records but only "
                f"{available} fit in the remaining {len(payload) - offset} bytes"
            )

        timestamps = [
            _TIMESTAMP.unpack_from(payload, offset + i * RECORD_SIZE)[0]
            for i in range(count)
        ]
        offset += count * RECORD_SIZE

        sections.append(AnchorSection(kind, timestamps))

    return sections


def marker_seconds(payload: bytes, first_frame_timestamp: int) -> list[float]:
    """Marker positions in seconds from the start of the recording.

    Timestamps are on the same monotonic microsecond clock as
    ``ExtraMetadata.FirstFrameTimestamp`` (309468418 - about 309 s of uptime -
    in sample.insv), which is why the offset is taken against the first frame
    rather than a Unix epoch. The clock does not reset between recordings, so
    on a camera that has been on a while these run well past 32 bits.
    """
    return [
        (timestamp - first_frame_timestamp) / 1_000_000
        for section in parse_anchors(payload)
        for timestamp in section.timestamps
    ]
