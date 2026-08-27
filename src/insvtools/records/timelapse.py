"""Sample-to-timestamp mapping: one record per video sample."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

from .timestamped import TS_SIZE, TimestampedRecord

_TS = struct.Struct("<q")


@dataclass
class TimelapseRecord(TimestampedRecord):
    """A timestamp for one video sample."""

    SIZE: ClassVar[int] = TS_SIZE

    @classmethod
    def parse(cls, data: bytes, off: int) -> "TimelapseRecord":
        """Read a sample timestamp at ``off``."""
        (timestamp,) = _TS.unpack_from(data, off)
        return cls(timestamp)
