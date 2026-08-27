"""The ANCHORS frame (type 10) - the timeline markers a user presses record on.

Not part of the upstream Java, which leaves type 10 as an opaque payload. This
exists for the Insv-Marker-Extractor port, which currently gets markers by
running `decompose-meta --frame-type=10` and re-reading the bytes off disk.

**The layout here is inferred, not confirmed.** The PowerShell reads the
payload as a single ``uint32`` count at offset 1 followed by 8-byte records.
sample.insv's 35-byte payload does not fit that: it decodes cleanly as seven
5-byte section headers (``uint8 kind, uint32 count``) for kinds 1, 2, 3, 4,
0x10, 0x11 and 0x12, every one of them empty::

    01 00000000 | 02 00000000 | 03 00000000 | 04 00000000
    | 10 00000000 | 11 00000000 | 12 00000000

The PowerShell happens to work because section 1 comes first, so its records
- if there are any - start exactly where it looks for them. No file with
actual markers exists in this workspace, so neither reading is proven.

Because of that, this frame is deliberately *not* registered in the frame
factory: nothing in the read/write path depends on it, and a wrong guess here
can never corrupt a file that is being cut or recomposed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SECTION_HEADER_SIZE = 5
RECORD_SIZE = 8

_SECTION = struct.Struct("<BI")
_TIMESTAMP = struct.Struct("<I")


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
    in sample.insv), which is why they fit in 32 bits and why the offset is
    taken against the first frame rather than a Unix epoch.
    """
    return [
        (timestamp - first_frame_timestamp) / 1_000_000
        for section in parse_anchors(payload)
        for timestamp in section.timestamps
    ]
