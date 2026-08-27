"""Port of org.insvtools.commands.CutCommand.

File grouping and output naming are implemented here and are independent of
how the MP4 itself gets rewritten. The remux backend lands in mp4/ and is
wired into :meth:`CutCommand.run`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable

from ..frames.frame_type import FrameType
from ..header import InsvHeader
from ..metadata import InsvMetadata
from ..mp4.reader import Mp4File, Track
from ..mp4.writer import write_clipped
from .base import AbstractCommand

VIDEO_HANDLER_TYPE = "vide"

# {prefix}{VID|LRV}_{yyyyMMdd_HHmmss}_{NN}_{nnn}.{ext}
_INSV_FILE_PATTERN = re.compile(r"(\w*)(VID|LRV)_(\d{8}_\d{6})_\d\d_(\d+)\.(\w+)")


def file_extension(file: Path) -> str:
    """The extension including its dot, or '' if there is none."""
    name = file.name
    dot_index = name.rfind(".")
    return "" if dot_index == -1 else name[dot_index:]


def _strip_suffix(text: str, suffix: str) -> str:
    return text[: -len(suffix)] if suffix and text.endswith(suffix) else text


class CutCommand(AbstractCommand):
    def __init__(
        self,
        file_name: str,
        cut_file_name: str | None,
        start_time: float,
        end_time: float,
        timestamp_scale: int,
        group_of_files: bool,
    ):
        super().__init__(file_name)
        self.main_file = Path(file_name)
        self.cut_file_name = cut_file_name
        self.start_time = start_time
        self.end_time = end_time
        self.timestamp_scale = timestamp_scale
        self.group_of_files = group_of_files

    def cut_file_for(self, file: Path) -> Path:
        """Derive the output name for one file of the group.

        With no --out-file, a '.cut' infix is added. With one, the main file
        takes it verbatim and siblings have the main file's stem substituted
        for their own - but only when the given name actually contains that
        stem; otherwise siblings just land in the same directory.
        """
        if file.name == self.main_file.name and self.cut_file_name is not None:
            return Path(self.cut_file_name)

        ext = file_extension(file)
        main_file_name_wo_ext = _strip_suffix(self.main_file.name, file_extension(self.main_file))
        file_name_wo_ext = _strip_suffix(file.name, ext)

        if self.cut_file_name is None:
            return Path(f"{file_name_wo_ext}.cut{ext}")

        if main_file_name_wo_ext not in self.cut_file_name:
            cut_dir = Path(self.cut_file_name).parent
            return cut_dir / f"{file_name_wo_ext}.cut{ext}"

        return Path(self.cut_file_name.replace(main_file_name_wo_ext, file_name_wo_ext))

    def list_files(self, accept: Callable[[Path], bool]) -> Iterable[Path]:
        """List sibling files of the main file. Overridden in tests."""
        directory = self.main_file.absolute().parent
        return [p for p in directory.iterdir() if accept(p)]

    def files_to_process(self) -> dict[Path, Path]:
        """Map each input file of the group to its output file.

        A recording produces several files - one per lens plus a low-res proxy
        - which must all be cut at the same point. They share a prefix, a
        timestamp and a trailing number; .insv and .lrv are interchangeable.
        """
        matcher = _INSV_FILE_PATTERN.fullmatch(self.main_file.name)

        if not self.group_of_files or matcher is None:
            return {self.main_file: self.cut_file_for(self.main_file)}

        prefix, _, date_time, num, ext = matcher.groups()

        if ext in ("insv", "lrv"):
            ext = "(insv|lrv)"

        group_pattern = re.compile(
            re.escape(prefix) + r"(VID|LRV)_" + date_time + r"_\d\d_" + num + r"\." + ext
        )

        files = self.list_files(lambda p: group_pattern.fullmatch(p.name) is not None)

        return {file: self.cut_file_for(file) for file in files}

    def run(self) -> None:
        if not self.main_file.exists():
            raise ValueError(f"File {self.file_name} not found")

        files_to_process = self.files_to_process()

        for cut_file in files_to_process.values():
            if cut_file.exists():
                raise ValueError(f"File {cut_file.name} already exists")

        for source, cut_file in files_to_process.items():
            self.logger.info(f"Processing {source.name} -> {cut_file.name}")

            try:
                self._cut_file(source, cut_file)
            except Exception:
                # Never leave a half-written file behind.
                try:
                    if cut_file.exists():
                        cut_file.unlink()
                except OSError:
                    pass
                raise

    def _cut_file(self, source: Path, cut_file: Path) -> None:
        with source.open("rb") as f:
            header = InsvHeader.read(f)
            limit = header.metadata_pos if header is not None else None
            mp4 = Mp4File.read(f, limit)

            start_time = self._adjust_to_sync_sample(mp4)
            ranges, video = self._sample_ranges(mp4, start_time)

            metadata = self.read_metadata_optional(source)

            if metadata is not None:
                metadata.parse()
                self.logger.debug(
                    f"Found INSV metadata [framesCount={len(metadata.frames)}]"
                )

            with cut_file.open("wb") as out:
                write_clipped(f, mp4, ranges, out)
                container_size = out.tell()

                if metadata is not None:
                    self._update_metadata(metadata, start_time, container_size, video)
                    metadata.write(out)

    def _adjust_to_sync_sample(self, mp4: Mp4File) -> float:
        """Snap the start time back to a keyframe.

        Decoding can only begin at a sync sample, so the cut point moves
        backwards to one. Every track that has a sync sample table must agree
        on where that is, otherwise the tracks would start at different times.
        """
        start_time = self.start_time
        adjusted = False

        for track in mp4.tracks:
            if not track.has_stss or not any(s.sync for s in track.samples):
                continue

            new_start_time = _sync_sample_time(track, start_time)

            if adjusted:
                if new_start_time != start_time:
                    raise ValueError(
                        "The start time has already been adjusted by another track "
                        "with sync samples or another video file. All files should "
                        "have the same point of cut (synced samples should have "
                        "intersection in this point)."
                    )
            else:
                if self.end_time > 0 and new_start_time > self.end_time:
                    raise ValueError("End time is more than adjusted start time")
                self.logger.debug(
                    f"Start time has been adjusted by sync samples to new value: "
                    f"{new_start_time}"
                )
                start_time = new_start_time
                adjusted = True

        return start_time

    def _sample_ranges(
        self, mp4: Mp4File, start_time: float
    ) -> tuple[list[tuple[int, int]], tuple[int, int, float, float]]:
        """Pick [first, last) per track, and report the video track's range.

        The video range is what the TIMELAPSE records are indexed by, so it is
        returned separately.
        """
        ranges: list[tuple[int, int]] = []
        video = (-1, -1, -1.0, -1.0)

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

                if self.end_time > 0 and current_time >= self.end_time:
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

            self.logger.debug(
                f"Track ({track.handler}) has been clipped "
                f"[firstSample={first_sample}, lastSample={last_sample}]"
            )

            if track.handler == VIDEO_HANDLER_TYPE:
                video = (first_sample, last_sample, first_sample_time, last_sample_time)

        return ranges, video

    def _update_metadata(
        self,
        metadata: InsvMetadata,
        start_time: float,
        container_size: int,
        video: tuple[int, int, float, float],
    ) -> None:
        info_frame = metadata.find_frame(FrameType.INFO)

        if info_frame is None:
            return

        extra = info_frame.extra_metadata
        scale = self.timestamp_scale

        if scale == 0:
            # A firmware update moved timestamps from millis to micros without
            # flagging it anywhere; upstream reads the sign of GyroTimestamp,
            # which appears to correlate.
            scale = 1_000 if extra.GyroTimestamp < 0 else 1_000_000

        video_start_sample, video_end_sample, video_start_time, video_end_time = video

        info_frame.set_file_size(container_size)
        info_frame.set_first_frame_timestamp(
            extra.FirstFrameTimestamp + int(start_time * scale)
        )
        info_frame.set_total_time(round(video_end_time - video_start_time))
        info_frame.set_first_gps_timestamp(
            extra.FirstGpsTimestamp + int(start_time * 1000)
        )

        timelapse_frame = metadata.find_frame(FrameType.TIMELAPSE)

        # Timelapse holds one record per video sample, so dropping samples
        # means dropping the matching records.
        if timelapse_frame is not None and video_start_sample >= 0:
            timelapse_frame.records[:] = timelapse_frame.records[
                video_start_sample:video_end_sample
            ]


def _sync_sample_time(track: Track, time: float) -> float:
    """The start time of the last sync sample at or before ``time``.

    Upstream walks the sync sample table with an off-by-one in its duration
    accumulation, which is invisible for constant-frame-rate footage (all
    known camera files) but would skew variable-rate media. This computes the
    cumulative times straight.
    """
    previous_sync_time = 0.0
    current_time = 0.0
    found = False

    for index, sample in enumerate(track.samples):
        if sample.sync:
            if current_time > time:
                return previous_sync_time
            previous_sync_time = current_time
            found = True
        current_time += sample.duration / track.timescale

    if not found or current_time < time:
        raise ValueError("Start time is more than track length")

    return previous_sync_time
