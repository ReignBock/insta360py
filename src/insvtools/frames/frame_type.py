"""Port of org.insvtools.frames.FrameType."""

from __future__ import annotations

from enum import IntEnum


class FrameType(IntEnum):
    """Metadata frame types.

    Codes are stored as a *signed* byte in the frame header, which is why RAW
    is -1: it is a synthetic type used for stretches of the trailer that are
    not covered by any real frame, so they can be reproduced verbatim.
    """

    RAW = -1
    INDEX = 0
    INFO = 1
    THUMBNAIL = 2
    GYRO = 3
    EXPOSURE = 4
    THUMBNAIL_EXT = 5
    TIMELAPSE = 6
    GPS = 7
    STAR_NUM = 8
    THREE_A_IN_TIMESTAMP = 9
    ANCHORS = 10
    THREE_A_SIMULATION = 11
    EXPOSURE_SECONDARY = 12
    MAGNETIC = 13
    EULER = 14
    GYRO_SECONDARY = 15
    SPEED = 16
    TBOX = 17
    EDITOR = 18
    HEARTRATE = 19
    FORWARD_DIRECTION = 20
    UPVIEW = 21
    SHELL_RECOGNITION_DATA = 22
    POS = 23
    TIMELAPSE_QUAT = 24

    @classmethod
    def from_code(cls, code: int) -> "FrameType | None":
        """Return the type for ``code``, or None for codes we don't know.

        Unknown codes are not an error: such frames are carried through as
        opaque payloads so that writing the file back preserves them.
        """
        try:
            return cls(code)
        except ValueError:
            return None
