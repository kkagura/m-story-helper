"""Read character UI fields without guessing missing values from percentages."""

import re
import unicodedata

import numpy as np

from app.vision.models import ExperienceReading, LevelReading, NameReading, VisionProfile
from app.vision.names import PlayerNameReader
from app.vision.numbers import INTEGER_PATTERN

_LEVEL = re.compile(r"(?:LV\.?)?([0-9]{1,4})", re.IGNORECASE)
_PERCENT = r"([0-9]{1,3}(?:\.[0-9]{1,4})?)"
_EXPERIENCE = re.compile(rf"({INTEGER_PATTERN})(?:\[{_PERCENT}%\]|\({_PERCENT}%\))")


def normalize(text: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", text or "").split())


def parse_level(reading: NameReading) -> LevelReading:
    data = reading.model_dump()
    if reading.status != "known":
        return LevelReading(**data)
    match = _LEVEL.fullmatch(normalize(reading.text))
    if match and int(match[1]) > 0:
        return LevelReading(**data, value=int(match[1]))
    data.update(status="unknown", text=None, reason="invalid_level")
    return LevelReading(**data)


def parse_job(reading: NameReading) -> NameReading:
    if reading.status != "known":
        return reading
    text = unicodedata.normalize("NFKC", reading.text or "").strip()
    if (
        1 <= len(text) <= 32 and any(char.isalpha() for char in text)
        and not any(char.isdigit() or char in "/%[]()" for char in text)
    ):
        return reading.model_copy(update={"text": text})
    return reading.model_copy(update={"status": "unknown", "text": None, "reason": "invalid_job"})


def parse_experience(reading: NameReading) -> ExperienceReading:
    data = reading.model_dump()
    if reading.status != "known":
        return ExperienceReading(**data)
    text = normalize(reading.text)
    if text.upper().startswith("EXP"):
        text = text[3:]
    match = _EXPERIENCE.fullmatch(text)
    reason = "invalid_experience_format"
    if match:
        value = int(match[1].replace(",", ""))
        percentage = float(match[2] if match[2] is not None else match[3])
        if value <= 9_999_999_999 and 0 <= percentage <= 100:
            return ExperienceReading(**data, value=value, percentage=percentage)
        reason = "invalid_experience_range"
    data.update(status="unknown", text=None, reason=reason)
    return ExperienceReading(**data)


def read_character(
    reader: PlayerNameReader, bgr: np.ndarray, profile: VisionProfile,
) -> tuple[LevelReading, NameReading, ExperienceReading]:
    level = reader.read_region(
        bgr, profile, profile.player_level, profile.player_level_min_confidence,
    )
    job = reader.read_region(bgr, profile, profile.player_job, profile.player_name_min_confidence)
    exp = reader.read_region(bgr, profile, profile.exp_text, profile.numbers_min_confidence)
    return parse_level(level), parse_job(job), parse_experience(exp)
