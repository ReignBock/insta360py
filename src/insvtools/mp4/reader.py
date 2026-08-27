"""Read MP4 sample tables.

This is the half of the cut that has to be exact: which samples fall in the
requested range, and where the nearest preceding keyframe is. The Java gets
these from mp4parser; here they come from the tables directly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

from .boxes import Box, parse_boxes

_U32 = struct.Struct(">I")
_U64 = struct.Struct(">Q")


@dataclass
class Sample:
    """One media sample: where it is, how long it lasts, whether it is a keyframe."""

    offset: int
    size: int
    duration: int
    cts_offset: int
    sync: bool
    chunk: int


@dataclass
class Track:
    """A single track and its fully expanded sample table."""

    box: Box
    handler: str
    timescale: int
    samples: list[Sample]
    # Preserved so the rewritten tables keep the original's shape.
    constant_sample_size: int
    chunk_sample_description: list[int]
    has_stss: bool
    has_ctts: bool


def _entries(payload: bytes, offset: int, count: int, fmt: struct.Struct) -> list[tuple]:
    """Unpack ``count`` fixed-size entries starting at ``offset``."""
    return list(fmt.iter_unpack(payload[offset : offset + count * fmt.size]))


def _read_stts(payload: bytes) -> list[int]:
    (count,) = _U32.unpack_from(payload, 4)
    durations: list[int] = []
    for sample_count, delta in _entries(payload, 8, count, struct.Struct(">II")):
        durations.extend([delta] * sample_count)
    return durations


def _read_ctts(payload: bytes) -> list[int]:
    version = payload[0]
    (count,) = _U32.unpack_from(payload, 4)
    fmt = struct.Struct(">Ii") if version == 1 else struct.Struct(">II")
    offsets: list[int] = []
    for sample_count, offset in _entries(payload, 8, count, fmt):
        offsets.extend([offset] * sample_count)
    return offsets


def _read_stsz(payload: bytes) -> tuple[int, list[int]]:
    sample_size, count = struct.unpack_from(">II", payload, 4)
    if sample_size != 0:
        return sample_size, [sample_size] * count
    return 0, [size for (size,) in _entries(payload, 12, count, _U32)]


def _read_stz2(payload: bytes) -> tuple[int, list[int]]:
    field_size = payload[7]
    (count,) = _U32.unpack_from(payload, 8)
    sizes: list[int] = []
    data = payload[12:]
    if field_size == 4:
        for i in range(count):
            byte = data[i // 2]
            sizes.append((byte >> 4) if i % 2 == 0 else (byte & 0x0F))
    elif field_size == 8:
        sizes = list(data[:count])
    elif field_size == 16:
        sizes = [size for (size,) in _entries(data, 0, count, struct.Struct(">H"))]
    else:
        raise ValueError(f"Unsupported stz2 field size {field_size}")
    return 0, sizes


def _read_stsc(payload: bytes) -> list[tuple[int, int, int]]:
    (count,) = _U32.unpack_from(payload, 4)
    return [tuple(e) for e in _entries(payload, 8, count, struct.Struct(">III"))]


def _read_chunk_offsets(box: Box, payload: bytes) -> list[int]:
    (count,) = _U32.unpack_from(payload, 4)
    fmt = _U64 if box.type == b"co64" else _U32
    return [offset for (offset,) in _entries(payload, 8, count, fmt)]


def _read_stss(payload: bytes) -> set[int]:
    (count,) = _U32.unpack_from(payload, 4)
    return {number for (number,) in _entries(payload, 8, count, _U32)}


def _expand_samples(
    sizes: list[int],
    durations: list[int],
    cts_offsets: list[int] | None,
    sync_samples: set[int] | None,
    stsc_entries: list[tuple[int, int, int]],
    chunk_offsets: list[int],
) -> tuple[list[Sample], list[int]]:
    """Flatten the sample-to-chunk table into one entry per sample.

    stsc stores runs of chunks that share a sample count, so this walks those
    runs and hands back the samples plus each chunk's sample-description index.
    """
    samples: list[Sample] = []
    chunk_sample_description: list[int] = []
    sample_index = 0

    for entry_index, (first_chunk, samples_per_chunk, sdi) in enumerate(stsc_entries):
        last_chunk = (
            stsc_entries[entry_index + 1][0] - 1
            if entry_index + 1 < len(stsc_entries)
            else len(chunk_offsets)
        )

        for chunk in range(first_chunk, last_chunk + 1):
            if chunk > len(chunk_offsets):
                break

            offset = chunk_offsets[chunk - 1]
            chunk_sample_description.append(sdi)

            for _ in range(samples_per_chunk):
                if sample_index >= len(sizes):
                    break

                # stss is 1-based; no stss at all means every sample is a
                # sync sample.
                is_sync = sync_samples is None or sample_index + 1 in sync_samples

                samples.append(
                    Sample(
                        offset=offset,
                        size=sizes[sample_index],
                        duration=durations[sample_index] if sample_index < len(durations) else 0,
                        cts_offset=cts_offsets[sample_index] if cts_offsets else 0,
                        sync=is_sync,
                        chunk=chunk - 1,
                    )
                )
                offset += sizes[sample_index]
                sample_index += 1

    return samples, chunk_sample_description


def _read_track(f: BinaryIO, trak: Box) -> Track:
    mdia = trak.find(b"mdia")
    if mdia is None:
        raise ValueError("trak without mdia")

    mdhd = mdia.find(b"mdhd")
    hdlr = mdia.find(b"hdlr")
    stbl = mdia.find(b"minf", b"stbl")
    if mdhd is None or hdlr is None or stbl is None:
        raise ValueError("trak missing mdhd, hdlr or stbl")

    mdhd_payload = mdhd.payload(f)
    timescale = (
        _U32.unpack_from(mdhd_payload, 20)[0]
        if mdhd_payload[0] == 1
        else _U32.unpack_from(mdhd_payload, 12)[0]
    )

    handler = hdlr.payload(f)[8:12].decode("latin1")

    stts = stbl.find(b"stts")
    stsz = stbl.find(b"stsz") or stbl.find(b"stz2")
    stsc = stbl.find(b"stsc")
    stco = stbl.find(b"stco") or stbl.find(b"co64")
    stss = stbl.find(b"stss")
    ctts = stbl.find(b"ctts")

    if stts is None or stsz is None or stsc is None or stco is None:
        raise ValueError("stbl missing a required table")

    durations = _read_stts(stts.payload(f))
    if stsz.type == b"stsz":
        constant_size, sizes = _read_stsz(stsz.payload(f))
    else:
        constant_size, sizes = _read_stz2(stsz.payload(f))
    stsc_entries = _read_stsc(stsc.payload(f))
    chunk_offsets = _read_chunk_offsets(stco, stco.payload(f))
    sync_samples = _read_stss(stss.payload(f)) if stss is not None else None
    cts_offsets = _read_ctts(ctts.payload(f)) if ctts is not None else None

    samples, chunk_sample_description = _expand_samples(
        sizes, durations, cts_offsets, sync_samples, stsc_entries, chunk_offsets
    )

    return Track(
        box=trak,
        handler=handler,
        timescale=timescale,
        samples=samples,
        constant_sample_size=constant_size,
        chunk_sample_description=chunk_sample_description,
        has_stss=sync_samples is not None,
        has_ctts=cts_offsets is not None,
    )


@dataclass
class Mp4File:
    """A parsed container: its box tree and its tracks."""

    boxes: list[Box]
    moov: Box
    tracks: list[Track]
    movie_timescale: int
    limit: int

    @classmethod
    def read(cls, f: BinaryIO, limit: int | None = None) -> "Mp4File":
        """Parse the container, ignoring anything at or after ``limit``."""
        if limit is None:
            f.seek(0, 2)
            limit = f.tell()

        boxes = parse_boxes(f, 0, limit)
        moov = next((b for b in boxes if b.type == b"moov"), None)

        if moov is None:
            raise ValueError("No moov box found")

        mvhd = moov.find(b"mvhd")
        if mvhd is None:
            raise ValueError("No mvhd box found")

        mvhd_payload = mvhd.payload(f)
        movie_timescale = (
            _U32.unpack_from(mvhd_payload, 20)[0]
            if mvhd_payload[0] == 1
            else _U32.unpack_from(mvhd_payload, 12)[0]
        )

        tracks = [_read_track(f, trak) for trak in moov.find_all(b"trak")]

        return cls(boxes, moov, tracks, movie_timescale, limit)
