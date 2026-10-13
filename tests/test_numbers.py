"""OCR parsing tests and response stubs, not real model accuracy measurements."""

import numpy as np
import pytest

from app.vision.models import NameReading, Rect, VisionProfile
from app.vision.names import PlayerNameReader
from app.vision.numbers import parse_values, read_values


@pytest.mark.parametrize(
    ("text", "current", "total"),
    [
        ("2534/3711", 2534, 3711),
        ("HP [0/100]", 0, 100),
        ("100/100", 100, 100),
        ("ＨＰ［１，２３４／５，６７８］", 1234, 5678),
        (" 48 / 513 ", 48, 513),
    ],
)
def test_parse_current_total_and_ratio(text, current, total):
    source = NameReading(status="known", text=text, raw_text=text, confidence=0.95)
    reading = parse_values(source, "hp")
    assert reading.status == "known"
    assert (reading.current, reading.total) == (current, total)
    assert reading.ratio == pytest.approx(current / total, abs=0.00005)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("12/0", "invalid_number_range"),
        ("101/100", "invalid_number_range"),
        ("999,999,999,999/999,999,999,999", "invalid_number_range"),
        ("-1/100", "invalid_number_format"),
        ("1.5/100", "invalid_number_format"),
        ("10O/100", "invalid_number_format"),
        ("1,23/100", "invalid_number_format"),
        ("MP [10/100]", "invalid_number_format"),
        ("[10/100", "invalid_number_format"),
        ("10/100 extra", "invalid_number_format"),
    ],
)
def test_invalid_numbers_remain_unknown(text, reason):
    source = NameReading(status="known", text=text, raw_text=text, confidence=0.99)
    reading = parse_values(source, "hp")
    assert reading.status == "unknown"
    assert reading.reason == reason
    assert reading.current is reading.total is reading.ratio is reading.text is None
    assert reading.raw_text == text


def test_low_confidence_does_not_become_a_numeric_reading(monkeypatch):
    def fake_ocr(_pixels, **_options):
        return [[[], "25/100", 0.7]], [0.01]

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fake_ocr)
    selected = VisionProfile(
        reference_size=(120, 40), hp_text=Rect(x=0, y=0, width=120, height=20),
        numbers_min_confidence=0.8,
    )
    reading = read_values(PlayerNameReader(), np.zeros((40, 120, 3), dtype=np.uint8),
                          selected, "hp")
    assert reading.reason == "low_confidence"
    assert reading.raw_text == "25/100"
    assert reading.current is reading.total is reading.ratio is None


def test_old_profile_has_unknown_numeric_values_without_loading_ocr(monkeypatch):
    def unexpected_load(_):
        pytest.fail("Missing numeric regions must not load OCR")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", unexpected_load)
    image = np.zeros((40, 120, 3), dtype=np.uint8)
    selected = VisionProfile(reference_size=(120, 40))
    for kind in ("hp", "mp"):
        reading = read_values(PlayerNameReader(), image, selected, kind)
        assert reading.reason == "region_not_configured"
        assert reading.current is reading.total is None
