from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class ReceivedFrame:
    session_id: str
    frame_id: int
    size_version: int
    received_at_monotonic: float
    converted_at_monotonic: float
    media_timestamp_ms: float | None
    width: int
    height: int
    bgr: np.ndarray
    source: Literal["webrtc"] = "webrtc"


class LatestFrameBuffer:
    """Use on the service event loop; never enqueue multiple pending frames."""

    def __init__(self) -> None:
        self._frame: ReceivedFrame | None = None
        self._pending = False
        self.replaced_frames = 0

    def put(self, frame: ReceivedFrame) -> None:
        if self._pending:
            self.replaced_frames += 1
        self._frame = frame
        self._pending = True

    def peek(self) -> ReceivedFrame | None:
        return self._frame

    def take(self) -> ReceivedFrame | None:
        if not self._pending:
            return None
        self._pending = False
        return self._frame

    def clear(self) -> None:
        self._frame = None
        self._pending = False
