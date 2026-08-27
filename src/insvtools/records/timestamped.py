"""Base for the records that all begin with an int64 timestamp."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar

TS_SIZE = 8
_TS = struct.Struct("<q")


@dataclass
class TimestampedRecord:
    """Common head of every record type: an int64 timestamp."""

    timestamp: int

    SIZE: ClassVar[int] = TS_SIZE

    def to_bytes(self) -> bytes:
        """Serialize back to the on-disk form."""
        return _TS.pack(self.timestamp)
