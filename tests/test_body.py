"""Synthetic template matching checks; not real avatar detection acceptance."""

import numpy as np
import pytest

from app.vision.body import BodyLocator
from app.vision.models import Rect, SceneNameReading, VisionProfile


def setup(monkeypatch):
    template = np.random.default_rng(7).integers(0, 255, (20, 16, 3), dtype=np.uint8)
    monkeypatch.setattr(BodyLocator, "load_template", lambda _: (template, "test-template"))
    selected = VisionProfile(
        reference_size=(400, 300), scene=Rect(x=0, y=0, width=400, height=300),
        body_min_score=0.99,
    )
    name = SceneNameReading(status="found", name_bbox=(100, 220, 220, 12), reason=None)
    return template, selected, name


@pytest.mark.parametrize(("x", "y"), [(130, 160), (180, 120), (250, 80)])
def test_actual_match_not_a_fixed_name_offset(monkeypatch, x, y):
    template, selected, name = setup(monkeypatch)
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    image[y:y + 20, x:x + 16] = template
    original = image.copy()
    result = BodyLocator().locate(image, selected, name)
    assert result.status == "found"
    assert result.bbox == (x, y, 16, 20)
    assert result.bottom_center == (x + 8, y + 19)
    assert result.template_version == "test-template"
    np.testing.assert_array_equal(image, original)


def test_blank_and_other_appearance_do_not_produce_a_body(monkeypatch):
    _, selected, name = setup(monkeypatch)
    result = BodyLocator().locate(np.zeros((300, 400, 3), dtype=np.uint8), selected, name)
    assert result.status == "not_found"
    assert result.bbox is result.bottom_center is None
    image = np.random.default_rng(44).integers(0, 255, (300, 400, 3), dtype=np.uint8)
    result = BodyLocator().locate(image, selected, name)
    assert result.status == "not_found"
    assert result.reason == "no_body_match"


def test_duplicate_matches_are_ambiguous(monkeypatch):
    template, selected, name = setup(monkeypatch)
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    image[160:180, 130:146] = template
    image[160:180, 240:256] = template
    result = BodyLocator().locate(image, selected, name)
    assert result.status == "ambiguous"
    assert len(result.candidates) == 2
    assert result.bbox is result.bottom_center is None


def test_unconfirmed_name_skips_loading(monkeypatch):
    def unexpected_load(_):
        pytest.fail("Unknown name cannot authorize a body match")

    monkeypatch.setattr(BodyLocator, "load_template", unexpected_load)
    result = BodyLocator().locate(
        np.zeros((300, 400, 3), dtype=np.uint8), VisionProfile(reference_size=(400, 300)),
        SceneNameReading(status="ambiguous"),
    )
    assert result.reason == "name_not_confirmed"


def test_ui_match_and_missing_template_return_unknown(monkeypatch):
    template, selected, name = setup(monkeypatch)
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    image[160:180, 130:146] = template
    selected = selected.model_copy(update={
        "scene_exclusions": (Rect(x=130, y=160, width=16, height=20),),
    })
    assert BodyLocator().locate(image, selected, name).reason == "body_overlaps_ui"

    def missing(_):
        raise FileNotFoundError

    monkeypatch.setattr(BodyLocator, "load_template", missing)
    assert BodyLocator().locate(image, selected, name).reason == "body_template_unavailable"
