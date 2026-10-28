"""Appearance matching checks; do not establish actual game hitboxes or click success."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.vision.models import Rect, SceneNameReading, VisionProfile
from app.vision.npc_body import NpcBodyLocator


def profile():
    return VisionProfile(
        reference_size=(260, 220), scene=Rect(x=0, y=0, width=260, height=210),
        body_template=None, body_min_score=1.0,
    )


def test_npc_body_matches_actual_position_independently_of_player_settings(monkeypatch):
    template = np.random.default_rng(32).integers(0, 255, (30, 20, 3), dtype=np.uint8)
    monkeypatch.setattr(NpcBodyLocator, "load_template", lambda _: (template, "fixture"))
    pixels = np.zeros((220, 260, 3), dtype=np.uint8)
    pixels[115:145, 110:130] = template
    name = SceneNameReading(status="found", name_bbox=(80, 180, 100, 16))
    result = NpcBodyLocator().locate(pixels, profile(), name)
    assert result.status == "found" and result.bbox == (110, 115, 20, 30)
    assert result.template_id == "npc_charlie" and result.template_version == "fixture"
    assert result.search_bbox != result.bbox


def test_duplicate_bodies_and_missing_appearance_do_not_return_a_body(monkeypatch):
    template = np.random.default_rng(17).integers(0, 255, (30, 20, 3), dtype=np.uint8)
    monkeypatch.setattr(NpcBodyLocator, "load_template", lambda _: (template, "fixture"))
    pixels = np.zeros((220, 260, 3), dtype=np.uint8)
    name = SceneNameReading(status="found", name_bbox=(80, 180, 100, 16))
    assert NpcBodyLocator().locate(pixels, profile(), name).bbox is None
    pixels[100:130, 90:110] = template
    pixels[100:130, 140:160] = template
    result = NpcBodyLocator().locate(pixels, profile(), name)
    assert result.status == "ambiguous" and result.bbox is None


def test_unconfirmed_name_does_not_load_template(monkeypatch):
    def forbidden(_):
        pytest.fail("Unconfirmed names must not search appearance")

    monkeypatch.setattr(NpcBodyLocator, "load_template", forbidden)
    result = NpcBodyLocator().locate(
        np.zeros((220, 260, 3), dtype=np.uint8), profile(), SceneNameReading(),
    )
    assert result.status == "unknown" and result.bbox is None


def test_reference_body_crop_excludes_name_and_speech_bubble():
    path = Path(__file__).resolve().parents[1] / "samples" / "tasks" / "1.png"
    with Image.open(path) as image:
        pixels = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    selected = VisionProfile(
        reference_size=(1382, 807), scene=Rect(x=8, y=31, width=1365, height=693),
    )
    result = NpcBodyLocator().locate(
        pixels, selected, SceneNameReading(status="found", name_bbox=(411, 480, 54, 18)),
    )
    assert result.status == "found" and result.bbox == (411, 408, 50, 69)
    assert result.bbox[1] + result.bbox[3] <= 480
