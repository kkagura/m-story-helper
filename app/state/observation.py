from dataclasses import dataclass

from app.media.frames import ReceivedFrame
from app.vision.models import ObservationResult


@dataclass(frozen=True)
class ObservationSnapshot:
    frame: ReceivedFrame
    result: ObservationResult
