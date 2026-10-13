"""Character field parsing/stub tests, separate from real OCR acceptance."""

import numpy as np
import pytest

from app.vision.character import parse_experience, parse_job, parse_level, read_character
from app.vision.models import NameReading, Rect, VisionProfile
from app.vision.names import PlayerNameReader


def recognized(text):
    return NameReading(status="known", text=text, raw_text=text, confidence=0.95)


@pytest.mark.parametrize("text", ["55", "LV. 55", "ＬＶ．５５"])
def test_level_integer(text):
    assert parse_level(recognized(text)).value == 55


@pytest.mark.parametrize("text", ["0", "-1", "5S", "55/100", "10000", "55.5"])
def test_invalid_level(text):
    result = parse_level(recognized(text))
    assert result.value is None
    assert result.reason == "invalid_level"
    assert result.raw_text == text


@pytest.mark.parametrize(
    ("text", "value", "percentage"),
    [("503851[54.37%]", 503851, 54.37), ("ＥＸＰ ５０３，８５１［５４．３７％］", 503851, 54.37),
     ("0(0%)", 0, 0), ("100[100%]", 100, 100)],
)
def test_experience_value_and_displayed_percentage(text, value, percentage):
    result = parse_experience(recognized(text))
    assert (result.value, result.percentage) == (value, percentage)
    assert result.status == "known"


@pytest.mark.parametrize(
    "text", ["503851", "[54.37%]", "10[101%]", "-1[0%]", "10[-1%]",
             "10[1.1%)", "1O[1%]", "999,999,999,999[1%]"],
)
def test_invalid_experience_never_infers_missing_fields(text):
    result = parse_experience(recognized(text))
    assert result.status == "unknown"
    assert result.value is result.percentage is None
    assert result.raw_text == text


def test_job_text_is_not_a_numeric_reading():
    assert parse_job(recognized("剑客")).text == "剑客"
    assert parse_job(recognized("Arch Mage")).text == "Arch Mage"
    for text in ("55", "剑客55", "55/100", "", "剑" * 33):
        result = parse_job(recognized(text))
        assert result.status == "unknown"
        assert result.reason == "invalid_job"


def test_unknown_ocr_is_not_promoted_to_known():
    source = NameReading(status="unknown", raw_text="55", confidence=0.4, reason="low_confidence")
    for parse in (parse_level, parse_job, parse_experience):
        result = parse(source)
        assert result.status == "unknown"
        assert result.reason == "low_confidence"


def test_character_reads_share_engine_and_fail_independently(monkeypatch):
    loads = []
    texts = iter(["5S", "剑客", "503851[54.37%]"])

    def fake_ocr(_pixels, **_options):
        return [[[], next(texts), 0.99]], [0.01]

    def load(_):
        loads.append(True)
        return fake_ocr

    monkeypatch.setattr(PlayerNameReader, "_create_engine", load)
    roi = Rect(x=0, y=0, width=100, height=20)
    selected = VisionProfile(
        reference_size=(100, 20), player_level=roi, player_job=roi, exp_text=roi,
    )
    level, job, exp = read_character(
        PlayerNameReader(), np.zeros((20, 100, 3), dtype=np.uint8), selected,
    )
    assert level.status == "unknown"
    assert job.text == "剑客"
    assert exp.value == 503851
    assert len(loads) == 1


def test_legacy_profile_skips_ocr(monkeypatch):
    def unexpected_load(_):
        pytest.fail("Missing regions must not load OCR")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", unexpected_load)
    results = read_character(
        PlayerNameReader(), np.zeros((20, 100, 3), dtype=np.uint8),
        VisionProfile(reference_size=(100, 20)),
    )
    assert all(item.status == "unknown" and item.reason == "region_not_configured"
               for item in results)


@pytest.mark.parametrize("score", [0.599, 0.6, 0.678712785243988])
def test_level_threshold_is_independent_and_inclusive(monkeypatch, score):
    texts = iter(["55", "剑客", "503851[54.37%]"])

    def fake_ocr(_pixels, **_options):
        return [[[], next(texts), score]], [0.01]

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fake_ocr)
    roi = Rect(x=0, y=0, width=100, height=20)
    selected = VisionProfile(
        reference_size=(100, 20), player_level=roi, player_job=roi, exp_text=roi,
        numbers_min_confidence=0.9, player_name_min_confidence=0.95,
    )
    assert selected.player_level_min_confidence == 0.6
    level, job, exp = read_character(
        PlayerNameReader(), np.zeros((20, 100, 3), dtype=np.uint8), selected,
    )
    if score >= 0.6:
        assert level.value == 55
        assert level.status == "known"
    else:
        assert level.value is None
        assert level.reason == "low_confidence"
    assert job.reason == exp.reason == "low_confidence"
