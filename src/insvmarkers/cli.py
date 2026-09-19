"""Command line surface for the marker extractor.

The PowerShell original is driven by dropping files onto a desktop shortcut;
this takes the same paths as arguments. Passing a directory picks up the video
files directly inside it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .extractor import expand_paths, format_timestamp
from .results import SessionResult, report_lines, scan
from .studio import StudioError, find_project_for_session, find_projects_dir, inject_keyframes

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed so the tests can inspect it."""
    parser = argparse.ArgumentParser(
        prog="insv-markers",
        description="Extract timeline markers from Insta360 .insv/.lrv files",
    )
    parser.add_argument(
        "paths",
        metavar="PATH",
        nargs="+",
        type=Path,
        help="video files, or directories holding them",
    )
    parser.add_argument(
        "--no-inject",
        dest="inject",
        action="store_false",
        help="only report markers; do not touch Insta360 Studio projects",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        metavar="FILE",
        help="also write the markers to a text file",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        help="Insta360 Studio footage project directory (default: from startup.ini)",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="log what is being read")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="errors only")

    return parser


def _report(result: SessionResult) -> None:
    print(f"\nSequence: {result.title} ({len(result.sequence.files)} files)")
    print("-" * 40)

    for index, seconds in enumerate(result.markers, start=1):
        print(f"Marker {index:02d} : {format_timestamp(seconds)}")


def _write_report(path: Path, lines: list[str]) -> None:
    """Write the collected report, or explain why it could not be written."""
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as error:
        print(f"[!] Could not write {path}: {error}", file=sys.stderr)
        return

    print(f"\n[+] Wrote markers to {path}")


def _inject(result: SessionResult, projects_dir: Path | None) -> None:
    """Add the markers to Studio's project, reporting why if that is not possible."""
    try:
        directory = projects_dir if projects_dir is not None else find_projects_dir()
        project = find_project_for_session(directory, result.sequence.session_id)
        added = inject_keyframes(project, list(result.markers))
    except StudioError as error:
        print(f"[i] Studio Project: {error}")
        return
    except OSError as error:
        print(f"[i] Studio Project: could not be updated: {error}")
        return

    print(f"[+] Injected {added} keyframe(s) into Insta360 Studio project.")


def main(argv: list[str] | None = None) -> int:
    """Report the markers of every session named on the command line."""
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.ERROR if args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    files = expand_paths(args.paths)

    if not files:
        print("No .insv or .lrv files found.", file=sys.stderr)
        return 1

    without_markers = 0
    report: list[str] = []

    for result in scan(files):
        if result.error is not None:
            print(f"\nSequence: {result.title}")
            print("-" * 40)
            print(f"Error: {result.error}", file=sys.stderr)
            continue

        if not result.markers:
            without_markers += 1
            continue

        _report(result)
        report.extend(report_lines(result))

        if args.inject:
            _inject(result, args.projects_dir)

    if without_markers:
        print(f"\n[i] No markers found in {without_markers} sequence(s).")

    if args.out is not None:
        _write_report(args.out, report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
