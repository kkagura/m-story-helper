"""Scene OCR stubs verify matching and geometry, not actual game OCR accuracy."""

import numpy as np
import pytest

from app.vision.models import NameReading, Rect, VisionProfile
from app.vision.names import PlayerNameReader
from app.vision.scene import locate_name


def row(text="角色", score=0.95, x=20, y=30):
    return [[[x, y], [x + 40, y], [x + 40, y + 10], [x, y + 10]], text, score]


def run(monkeypatch, rows, **options):
    selected = VisionProfile(
        reference_size=(300, 200), scene=Rect(x=10, y=20, width=200, height=100),
        **options,
    )
    image = np.full((200, 300, 3), 100, dtype=np.uint8)
    original = image.copy()
    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: lambda *_a, **_k: (rows, []))
    result = locate_name(PlayerNameReader(), image, selected,
                         NameReading(status="known", text="角色", confidence=0.95))
    np.testing.assert_array_equal(image, original)
    return result


def test_single_exact_name_and_offset_mapping(monkeypatch):
    result = run(monkeypatch, [row("其他角色"), row(" 角色 ")])
    assert result.status == "found"
    assert result.name_bbox == (30, 50, 40, 10)
    assert result.text_count == 2


def test_ui_exclusion_and_fixed_identity_region_are_not_candidates(monkeypatch):
    result = run(monkeypatch, [row(x=5, y=5), row(x=80, y=50)],
                 scene_exclusions=(Rect(x=10, y=20, width=60, height=30),))
    assert result.status == "found"
    assert result.name_bbox == (90, 70, 40, 10)
    result = run(monkeypatch, [row()], player_name=Rect(x=30, y=50, width=40, height=10))
    assert result.status == "not_found"
    assert not result.candidates


def test_duplicates_and_low_confidence_never_produce_a_selected_position(monkeypatch):
    duplicate = run(monkeypatch, [row(), row(score=0.2, x=90)])
    assert duplicate.status == "ambiguous"
    assert duplicate.name_bbox is None
    low = run(monkeypatch, [row(score=0.7)])
    assert low.status == "unknown"
    assert low.reason == "low_confidence"
    assert low.name_bbox is None
    assert len(low.candidates) == 1


def test_substring_is_not_a_match(monkeypatch):
    result = run(monkeypatch, [row("其他角色")])
    assert result.status == "not_found"


def test_unknown_identity_and_missing_scene_skip_model(monkeypatch):
    def unexpected_load(_):
        pytest.fail("Unavailable identity/ROI must skip scene OCR")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", unexpected_load)
    image = np.zeros((200, 300, 3), dtype=np.uint8)
    selected = VisionProfile(reference_size=(300, 200))
    result = locate_name(PlayerNameReader(), image, selected, NameReading(status="unknown"))
    assert result.reason == "identity_unknown"
    result = locate_name(PlayerNameReader(), image, selected,
                         NameReading(status="known", text="角色"))
    assert result.reason == "scene_not_configured"


def test_scene_result_capacity_is_not_silently_truncated(monkeypatch):
    result = run(monkeypatch, [row()] * 257)
    assert result.reason == "scene_text_limit"
    assert result.name_bbox is None
    result = run(monkeypatch, [row()] * 33)
    assert result.reason == "scene_candidate_limit"
    assert result.name_bbox is None


def test_resized_detections_map_to_source_coordinates(monkeypatch):
    def fake_ocr(pixels, **_options):
        assert pixels.shape[:2] == (384, 1536)
        return [[[[192, 96], [384, 96], [384, 192], [192, 192]], "角色", 0.99]], []

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fake_ocr)
    selected = VisionProfile(
        reference_size=(4020, 1040), scene=Rect(x=10, y=20, width=4000, height=1000),
    )
    result = locate_name(PlayerNameReader(), np.zeros((1040, 4020, 3), dtype=np.uint8),
                         selected, NameReading(status="known", text="角色"))
    assert result.name_bbox == (510, 270, 500, 250)


def test_non_finite_geometry_is_unknown(monkeypatch):
    invalid = row()
    invalid[0][0][0] = float("nan")
    result = run(monkeypatch, [invalid])
    assert result.reason == "ocr_invalid_output"
