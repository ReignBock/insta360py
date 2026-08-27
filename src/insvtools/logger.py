"""Port of org.insvtools.logger.

Upstream appends every message to insvtools.log in the working directory,
while info goes to stdout and errors to stderr. That behaviour is reproduced
so the tool feels the same from a shell.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO

LOG_FILE_NAME = "insvtools.log"

_log_file: TextIO | None = None
_log_file_failed = False


def _log_stream() -> TextIO:
    global _log_file, _log_file_failed

    if _log_file is None and not _log_file_failed:
        try:
            _log_file = Path(LOG_FILE_NAME).open("a", encoding="utf-8")
        except OSError:
            print(
                "Can't create log file, all messages will be dumped to System.out",
                file=sys.stderr,
            )
            _log_file_failed = True

    return _log_file if _log_file is not None else sys.stdout


def _write(level: str, msg: str) -> None:
    stream = _log_stream()
    stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {msg}\n")
    stream.flush()


class Logger:
    def __init__(self, name: str):
        self.name = name

    def debug(self, msg: str) -> None:
        _write("DEBUG", msg)

    def info(self, msg: str) -> None:
        print(msg)
        _write("INFO ", msg)

    def error(self, msg: str, err: BaseException | None = None) -> None:
        print(msg, file=sys.stderr)
        _write("ERROR", msg)
        if err is not None:
            stream = _log_stream()
            traceback.print_exception(type(err), err, err.__traceback__, file=stream)
            stream.flush()


def get_logger(name: str) -> Logger:
    return Logger(name)
