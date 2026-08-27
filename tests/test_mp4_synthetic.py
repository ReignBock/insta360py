"""A hand-built container, for structures neither fixture contains.

sample.insv and x5_indexed.insv are both ordinary: stco or co64, ctts, stss.
Boxes that must be dropped (sbgp and friends), clipped (sdtp) or ignored
(edts), and the malformed cases, need a container built to order.
"""

# pylint: disable=protected-access,redefined-outer-name

import io
import struct
from pathlib import Path

import pytest

from insvtools.mp4.boxes import box_bytes, parse_boxes
from insvtools.mp4.reader import Mp4File
from insvtools.mp4.writer import write_clipped

SAMPLE_SIZE = 4
SAMPLE_COUNT = 8
MEDIA = b"".join(bytes([i]) * SAMPLE_SIZE for i in range(SAMPLE_COUNT))


def _full(payload: bytes) -> bytes:
    """Prefix a version/flags word."""
    return bytes(4) + payload


def _mvhd(timescale: int = 1000) -> bytes:
    # version 0: creation, modification, timescale, duration, then the rest.
    return box_bytes(b"mvhd", _full(struct.pack(">IIII", 0, 0, timescale, 1000)) + bytes(80))


def _mdhd(timescale: int = 1000) -> bytes:
    return box_bytes(b"mdhd", _full(struct.pack(">IIII", 0, 0, timescale, 1000)) + bytes(4))


def _tkhd() -> bytes:
    return box_bytes(b"tkhd", _full(struct.pack(">IIIII", 0, 0, 1, 0, 1000)) + bytes(60))


def _hdlr(handler: bytes) -> bytes:
    return box_bytes(b"hdlr", _full(b"\x00" * 4 + handler) + bytes(12))


def _elst() -> bytes:
    return box_bytes(b"edts", box_bytes(b"elst", _full(struct.pack(">IIII", 1, 1000, 0, 1))))


def _stbl(mdat_payload_offset: int, *, extra: bytes = b"") -> bytes:
    stts = box_bytes(b"stts", _full(struct.pack(">III", 1, SAMPLE_COUNT, 100)))
    stsc = box_bytes(b"stsc", _full(struct.pack(">IIII", 1, 1, SAMPLE_COUNT, 1)))
    stsz = box_bytes(b"stsz", _full(struct.pack(">II", SAMPLE_SIZE, SAMPLE_COUNT)))
    stco = box_bytes(b"stco", _full(struct.pack(">II", 1, mdat_payload_offset)))
    stss = box_bytes(b"stss", _full(struct.pack(">II", 2, 1) + struct.pack(">I", 5)))
    stsd = box_bytes(b"stsd", _full(struct.pack(">I", 0)))
    return box_bytes(b"stbl", stsd + stts + stsc + stsz + stco + stss + extra)


def build_mp4(*, extra_stbl: bytes = b"", with_edts: bool = False) -> bytes:
    """A single-track container whose one chunk holds every sample."""
    ftyp = box_bytes(b"ftyp", b"isom" + bytes(8))
    mdat_offset = len(ftyp)
    mdat = box_bytes(b"mdat", MEDIA)
    payload_offset = mdat_offset + 8

    minf = box_bytes(b"minf", _stbl(payload_offset, extra=extra_stbl))
    mdia = box_bytes(b"mdia", _mdhd() + _hdlr(b"vide") + minf)
    trak = box_bytes(b"trak", _tkhd() + (_elst() if with_edts else b"") + mdia)
    moov = box_bytes(b"moov", _mvhd() + trak)

    return ftyp + mdat + moov


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    """A minimal single-track container written to disk."""
    path = tmp_path / "synthetic.mp4"
    path.write_bytes(build_mp4())
    return path


def _clip(path: Path, out: Path, first: int, last: int) -> None:
    with path.open("rb") as f:
        mp4 = Mp4File.read(f)
        with out.open("wb") as g:
            write_clipped(f, mp4, [(first, last)], g)


# --- reading ----------------------------------------------------------------


def test_a_container_with_no_limit_is_read_to_the_end(synthetic: Path) -> None:
    """Omitting the limit means "the whole file" - the plain-MP4 case."""
    with synthetic.open("rb") as f:
        mp4 = Mp4File.read(f)

    assert mp4.limit == synthetic.stat().st_size
    assert len(mp4.tracks) == 1
    assert len(mp4.tracks[0].samples) == SAMPLE_COUNT
    assert [s.sync for s in mp4.tracks[0].samples][:5] == [True, False, False, False, True]


def test_a_container_without_moov_is_rejected(tmp_path: Path) -> None:
    """Without moov there are no tracks to read."""
    path = tmp_path / "nomoov.mp4"
    path.write_bytes(box_bytes(b"ftyp", b"isom"))

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="No moov box found"):
            Mp4File.read(f)


def test_a_moov_without_mvhd_is_rejected(tmp_path: Path) -> None:
    """The movie timescale lives in mvhd."""
    path = tmp_path / "nomvhd.mp4"
    path.write_bytes(box_bytes(b"moov", box_bytes(b"trak", b"")))

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="No mvhd box found"):
            Mp4File.read(f)


def test_a_trak_without_mdia_is_rejected(tmp_path: Path) -> None:
    """A track with no media has nothing to clip."""
    path = tmp_path / "nomdia.mp4"
    path.write_bytes(box_bytes(b"moov", _mvhd() + box_bytes(b"trak", _tkhd())))

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="trak without mdia"):
            Mp4File.read(f)


def test_a_trak_missing_mdhd_is_rejected(tmp_path: Path) -> None:
    """mdhd, hdlr and stbl are all required to expand a track."""
    path = tmp_path / "nomdhd.mp4"
    mdia = box_bytes(b"mdia", _hdlr(b"vide"))
    path.write_bytes(box_bytes(b"moov", _mvhd() + box_bytes(b"trak", _tkhd() + mdia)))

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="missing mdhd, hdlr or stbl"):
            Mp4File.read(f)


def test_an_stbl_missing_a_required_table_is_rejected(tmp_path: Path) -> None:
    """stts, stsz, stsc and the chunk offsets are all needed."""
    path = tmp_path / "nostts.mp4"
    minf = box_bytes(b"minf", box_bytes(b"stbl", box_bytes(b"stsd", _full(bytes(4)))))
    mdia = box_bytes(b"mdia", _mdhd() + _hdlr(b"vide") + minf)
    path.write_bytes(box_bytes(b"moov", _mvhd() + box_bytes(b"trak", _tkhd() + mdia)))

    with path.open("rb") as f:
        with pytest.raises(ValueError, match="missing a required table"):
            Mp4File.read(f)


def test_a_header_cut_short_by_the_end_of_file_ends_the_walk(tmp_path: Path) -> None:
    """The region claims more bytes than the file actually holds."""
    path = tmp_path / "short.mp4"
    path.write_bytes(box_bytes(b"free", b"") + b"\x00\x00")

    with path.open("rb") as f:
        boxes = parse_boxes(f, 0, 999)

    assert [b.type for b in boxes] == [b"free"]


# --- writing ----------------------------------------------------------------


def test_clipping_keeps_only_the_requested_samples(synthetic: Path, tmp_path: Path) -> None:
    """The output holds exactly the requested sample range, in order."""
    out = tmp_path / "clipped.mp4"
    _clip(synthetic, out, 2, 6)

    with out.open("rb") as f:
        mp4 = Mp4File.read(f)
        data = []
        for sample in mp4.tracks[0].samples:
            f.seek(sample.offset)
            data.append(f.read(sample.size))

    assert len(mp4.tracks[0].samples) == 4
    assert data == [bytes([i]) * SAMPLE_SIZE for i in range(2, 6)]


def test_boxes_that_cannot_be_clipped_are_dropped(tmp_path: Path) -> None:
    """sbgp/sgpd/stsh index samples by number and would be left stale."""
    source = tmp_path / "grouped.mp4"
    source.write_bytes(build_mp4(extra_stbl=box_bytes(b"sbgp", _full(bytes(8)))))

    out = tmp_path / "clipped.mp4"
    _clip(source, out, 0, 4)

    with out.open("rb") as f:
        mp4 = Mp4File.read(f)
        stbl = mp4.tracks[0].box.find(b"mdia", b"minf", b"stbl")
        assert stbl is not None
        assert b"sbgp" not in {c.type for c in stbl.children}


def test_sdtp_is_clipped_alongside_the_samples(tmp_path: Path) -> None:
    """One byte per sample, so it has to be sliced to the same range."""
    sdtp = box_bytes(b"sdtp", _full(bytes(range(SAMPLE_COUNT))))
    source = tmp_path / "sdtp.mp4"
    source.write_bytes(build_mp4(extra_stbl=sdtp))

    out = tmp_path / "clipped.mp4"
    _clip(source, out, 2, 5)

    with out.open("rb") as f:
        mp4 = Mp4File.read(f)
        stbl = mp4.tracks[0].box.find(b"mdia", b"minf", b"stbl")
        assert stbl is not None
        kept = next(c for c in stbl.children if c.type == b"sdtp")
        assert kept.payload(f)[4:] == bytes([2, 3, 4])


def test_an_edit_list_is_dropped(tmp_path: Path) -> None:
    """The edit list maps into media time the cut has just moved."""
    source = tmp_path / "edts.mp4"
    source.write_bytes(build_mp4(with_edts=True))

    with source.open("rb") as f:
        assert Mp4File.read(f).tracks[0].box.find(b"edts") is not None

    out = tmp_path / "clipped.mp4"
    _clip(source, out, 0, 4)

    with out.open("rb") as f:
        assert Mp4File.read(f).tracks[0].box.find(b"edts") is None


def test_a_container_without_mdat_cannot_be_written(tmp_path: Path) -> None:
    """There is nowhere to copy samples from."""
    path = tmp_path / "nomdat.mp4"
    minf = box_bytes(b"minf", _stbl(9999))
    mdia = box_bytes(b"mdia", _mdhd() + _hdlr(b"vide") + minf)
    trak = box_bytes(b"trak", _tkhd() + mdia)
    path.write_bytes(box_bytes(b"moov", _mvhd() + trak))

    with path.open("rb") as f:
        mp4 = Mp4File.read(f)
        with pytest.raises(ValueError, match="No mdat box found"):
            write_clipped(f, mp4, [(0, 1)], io.BytesIO())


def test_samples_running_past_the_end_of_the_file_are_an_error(tmp_path: Path) -> None:
    """A truncated file must fail loudly, not write a short sample."""
    whole = build_mp4()
    path = tmp_path / "truncated.mp4"
    path.write_bytes(whole[: len(whole) - 4])  # cuts into moov, not mdat

    with path.open("rb") as f:
        mp4 = Mp4File.read(f, len(whole))
        mp4.tracks[0].samples[0].size = 10**6
        with pytest.raises(ValueError, match="Unexpected end of file"):
            write_clipped(f, mp4, [(0, 1)], io.BytesIO())


def _stz2_stbl(mdat_payload_offset: int) -> bytes:
    """The same table as _stbl, but with sizes in the compact stz2 form."""
    stts = box_bytes(b"stts", _full(struct.pack(">III", 1, SAMPLE_COUNT, 100)))
    stsc = box_bytes(b"stsc", _full(struct.pack(">IIII", 1, 1, SAMPLE_COUNT, 1)))
    stz2 = box_bytes(
        b"stz2",
        bytes(4) + bytes(3) + bytes([8]) + struct.pack(">I", SAMPLE_COUNT)
        + bytes([SAMPLE_SIZE]) * SAMPLE_COUNT,
    )
    stco = box_bytes(b"stco", _full(struct.pack(">II", 1, mdat_payload_offset)))
    stsd = box_bytes(b"stsd", _full(struct.pack(">I", 0)))
    return box_bytes(b"stbl", stsd + stts + stsc + stz2 + stco)


def _wrap(stbl: bytes, media: bytes = MEDIA) -> bytes:
    ftyp = box_bytes(b"ftyp", b"isom" + bytes(8))
    mdat = box_bytes(b"mdat", media)
    minf = box_bytes(b"minf", stbl)
    mdia = box_bytes(b"mdia", _mdhd() + _hdlr(b"vide") + minf)
    trak = box_bytes(b"trak", _tkhd() + mdia)
    return ftyp + mdat + box_bytes(b"moov", _mvhd() + trak)


def test_a_compact_stz2_table_is_read(tmp_path: Path) -> None:
    """stz2 packs sizes into 4, 8 or 16 bits instead of a word each."""
    path = tmp_path / "stz2.mp4"
    ftyp_len = len(box_bytes(b"ftyp", b"isom" + bytes(8)))
    path.write_bytes(_wrap(_stz2_stbl(ftyp_len + 8)))

    with path.open("rb") as f:
        mp4 = Mp4File.read(f)

    assert len(mp4.tracks[0].samples) == SAMPLE_COUNT
    assert {s.size for s in mp4.tracks[0].samples} == {SAMPLE_SIZE}
    assert mp4.tracks[0].constant_sample_size == 0


def test_an_stsc_naming_more_chunks_than_exist_stops_at_the_last(tmp_path: Path) -> None:
    """A table that over-claims must not index past the chunk offsets."""
    stts = box_bytes(b"stts", _full(struct.pack(">III", 1, SAMPLE_COUNT, 100)))
    # Two entries, so the first runs to chunk 2 - but only one offset exists.
    stsc = box_bytes(
        b"stsc", _full(struct.pack(">I", 2) + struct.pack(">IIIIII", 1, 4, 1, 3, 4, 1))
    )
    stsz = box_bytes(b"stsz", _full(struct.pack(">II", SAMPLE_SIZE, SAMPLE_COUNT)))
    stco = box_bytes(b"stco", _full(struct.pack(">II", 1, 20)))
    stsd = box_bytes(b"stsd", _full(struct.pack(">I", 0)))
    path = tmp_path / "overclaim.mp4"
    path.write_bytes(_wrap(box_bytes(b"stbl", stsd + stts + stsc + stsz + stco)))

    with path.open("rb") as f:
        mp4 = Mp4File.read(f)

    assert len(mp4.tracks[0].samples) == 4  # one chunk's worth, not two


def test_a_chunk_claiming_more_samples_than_the_size_table_stops(tmp_path: Path) -> None:
    """A chunk claiming more samples than the size table holds stops at the table."""
    stts = box_bytes(b"stts", _full(struct.pack(">III", 1, 2, 100)))
    stsc = box_bytes(b"stsc", _full(struct.pack(">IIII", 1, 1, 99, 1)))
    stsz = box_bytes(b"stsz", _full(struct.pack(">II", SAMPLE_SIZE, 2)))
    stco = box_bytes(b"stco", _full(struct.pack(">II", 1, 20)))
    stsd = box_bytes(b"stsd", _full(struct.pack(">I", 0)))
    path = tmp_path / "oversized.mp4"
    path.write_bytes(_wrap(box_bytes(b"stbl", stsd + stts + stsc + stsz + stco)))

    with path.open("rb") as f:
        mp4 = Mp4File.read(f)

    assert len(mp4.tracks[0].samples) == 2  # capped by the size table


def test_a_large_unreferenced_run_before_the_first_sample_is_dropped(
    tmp_path: Path,
) -> None:
    """A small gap is padding worth keeping; a big one is not ours to carry."""
    padding = 5000  # over _MAX_MDAT_PREFIX
    media = bytes(padding) + MEDIA
    ftyp_len = len(box_bytes(b"ftyp", b"isom" + bytes(8)))
    path = tmp_path / "padded.mp4"
    path.write_bytes(_wrap(_stbl(ftyp_len + 8 + padding), media=media))

    out = tmp_path / "clipped.mp4"
    _clip(path, out, 0, 2)

    with out.open("rb") as f:
        mp4 = Mp4File.read(f)
        mdat = next(b for b in mp4.boxes if b.type == b"mdat")
        assert mp4.tracks[0].samples[0].offset == mdat.payload_offset


def test_a_track_with_no_samples_writes_an_empty_mdat(tmp_path: Path) -> None:
    """Nothing references mdat, so there is no prefix to preserve either."""
    stts = box_bytes(b"stts", _full(struct.pack(">I", 0)))
    stsc = box_bytes(b"stsc", _full(struct.pack(">I", 0)))
    stsz = box_bytes(b"stsz", _full(struct.pack(">II", SAMPLE_SIZE, 0)))
    stco = box_bytes(b"stco", _full(struct.pack(">I", 0)))
    stsd = box_bytes(b"stsd", _full(struct.pack(">I", 0)))
    path = tmp_path / "empty.mp4"
    path.write_bytes(_wrap(box_bytes(b"stbl", stsd + stts + stsc + stsz + stco)))

    out = io.BytesIO()
    with path.open("rb") as f:
        mp4 = Mp4File.read(f)
        assert mp4.tracks[0].samples == []
        write_clipped(f, mp4, [(0, 0)], out)

    boxes = parse_boxes(io.BytesIO(out.getvalue()), 0, len(out.getvalue()))
    mdat = next(b for b in boxes if b.type == b"mdat")
    assert mdat.payload_size == 0
