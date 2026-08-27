"""Port of org.insvtools.InsvTools - the command line entry point.

The argument contract is upstream's, not argparse's: the file name is always
last, parameters are strictly ``--key=value`` (never space separated), and an
unrecognised parameter is an error rather than something to ignore.
"""

from __future__ import annotations

import re
import sys

from .logger import get_logger

logger = get_logger(__name__)

_TIME_PATTERN = re.compile(r"((\d+):)?((\d+)(\.\d+)?)")

USAGE = """InsvTools v.{version}
Toolkit for working with Insta360 cameras video files
Usage (jar):    java -jar insvtools.jar <cmd> [parameters] <filename>
Usage (native): insvtools <cmd> [parameters] <filename>
Available commands and parameters:
    cut                             - cut the file using start time and/or end time
        [--start-time=<time>]       - start time in format [MM:]SS[.SSS]
        [--end-time=<time>]         - end time in format [MM:]SS[.SSS]
        [--timestamp-scale=<scale>] - Gyro records timestamp scale (autodetect by default)
        [--group=<true/false>]      - process the whole group of files related to specified file (true by default)
        [--out-file=<filename>]     - use specified output file (by default 'cut' suffix will be added to the original file name)

    dump-meta                       - dump insv file metadata
        [--frame-type=<frame-type>] - dump only specified integer frame type (by default all frames will be dumped)
        [--dump-file=<filename>]    - dump file name (by default 'meta.json' suffix will be added to the original file name)

    decompose-meta                  - store insv file metadata to file-per-frame
        [--frame-type=<frame-type>] - store only specified integer frame type (by default all frames will be stored)

    compose-meta                    - compose file-per-frame metadata to the insv file

    remove-meta                     - remove insv file metadata

    extract-meta                    - extract insv file metadata as one file
        [--meta-file=<filename>]    - metadata file name (by default 'meta' suffix will be added to the original file name)

    replace-meta                    - replace insv file metadata with another from file
        [--meta-file=<filename>]    - metadata file name (by default 'meta' suffix will be added to the original file name)"""


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("insta360py")
    except Exception:
        return "unknown"


def parse_time(time: str | None) -> float:
    """Parse ``[MM:]SS[.SSS]`` into seconds."""
    if time is None:
        return 0.0

    matcher = _TIME_PATTERN.fullmatch(time)

    if matcher is None:
        raise ValueError(f"Can't parse time {time}")

    minutes = matcher.group(2)
    seconds = matcher.group(3)

    return (0.0 if minutes is None else int(minutes) * 60.0) + float(seconds)


def _build_command(cmd_name: str, file_name: str, parameters: dict[str, str]):
    if cmd_name == "dump-meta":
        from .commands.meta_dump import MetaDumpCommand

        frame_type = parameters.pop("--frame-type", None)
        dump_file_name = parameters.pop("--dump-file", None)
        return MetaDumpCommand(file_name, 0 if frame_type is None else int(frame_type), dump_file_name)

    if cmd_name == "decompose-meta":
        from .commands.meta_decompose import MetaDecomposeCommand

        frame_type = parameters.pop("--frame-type", None)
        return MetaDecomposeCommand(file_name, 0 if frame_type is None else int(frame_type))

    if cmd_name == "compose-meta":
        from .commands.meta_compose import MetaComposeCommand

        return MetaComposeCommand(file_name)

    if cmd_name == "remove-meta":
        from .commands.meta_remove import MetaRemoveCommand

        return MetaRemoveCommand(file_name)

    if cmd_name == "extract-meta":
        from .commands.meta_extract import MetaExtractCommand

        return MetaExtractCommand(file_name, parameters.pop("--meta-file", None))

    if cmd_name == "replace-meta":
        from .commands.meta_replace import MetaReplaceCommand

        return MetaReplaceCommand(file_name, parameters.pop("--meta-file", None))

    if cmd_name == "cut":
        from .commands.cut import CutCommand

        start_time = parameters.pop("--start-time", None)
        end_time = parameters.pop("--end-time", None)
        group_flag = parameters.pop("--group", None)
        cut_file_name = parameters.pop("--out-file", None)
        timestamp_scale = parameters.pop("--timestamp-scale", None)

        group_of_files = group_flag is None or group_flag.lower() == "true"
        scale = 0 if timestamp_scale is None else int(timestamp_scale)

        if start_time is None and end_time is None:
            raise ValueError(
                "At least one parameter (--start-time or --end-time) should be specified"
            )

        return CutCommand(
            file_name,
            cut_file_name,
            parse_time(start_time),
            parse_time(end_time),
            scale,
            group_of_files,
        )

    return None


def run(*args: str) -> int:
    version = _version()

    if len(args) < 2:
        print(USAGE.format(version=version))
        return 0

    try:
        cmd_name = args[0]
        file_name = args[-1]
        parameters: dict[str, str] = {}

        for arg in args[1:-1]:
            if "=" in arg:
                key, _, value = arg.partition("=")
                parameters[key] = value
            else:
                raise ValueError(
                    f"Can't parse parameter: '{arg}', expected format: --parameter=value"
                )

        cmd = _build_command(cmd_name, file_name, parameters)

        if cmd is None:
            raise ValueError(f"Unknown command {cmd_name}")

        if parameters:
            raise ValueError(f"Unknown parameter(s): {set(parameters)}")

        logger.debug("Command line arguments: " + " ".join(args))
        logger.info(f"InsvTools v.{version}, start processing '{cmd_name}' command")
        cmd.run()
        logger.info("Processed successfully")

        return 0
    except Exception as e:  # noqa: BLE001 - upstream reports every failure the same way
        logger.error(f"Failure: {e}", e)

        return -1


def main() -> None:
    sys.exit(run(*sys.argv[1:]))
