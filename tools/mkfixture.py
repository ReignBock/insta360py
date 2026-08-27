"""Build tests/resources/x5_indexed.insv from a real Insta360 X5 recording.

sample.insv (a ONE R file) exercises only the chained-frame layout. Newer
cameras write a different shape that nothing else in the test suite reaches:
an INDEX frame, an ``inst`` box wrapping the trailer, frame types beyond the
24 that are documented, an empty ExtraMetadata.Gyro, and real ANCHORS markers.

The source recordings are private and far too large to commit (tens of GB), so
this derives a small fixture from one. It is not camera output byte-for-byte -
payloads are truncated and personal data is removed - but every structural
feature above is preserved, which is what the tests are about.

Personal data is stripped deliberately:
  * GPS records are replaced with zeroed ones (real coordinates otherwise).
  * The camera serial number is replaced.
  * The thumbnail is truncated past its header, so no image survives.

Usage:  python tools/mkfixture.py <source.lrv> [out.insv]
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# pylint: disable=wrong-import-position
from insvtools.commands.cut import cut_one
from insvtools.frames.frame_type import FrameType
from insvtools.frames.index_frame import IndexFrame
from insvtools.frames.info_frame import InfoFrame
from insvtools.header import InsvHeader
from insvtools.metadata import InsvMetadata, write_trailer
from insvtools.mp4.boxes import parse_boxes
from insvtools.records.gps import GpsRecord

# Enough of each payload to keep records parseable, small enough to commit.
PAYLOAD_CAP = 256
# moov/udta is a multi-megabyte Insta360 blob of proprietary children. It is
# emptied rather than truncated - it is a container, so a partial copy would
# leave a half-written child box behind. mdat precedes moov in these files, so
# shrinking moov moves no chunk and no offset needs fixing.
EMPTY_UDTA = struct.pack(">I4s", 8, b"udta")
THUMBNAIL_CAP = 64
GPS_RECORDS = 2
SCRUBBED_SERIAL = "TESTSERIAL0000"

_U32 = struct.Struct(">I")


def build(source: Path, out: Path) -> None:
    """Cut a fraction of a second off ``source`` and shrink its trailer."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.insv"
        # 0.2s starting on a keyframe: a handful of samples, real container.
        cut_one(source, clip, start_time=0.0, end_time=0.2)

        with clip.open("rb") as f:
            header = InsvHeader.read(f)
            assert header is not None and header.boxed, "source is not X5-shaped"
            f.seek(0)
            metadata = InsvMetadata.read(f)
            assert metadata is not None
            container = _read_container(f, header)

        _shrink(metadata)

        with out.open("wb") as g:
            g.write(container)
            write_trailer(g, metadata, boxed=True)


def _read_container(f, header: InsvHeader) -> bytes:
    """The MP4 content, with the oversized udta blob cut down."""
    out = bytearray()

    for box in parse_boxes(f, 0, header.container_end):
        if box.type != b"moov":
            out += _raw(f, box)
            continue

        payload = bytearray()
        for child in box.children:
            payload += EMPTY_UDTA if child.type == b"udta" else _raw(f, child)

        out += _U32.pack(len(payload) + 8) + b"moov" + payload

    return bytes(out)


def _raw(f, box) -> bytes:
    f.seek(box.offset)
    return f.read(box.size)


def _shrink(metadata: InsvMetadata) -> None:
    """Truncate payloads and remove personal data, in place."""
    for frame in metadata.frames:
        frame_type = frame.header.frame_type

        if isinstance(frame, IndexFrame):
            frame.parse(metadata)  # rebuilt on write, must be interpreted
        elif isinstance(frame, InfoFrame):
            frame.parse(metadata)
            assert frame.extra_metadata is not None
            frame.extra_metadata.SerialNumber = SCRUBBED_SERIAL
        elif frame_type is FrameType.GPS:
            frame.payload = bytes(GpsRecord.SIZE * GPS_RECORDS)
        elif frame_type is FrameType.THUMBNAIL:
            frame.payload = frame.payload[:THUMBNAIL_CAP]
        elif frame_type is not FrameType.ANCHORS:
            # ANCHORS is the point of the fixture; everything else just needs
            # to still be there, not to still be whole.
            frame.payload = frame.payload[:PAYLOAD_CAP]


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("tests/resources/x5_indexed.insv")
    build(src, dst)
    print(f"wrote {dst} ({dst.stat().st_size:,} bytes)")
