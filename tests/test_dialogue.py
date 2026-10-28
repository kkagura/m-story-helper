"""Dialogue geometry/OCR stubs, not real-model or interactive acceptance tests."""

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.server import create_app
from app.config import Settings
from app.vision.dialogue import extract_dialogue, find_panels, read_dialogue
from app.vision.models import DialogueText, VisionProfile
from app.vision.names import PlayerNameReader

PANEL = (100, 100, 520, 200)


def text(value, x=265, y=155, width=330, confidence=0.95):
    return DialogueText(text=value, confidence=confidence, bbox=(x, y, width, 14))


def test_common_reader_does_not_classify_task_or_propose_actions():
    reading = extract_dialogue(PANEL, (
        text("你确定要交换吗？"), text("查里中士", x=130, y=210, width=100),
        text("是", x=520, y=280, width=35), text("聊天文字", x=10, y=520),
    ))
    assert reading.status == "found" and reading.npc_name == "查里中士"
    assert len(reading.options) == 1
    assert not hasattr(reading, "page") and not hasattr(reading, "suggested_action")
    assert "聊天文字" not in reading.text


@pytest.mark.parametrize("offset", [(180, 150), (300, 220)])
def test_light_panel_locator_is_not_a_fixed_sample_roi(offset):
    pixels = np.zeros((700, 1200, 3), dtype=np.uint8)
    x, y = offset
    pixels[y:y + 180, x:x + 500] = 220
    panels = find_panels(pixels)
    assert len(panels) == 1
    left, top, w, h = panels[0]
    assert left <= x and top <= y and left + w >= x + 500 and top + h >= y + 180
    assert 0 <= left < left + w <= 1200 and 0 <= top < top + h <= 700


def test_multiple_panels_and_no_panel_do_not_run_ocr(monkeypatch):
    def forbidden(*_):
        pytest.fail("Ambiguous or missing panel must not start OCR")

    reader = PlayerNameReader()
    monkeypatch.setattr(reader, "ensure_engine", forbidden)
    selected = VisionProfile(reference_size=(800, 500))
    pixels = np.zeros((500, 800, 3), dtype=np.uint8)
    assert read_dialogue(reader, pixels, selected).status == "not_found"
    monkeypatch.setattr("app.vision.dialogue.find_panels", lambda _: (PANEL, (0, 0, 520, 200)))
    reading = read_dialogue(reader, pixels, selected)
    assert reading.status == "ambiguous" and len(reading.candidates) == 2


def test_ocr_maps_panel_coordinates_back_to_source_frame(monkeypatch):
    monkeypatch.setattr("app.vision.dialogue.find_panels", lambda _: (PANEL,))
    rows = [
        [[[330, 110], [990, 110], [990, 138], [330, 138]], "你确定要交换吗", 0.95],
        [[[840, 360], [910, 360], [910, 388], [840, 388]], "是", 0.95],
    ]
    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: lambda *_a, **_k: (rows, []))
    pixels = np.zeros((500, 800, 3), dtype=np.uint8)
    result = read_dialogue(PlayerNameReader(), pixels, VisionProfile(reference_size=(800, 500)))
    assert result.status == "found" and result.options[0].bbox == (520, 280, 35, 14)


@pytest.mark.parametrize(("rows", "reason"), [
    ([[[[0, 0]], "坏坐标", 0.9]], "ocr_invalid_output"),
    ([[[[0, 0], [1, 0], [1, 1], [0, 1]], "异常", float("nan")]], "ocr_invalid_output"),
    ([[[], "过多", 0.95]] * 65, "dialogue_text_limit"),
])
def test_invalid_or_excessive_ocr_output_fails_closed(monkeypatch, rows, reason):
    monkeypatch.setattr("app.vision.dialogue.find_panels", lambda _: (PANEL,))
    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: lambda *_a, **_k: (rows, []))
    reading = read_dialogue(
        PlayerNameReader(), np.zeros((500, 800, 3), dtype=np.uint8),
        VisionProfile(reference_size=(800, 500)),
    )
    assert reading.status == "unknown" and reading.reason == reason
    assert not reading.options


def test_uploaded_dialogue_is_part_of_the_same_frame_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("app.vision.dialogue.find_panels", lambda _: (PANEL,))
    rows = [[[[330, 110], [990, 110], [990, 138], [330, 138]], "已经交换成功了", 0.95]]
    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: lambda *_a, **_k: (rows, []))
    settings = Settings(
        vision_profile=str(tmp_path / "vision.json"), web_dist=str(tmp_path / "dist"),
    )
    payload = io.BytesIO()
    Image.new("RGB", (800, 500)).save(payload, format="PNG")
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        selected = VisionProfile(reference_size=(800, 500))
        response = client.post(f"/api/images/{image_id}/analyze", json={
            "profile": selected.model_dump(), "workflow": {
                "plugin_id": "orbis_charlie_exchange", "plugin_version": "1.3.0", "params": {},
            },
        })
        assert response.status_code == 200
        result = response.json()
        assert result["session_id"] == image_id and result["source_size"] == [800, 500]
        assert result["profile_version"] == selected.version
        assert result["workflow_inspection"]["stage_id"] == "success"
        assert result["dialogue"]["npc_name"] is None
        assert result["workflow_inspection"]["intent"]["kind"] == "wait"
        assert result["player_name"]["status"] == "unknown"


def test_missing_ocr_dependency_preserves_located_panel_and_unknown_status(monkeypatch):
    monkeypatch.setattr("app.vision.dialogue.find_panels", lambda _: (PANEL,))

    def missing(_):
        raise ImportError("fixture missing dependency")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", missing)
    result = read_dialogue(
        PlayerNameReader(), np.zeros((500, 800, 3), dtype=np.uint8),
        VisionProfile(reference_size=(800, 500)),
    )
    assert result.panel_bbox == PANEL and result.status == "unknown"
    assert result.reason == "ocr_dependency_missing" and not result.options


@pytest.mark.parametrize("number", [2, 3, 4, 5, 6])
def test_game_fixture_panel_includes_button_bar(number):
    path = Path(__file__).resolve().parents[1] / "samples" / "tasks" / f"{number}.png"
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    panels = find_panels(pixels)
    assert len(panels) == 1, f"Expected one complete panel in {number}.png, got {panels}"
    x, y, w, h = panels[0]
    a, b, c, d = (430, 255, 520, 318) if number == 4 else (430, 316, 520, 198)
    overlap = max(0, min(x + w, a + c) - max(x, a)) * max(
        0, min(y + h, b + d) - max(y, b),
    )
    assert overlap / (c * d) >= 0.95, f"Panel misses portrait or buttons: {panels}"


def test_scene_fixture_does_not_become_a_dialogue_panel():
    path = Path(__file__).resolve().parents[1] / "samples" / "tasks" / "1.png"
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    assert find_panels(pixels) == ()


def test_frame_detection_handles_disconnected_interiors_and_colored_button_bar():
    pixels = np.zeros((700, 1200, 3), dtype=np.uint8)
    # The white body is too narrow for a whole panel, separated from portrait and footer.
    pixels[220:390, 300:840] = 100
    pixels[228:352, 308:440] = 215
    pixels[228:352, 454:832] = 235
    pixels[365:383, 735:780] = (30, 150, 240)
    panels = find_panels(pixels)
    assert len(panels) == 1, panels
    x, y, w, h = panels[0]
    assert x <= 310 and y <= 230 and x + w >= 830 and y + h >= 382


def test_dark_rectangular_window_is_not_a_light_dialogue_panel():
    pixels = np.zeros((700, 1200, 3), dtype=np.uint8)
    pixels[220:390, 300:840] = 70
    assert find_panels(pixels) == ()
