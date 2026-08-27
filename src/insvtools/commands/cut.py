"""Cut an .insv to a time range, rewriting the metadata trailer to match."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, NamedTuple

from ..frames.info_frame import InfoFrame
from ..frames.timelapse_frame import TimelapseFrame
from ..header import InsvHeader
from ..metadata import InsvMetadata, read_metadata_optional
from ..mp4.reader import Mp4File, Track
from ..mp4.writer import write_clipped

logger = logging.getLogger(__name__)

VIDEO_HANDLER_TYPE = "vide"

# {prefix}{VID|LRV}_{yyyyMMdd_HHmmss}_{NN}_{nnn}.{ext}
_INSV_FILE_PATTERN = re.compile(r"(\w*)(VID|LRV)_(\d{8}_\d{6})_\d\d_(\d+)\.(\w+)")


class VideoRange(NamedTuple):
    """The video track's clip, which the TIMELAPSE records are indexed by."""

    first_sample: int
    last_sample: int
    start_time: float
    end_time: float


def cut_file_for(main_file: Path, out_file: str | None, file: Path) -> Path:
    """Derive the output name for one file of a group.

    With no ``out_file`` a '.cut' infix is added. With one, the main file takes
    it verbatim and siblings have the main file's stem substituted for their
    own - but only when the given name actually contains that stem, otherwise
    siblings just land in the same directory.
    """
    if file.name == main_file.name and out_file is not None:
        return Path(out_file)

    if out_file is None:
        return Path(f"{file.stem}.cut{file.suffix}")

    if main_file.stem not in out_file:
        return Path(out_file).parent / f"{file.stem}.cut{file.suffix}"

    return Path(out_file.replace(main_file.stem, file.stem))


def files_to_process(
    main_file: Path,
    out_file: str | None = None,
    group: bool = True,
    listing: Iterable[Path] | None = None,
) -> dict[Path, Path]:
    """Map each input file of the recording to its output file.

    One recording produces several files - one per lens plus a low-res proxy -
    which must all be cut at the same point. They share a prefix, a timestamp
    and a trailing number; .insv and .lrv are interchangeable.

    ``listing`` is the set of candidate siblings, defaulting to the main file's
    directory.
    """
    matcher = _INSV_FILE_PATTERN.fullmatch(main_file.name)

    if not group or matcher is None:
        return {main_file: cut_file_for(main_file, out_file, main_file)}

    prefix, _, date_time, num, ext = matcher.groups()

    if ext in ("insv", "lrv"):
        ext = "(insv|lrv)"

    pattern = re.compile(
        re.escape(prefix) + r"(VID|LRV)_" + date_time + r"_\d\d_" + num + r"\." + ext
    )

    if listing is None:
        listing = main_file.absolute().parent.iterdir()

    return {
        file: cut_file_for(main_file, out_file, file)
        for file in listing
        if pattern.fullmatch(file.name)
    }


def sync_sample_time(track: Track, time: float) -> float:
    """The start time of the last sync sample at or before ``time``.

    Decoding can only begin at a sync sample, so a cut point moves backwards
    to one.
    """
    previous_sync_time = 0.0
    current_time = 0.0
    found = False

    for sample in track.samples:
        if sample.sync:
            if current_time > time:
                return previous_sync_time
            previous_sync_time = current_time
            found = True
        current_time += sample.duration / track.timescale

    if not found or current_time < time:
        raise ValueError("Start time is more than track length")

    return previous_sync_time


def _snap_to_keyframe(mp4: Mp4File, start_time: float, end_time: float | None) -> float:
    """Snap the start back to a keyframe every track agrees on."""
    snapped = start_time
    adjusted = False

    for track in mp4.tracks:
        if not track.has_stss or not any(s.sync for s in track.samples):
            continue

        candidate = sync_sample_time(track, snapped)

        if adjusted:
            if candidate != snapped:
                raise ValueError(
                    "The start time has already been adjusted by another track with "
                    "sync samples. All tracks must share the same point of cut."
                )
            continue

        if end_time is not None and candidate > end_time:
            raise ValueError("End time is more than adjusted start time")

        logger.debug("Start time adjusted by sync samples to %s", candidate)
        snapped = candidate
        adjusted = True

    return snapped


def _sample_ranges(
    mp4: Mp4File, start_time: float, end_time: float | None
) -> tuple[list[tuple[int, int]], VideoRange]:
    """Pick [first, last) per track, and report the video track's range."""
    ranges: list[tuple[int, int]] = []
    video = VideoRange(-1, -1, -1.0, -1.0)

    for track in mp4.tracks:
        current_time = 0.0
        first_sample = -1
        first_sample_time = -1.0
        last_sample = -1
        last_sample_time = -1.0

        for index, sample in enumerate(track.samples):
            if current_time <= start_time:
                first_sample_time = current_time
                first_sample = index

            if end_time is not None and current_time >= end_time:
                last_sample = index
                last_sample_time = current_time
                break

            current_time += sample.duration / track.timescale

        if first_sample < 0:
            raise ValueError(f"Can't find first sample for time {start_time}")

        if last_sample < 0:
            last_sample = len(track.samples)
            last_sample_time = current_time

        ranges.append((first_sample, last_sample))

        logger.debug(
            "Track (%s) clipped to samples [%d, %d)", track.handler, first_sample, last_sample
        )

        if track.handler == VIDEO_HANDLER_TYPE:
            video = VideoRange(first_sample, last_sample, first_sample_time, last_sample_time)

    return ranges, video


def _update_metadata(
    metadata: InsvMetadata,
    start_time: float,
    container_size: int,
    video: VideoRange,
    timestamp_scale: int,
) -> None:
    info = metadata.find_frame_of(InfoFrame)

    # extra_metadata stays None for an INFO frame that did not parse (a JSON
    # frame, or a protobuf we could not read); there is nothing to patch then.
    if info is None or info.extra_metadata is None:
        return

    extra = info.extra_metadata
    scale = timestamp_scale

    if scale == 0:
        # A firmware update moved timestamps from millis to micros without
        # flagging it anywhere; upstream reads the sign of GyroTimestamp,
        # which appears to correlate.
        scale = 1_000 if extra.GyroTimestamp < 0 else 1_000_000

    extra.FileSize = container_size
    extra.FirstFrameTimestamp += int(start_time * scale)
    extra.TotalTime = round(video.end_time - video.start_time)
    # FirstGpsTimestamp is always in millis, whatever scale the rest uses.
    extra.FirstGpsTimestamp += int(start_time * 1000)

    timelapse = metadata.find_frame_of(TimelapseFrame)

    # Timelapse holds one record per video sample, so dropping samples means
    # dropping the matching records.
    if timelapse is not None and video.first_sample >= 0:
        timelapse.records[:] = timelapse.records[video.first_sample : video.last_sample]


def cut_one(
    source: Path,
    target: Path,
    start_time: float = 0.0,
    end_time: float | None = None,
    timestamp_scale: int = 0,
) -> None:
    """Cut a single file. The partial output is removed if anything fails."""
    try:
        with source.open("rb") as f:
            header = InsvHeader.read(f)
            mp4 = Mp4File.read(f, header.metadata_pos if header else None)

            start_time = _snap_to_keyframe(mp4, start_time, end_time)
            ranges, video = _sample_ranges(mp4, start_time, end_time)

            metadata = read_metadata_optional(source)

            if metadata is not None:
                metadata.parse()
                logger.debug("Found INSV metadata with %d frames", len(metadata.frames))

            with target.open("wb") as out:
                write_clipped(f, mp4, ranges, out)

                if metadata is not None:
                    _update_metadata(
                        metadata, start_time, out.tell(), video, timestamp_scale
                    )
                    metadata.write(out)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def cut(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    file_name: str,
    out_file: str | None = None,
    start_time: float = 0.0,
    end_time: float | None = None,
    timestamp_scale: int = 0,
    group: bool = True,
) -> None:
    """Cut a file, and by default the whole group of files it belongs to.

    Every argument here is a distinct user-facing option, so they are passed
    individually rather than bundled into a settings object.
    """
    main_file = Path(file_name)

    if not main_file.exists():
        raise FileNotFoundError(f"File {file_name} not found")

    targets = files_to_process(main_file, out_file, group)

    for target in targets.values():
        if target.exists():
            raise FileExistsError(f"File {target} already exists")

    for source, target in targets.items():
        logger.info("Processing %s -> %s", source.name, target.name)
        cut_one(source, target, start_time, end_time, timestamp_scale)
