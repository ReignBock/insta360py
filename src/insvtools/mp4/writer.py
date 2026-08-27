"""Rewrite an MP4 clipped to a range of samples.

This is deliberately not a muxer. Every box is copied through verbatim except
the handful that are indexed by sample number, which are regenerated, and the
three duration fields. Anything the format grows that we've never heard of
survives untouched - the same principle the metadata trailer's RAW frames
follow.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from itertools import groupby
from typing import BinaryIO

from .boxes import Box, box_bytes
from .reader import Mp4File, Sample, Track

logger = logging.getLogger(__name__)

_U32 = struct.Struct(">I")
_U64 = struct.Struct(">Q")

# Sample-indexed boxes we regenerate.
_REWRITTEN = frozenset({b"stts", b"stss", b"stsc", b"stsz", b"stz2", b"stco", b"co64", b"ctts"})

# Optional, derived boxes we cannot clip meaningfully. They are hints a player
# can live without, so they are dropped rather than emitted stale.
_DROPPED = frozenset({b"sbgp", b"sgpd", b"stsh", b"subs", b"saiz", b"saio", b"cslg"})

_COPY_CHUNK = 1 << 20

# Cameras pad the start of mdat (sample.insv has 8 zero bytes there). Copying
# that padding keeps a full-range rewrite byte-identical to the source. The
# bound stops a file with a genuinely large unreferenced region from dragging
# junk along.
_MAX_MDAT_PREFIX = 4096


@dataclass
class _Chunk:
    track_index: int
    samples: list[Sample]
    sample_description: int
    source_offset: int
    new_offset: int = 0

    @property
    def size(self) -> int:
        """Total bytes of the samples in this chunk."""
        return sum(s.size for s in self.samples)


def _run_length(values: list[int]) -> list[tuple[int, int]]:
    """Collapse equal neighbours into (count, value) pairs, as stts/ctts store them."""
    return [(sum(1 for _ in group), value) for value, group in groupby(values)]


def _stts(samples: list[Sample]) -> bytes:
    runs = _run_length([s.duration for s in samples])
    payload = bytearray(b"\x00\x00\x00\x00" + _U32.pack(len(runs)))
    for count, delta in runs:
        payload += struct.pack(">II", count, delta)
    return box_bytes(b"stts", bytes(payload))


def _ctts(samples: list[Sample]) -> bytes:
    runs = _run_length([s.cts_offset for s in samples])
    # Version 1 allows negative offsets and is a superset of version 0.
    payload = bytearray(b"\x01\x00\x00\x00" + _U32.pack(len(runs)))
    for count, offset in runs:
        payload += struct.pack(">Ii", count, offset)
    return box_bytes(b"ctts", bytes(payload))


def _stss(samples: list[Sample]) -> bytes:
    numbers = [i + 1 for i, s in enumerate(samples) if s.sync]
    payload = bytearray(b"\x00\x00\x00\x00" + _U32.pack(len(numbers)))
    for number in numbers:
        payload += _U32.pack(number)
    return box_bytes(b"stss", bytes(payload))


def _stsz(samples: list[Sample], constant_size: int) -> bytes:
    sizes = [s.size for s in samples]
    # Keep the original's shape: a constant-size table stays constant.
    if constant_size and all(size == constant_size for size in sizes):
        payload = b"\x00\x00\x00\x00" + struct.pack(">II", constant_size, len(sizes))
        return box_bytes(b"stsz", payload)

    payload = bytearray(b"\x00\x00\x00\x00" + struct.pack(">II", 0, len(sizes)))
    for size in sizes:
        payload += _U32.pack(size)
    return box_bytes(b"stsz", bytes(payload))


def _stsc(chunks: list[_Chunk]) -> bytes:
    entries: list[tuple[int, int, int]] = []
    for index, chunk in enumerate(chunks):
        samples_per_chunk = len(chunk.samples)
        sdi = chunk.sample_description
        if entries and entries[-1][1] == samples_per_chunk and entries[-1][2] == sdi:
            continue
        entries.append((index + 1, samples_per_chunk, sdi))

    payload = bytearray(b"\x00\x00\x00\x00" + _U32.pack(len(entries)))
    for first_chunk, samples_per_chunk, sdi in entries:
        payload += struct.pack(">III", first_chunk, samples_per_chunk, sdi)
    return box_bytes(b"stsc", bytes(payload))


def _chunk_offset_box(chunks: list[_Chunk]) -> bytes:
    if any(chunk.new_offset > 0xFFFFFFFF for chunk in chunks):
        payload = bytearray(b"\x00\x00\x00\x00" + _U32.pack(len(chunks)))
        for chunk in chunks:
            payload += _U64.pack(chunk.new_offset)
        return box_bytes(b"co64", bytes(payload))

    payload = bytearray(b"\x00\x00\x00\x00" + _U32.pack(len(chunks)))
    for chunk in chunks:
        payload += _U32.pack(chunk.new_offset)
    return box_bytes(b"stco", bytes(payload))


def _sdtp(payload: bytes, first: int, last: int) -> bytes:
    """Clip the per-sample dependency table; one byte per sample after the header."""
    return box_bytes(b"sdtp", payload[:4] + payload[4 + first : 4 + last])


def _patch_duration(payload: bytes, duration: int, offsets: tuple[int, int]) -> bytes:
    """Replace a 32- or 64-bit duration field, leaving everything else alone."""
    v0_offset, v1_offset = offsets
    data = bytearray(payload)
    if payload[0] == 1:
        _U64.pack_into(data, v1_offset, duration)
    else:
        _U32.pack_into(data, v0_offset, min(duration, 0xFFFFFFFF))
    return bytes(data)


def _build_chunks(tracks: list[Track], clipped: list[list[Sample]]) -> list[_Chunk]:
    """Group clipped samples back into chunks, preserving interleaving order.

    Samples that shared a chunk in the source stay together, and chunks are
    emitted in source-offset order, so a file that was interleaved for
    streaming stays interleaved.
    """
    chunks: list[_Chunk] = []

    for track_index, (track, samples) in enumerate(zip(tracks, clipped)):
        current: _Chunk | None = None
        for sample in samples:
            if current is None or sample.chunk != current.samples[-1].chunk:
                sdi = (
                    track.chunk_sample_description[sample.chunk]
                    if sample.chunk < len(track.chunk_sample_description)
                    else 1
                )
                current = _Chunk(track_index, [sample], sdi, sample.offset)
                chunks.append(current)
            else:
                current.samples.append(sample)

    chunks.sort(key=lambda c: c.source_offset)
    return chunks


def _rebuild_stbl(
    f: BinaryIO,
    stbl: Box,
    samples: list[Sample],
    track: Track,
    chunks: list[_Chunk],
    first: int,
    last: int,
) -> bytes:
    parts: list[bytes] = []

    for child in stbl.children:
        if child.type in _DROPPED:
            logger.debug("Dropping %s box: cannot be clipped", child.type.decode("latin1"))
            continue
        if child.type == b"sdtp":
            parts.append(_sdtp(child.payload(f), first, last))
            continue
        if child.type not in _REWRITTEN:
            parts.append(child.raw(f))
            continue

        if child.type == b"stts":
            parts.append(_stts(samples))
        elif child.type == b"stss":
            parts.append(_stss(samples))
        elif child.type == b"ctts":
            parts.append(_ctts(samples))
        elif child.type in (b"stsz", b"stz2"):
            parts.append(_stsz(samples, track.constant_sample_size))
        elif child.type == b"stsc":
            parts.append(_stsc(chunks))
        elif child.type in (b"stco", b"co64"):
            parts.append(_chunk_offset_box(chunks))

    return box_bytes(b"stbl", b"".join(parts))


def _rebuild_container(f: BinaryIO, box: Box, replacements: dict[int, bytes | None]) -> bytes:
    if box.offset in replacements:
        replacement = replacements[box.offset]
        return b"" if replacement is None else replacement

    if not box.children:
        return box.raw(f)

    payload = b"".join(_rebuild_container(f, child, replacements) for child in box.children)
    return box_bytes(box.type, payload)


def _build_moov(
    f: BinaryIO,
    mp4: Mp4File,
    clipped: list[list[Sample]],
    ranges: list[tuple[int, int]],
    chunks: list[_Chunk],
) -> bytes:
    replacements: dict[int, bytes | None] = {}
    movie_duration = 0

    for index, track in enumerate(mp4.tracks):
        samples = clipped[index]
        first, last = ranges[index]
        track_chunks = [c for c in chunks if c.track_index == index]

        stbl = track.box.find(b"mdia", b"minf", b"stbl")
        assert stbl is not None
        replacements[stbl.offset] = _rebuild_stbl(
            f, stbl, samples, track, track_chunks, first, last
        )

        media_duration = sum(s.duration for s in samples)
        track_duration = (
            round(media_duration * mp4.movie_timescale / track.timescale)
            if track.timescale
            else 0
        )
        movie_duration = max(movie_duration, track_duration)

        mdhd = track.box.find(b"mdia", b"mdhd")
        if mdhd is not None:
            replacements[mdhd.offset] = box_bytes(
                b"mdhd", _patch_duration(mdhd.payload(f), media_duration, (16, 24))
            )

        tkhd = track.box.find(b"tkhd")
        if tkhd is not None:
            replacements[tkhd.offset] = box_bytes(
                b"tkhd", _patch_duration(tkhd.payload(f), track_duration, (20, 28))
            )

        # An edit list maps into media time we have just moved; leaving a stale
        # one is worse than leaving none.
        edts = track.box.find(b"edts")
        if edts is not None:
            logger.debug("Dropping edts box: edit list cannot be clipped")
            replacements[edts.offset] = None

    mvhd = mp4.moov.find(b"mvhd")
    if mvhd is not None:
        replacements[mvhd.offset] = box_bytes(
            b"mvhd", _patch_duration(mvhd.payload(f), movie_duration, (16, 24))
        )

    return _rebuild_container(f, mp4.moov, replacements)


def _mdat_prefix(f: BinaryIO, mp4: Mp4File, mdat: Box) -> bytes:
    """Bytes between the start of mdat's payload and the first sample."""
    offsets = [s.offset for track in mp4.tracks for s in track.samples]
    if not offsets:
        return b""

    gap = min(offsets) - mdat.payload_offset

    if not 0 < gap <= _MAX_MDAT_PREFIX:
        if gap > _MAX_MDAT_PREFIX:
            logger.debug("Ignoring %d unreferenced bytes at the start of mdat", gap)
        return b""

    f.seek(mdat.payload_offset)
    return f.read(gap)


def _copy_sample(f: BinaryIO, out: BinaryIO, sample: Sample) -> None:
    """Copy one sample's bytes across, a block at a time."""
    f.seek(sample.offset)
    remaining = sample.size

    while remaining > 0:
        block = f.read(min(remaining, _COPY_CHUNK))

        if not block:
            raise ValueError("Unexpected end of file while copying samples")

        out.write(block)
        remaining -= len(block)


def _write_mdat(
    f: BinaryIO,
    out: BinaryIO,
    chunks: list[_Chunk],
    prefix: bytes,
    mdat_size: int,
    header_size: int,
) -> None:
    """Write the mdat box: header, any leading padding, then the samples."""
    if header_size == 8:
        out.write(_U32.pack(mdat_size + 8) + b"mdat")
    else:
        out.write(_U32.pack(1) + b"mdat" + _U64.pack(mdat_size + 16))

    out.write(prefix)

    for chunk in chunks:
        for sample in chunk.samples:
            _copy_sample(f, out, sample)


def _top_level_layout(f: BinaryIO, mp4: Mp4File) -> list[tuple[str, bytes | None]]:
    """Plan the output's top-level boxes.

    They keep their source order; moov and mdat are the only ones that change,
    so everything else is captured as raw bytes to pass straight through.
    """
    layout: list[tuple[str, bytes | None]] = []

    for box in mp4.boxes:
        if box.type in (b"moov", b"mdat"):
            layout.append((box.type.decode("latin1"), None))
        else:
            layout.append(("raw", box.raw(f)))

    return layout


def _place_chunks(
    chunks: list[_Chunk],
    layout: list[tuple[str, bytes | None]],
    moov_size: int,
    mdat_leader: int,
) -> None:
    """Assign each chunk its offset in the file being written."""
    offset = 0

    for kind, data in layout:
        if kind == "mdat":
            break
        offset += moov_size if kind == "moov" else len(data or b"")

    running = offset + mdat_leader

    for chunk in chunks:
        chunk.new_offset = running
        running += chunk.size


def write_clipped(
    f: BinaryIO,
    mp4: Mp4File,
    ranges: list[tuple[int, int]],
    out: BinaryIO,
) -> None:
    """Write a clipped copy of the container to ``out``.

    ``ranges`` gives [first, last) sample indices per track, in mp4.tracks
    order.
    """
    clipped = [track.samples[first:last] for track, (first, last) in zip(mp4.tracks, ranges)]
    chunks = _build_chunks(mp4.tracks, clipped)

    source_mdat = next((b for b in mp4.boxes if b.type == b"mdat"), None)
    if source_mdat is None:
        raise ValueError("No mdat box found")

    mdat_prefix = _mdat_prefix(f, mp4, source_mdat)
    mdat_size = len(mdat_prefix) + sum(chunk.size for chunk in chunks)

    layout = _top_level_layout(f, mp4)
    mdat_header_size = 8 if mdat_size + 8 <= 0xFFFFFFFF else 16

    # Chunk offsets live inside moov, and moov's size decides where mdat
    # starts, so the two are mutually dependent. Sizes settle after one round;
    # loop anyway and insist that they do.
    moov = _build_moov(f, mp4, clipped, ranges, chunks)

    for _ in range(4):
        _place_chunks(chunks, layout, len(moov), mdat_header_size + len(mdat_prefix))

        rebuilt = _build_moov(f, mp4, clipped, ranges, chunks)
        settled = len(rebuilt) == len(moov)
        moov = rebuilt

        if settled:
            break
    else:
        raise ValueError("moov size did not converge")

    for kind, data in layout:
        if kind == "raw":
            out.write(data or b"")
        elif kind == "moov":
            out.write(moov)
        else:
            _write_mdat(f, out, chunks, mdat_prefix, mdat_size, mdat_header_size)
