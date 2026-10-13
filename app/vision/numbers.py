"""Parse OCR current/total values independently from colored bar estimates."""

import re
import unicodedata
from typing import Literal

import numpy as np

from app.vision.models import NameReading, NumericReading, VisionProfile
from app.vision.names import PlayerNameReader

INTEGER_PATTERN = r"(?:[0-9]{1,10}|[0-9]{1,3}(?:,[0-9]{3}){1,3})"
_PAIR = re.compile(rf"({INTEGER_PATTERN})/({INTEGER_PATTERN})")


def parse_values(reading: NameReading, kind: Literal["hp", "mp"]) -> NumericReading:
    values = reading.model_dump()
    if reading.status != "known":
        return NumericReading(**values)
    text = "".join(unicodedata.normalize("NFKC", reading.text or "").split())
    if text.upper().startswith(kind.upper()):
        text = text[2:]
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    match = _PAIR.fullmatch(text)
    reason = "invalid_number_format"
    if match:
        current, total = (int(item.replace(",", "")) for item in match.groups())
        if 0 <= current <= total <= 9_999_999_999 and total > 0:
            return NumericReading(
                **values, current=current, total=total, ratio=round(current / total, 4),
            )
        reason = "invalid_number_range"
    values.update(status="unknown", text=None, reason=reason)
    return NumericReading(**values)


def read_values(
    reader: PlayerNameReader, bgr: np.ndarray, profile: VisionProfile,
    kind: Literal["hp", "mp"],
) -> NumericReading:
    roi = profile.hp_text if kind == "hp" else profile.mp_text
    reading = reader.read_region(bgr, profile, roi, profile.numbers_min_confidence)
    return parse_values(reading, kind)
