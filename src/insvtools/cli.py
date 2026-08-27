"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Sequence

from .commands import cut as cut_commands
from .commands import meta

logger = logging.getLogger(__name__)

_TIME_PATTERN = re.compile(r"((\d+):)?((\d+)(\.\d+)?)")


def _version() -> str:
    try:
        return version("insta360py")
    except PackageNotFoundError:
        return "unknown"


def parse_time(text: str) -> float:
    """Parse ``[MM:]SS[.SSS]`` into seconds."""
    matcher = _TIME_PATTERN.fullmatch(text)

    if matcher is None:
        raise argparse.ArgumentTypeError(f"Can't parse time {text!r}, expected [MM:]SS[.SSS]")

    minutes, seconds = matcher.group(2), matcher.group(3)

    return (0.0 if minutes is None else int(minutes) * 60.0) + float(seconds)


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser, one subparser per command."""
    parser = argparse.ArgumentParser(
        prog="insvtools",
        description="Toolkit for working with Insta360 camera video files",
    )
    parser.add_argument("--version", action="version", version=f"insvtools {_version()}")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log what is happening in detail"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only report problems")

    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def command(name: str, help_text: str, handler) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        sub.set_defaults(handler=handler)
        sub.add_argument("file_name", metavar="FILE", help="input .insv file")
        return sub

    cut = command("cut", "cut the file using start and/or end time", cut_commands.cut)
    # Defaults stay None so an explicit --start-time=0 differs from omitting it.
    cut.add_argument("--start-time", type=parse_time, metavar="TIME",
                     help="start time, as [MM:]SS[.SSS]")
    cut.add_argument("--end-time", type=parse_time, metavar="TIME",
                     help="end time, as [MM:]SS[.SSS]")
    cut.add_argument("--timestamp-scale", type=int, metavar="N",
                     help="gyro timestamp scale (autodetected by default)")
    cut.add_argument("--out-file", metavar="PATH",
                     help="output file (default: a '.cut' suffix on the input name)")
    cut.add_argument("--no-group", dest="group", action="store_false",
                     help="process only this file, not the whole recording")

    dump = command("dump-meta", "dump metadata as JSON", meta.dump_meta)
    dump.add_argument("--frame-type", type=int, metavar="N",
                      help="dump only this frame type (default: all)")
    dump.add_argument("--dump-file", dest="out_file", metavar="PATH",
                      help="output file (default: a '.meta.json' suffix on the input name)")

    decompose = command("decompose-meta", "write one file per metadata frame",
                        meta.decompose_meta)
    decompose.add_argument("--frame-type", type=int, metavar="N",
                           help="store only this frame type (default: all)")

    command("compose-meta", "rebuild a trailer from per-frame files", meta.compose_meta)
    command("remove-meta", "strip the metadata trailer", meta.remove_meta)

    extract = command("extract-meta", "copy the metadata trailer to its own file",
                      meta.extract_meta)
    extract.add_argument("--meta-file", metavar="PATH",
                         help="output file (default: a '.meta' suffix on the input name)")

    replace = command("replace-meta", "replace the metadata trailer from a file",
                      meta.replace_meta)
    replace.add_argument("--meta-file", metavar="PATH",
                         help="input file (default: a '.meta' suffix on the input name)")

    return parser


def _configure_logging(verbose: bool, quiet: bool) -> None:
    """Send progress to stderr, so stdout stays free for real output."""
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr, force=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose, args.quiet)

    handler = args.handler
    options = {
        key: value
        for key, value in vars(args).items()
        if key not in {"command", "handler", "verbose", "quiet"} and value is not None
    }

    if handler is cut_commands.cut and "start_time" not in options and "end_time" not in options:
        parser.error("cut needs --start-time and/or --end-time")

    try:
        handler(**options)
    # Any failure from here is a user-facing error, not a crash: the CLI
    # reports it and exits non-zero.
    except Exception as e:  # pylint: disable=broad-exception-caught
        # The traceback is only interesting with -v; the message is what the
        # user needs.
        logger.debug("Command failed", exc_info=e)
        print(f"insvtools: error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
