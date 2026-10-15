import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.api.server import create_app
from app.config import Settings
from app.vision.body import BodyLocator
from app.vision.models import Rect, VisionProfile
from app.vision.names import PlayerNameReader


def profile():
    return VisionProfile(reference_size=(100, 12), hp_text=Rect(x=0, y=0, width=100, height=12))


@pytest.mark.parametrize(
    "kind", [ "player_info", "player_name", "hp_text", "mp_text",
             "player_level", "player_job", "exp_text"],
)
def test_optional_region_compatibility_and_bounds(kind):
    legacy = profile().model_dump(
        exclude={ "player_info", "player_name", "hp_text", "mp_text",
                 "player_level", "player_job", "exp_text"},
    )
    assert getattr(VisionProfile.model_validate(legacy), kind) is None
    legacy[kind] = {"x": 0, "y": 0, "width": 100, "height": 12}
    assert getattr(VisionProfile.model_validate(legacy), kind).width == 100
    legacy[kind]["x"] = 1
    with pytest.raises(ValidationError):
        VisionProfile.model_validate(legacy)


@pytest.mark.parametrize("field", ["hp", "mp", "exp", "min_channel", "unexpected"])
def test_unknown_profile_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        VisionProfile.model_validate({**profile().model_dump(), field: None})


def test_upload_preview_analysis_and_saved_profile(tmp_path, monkeypatch):
    texts = iter(["测试角色", "25/100", "0/50", "55", "剑客", "503851[54.37%]"])

    def fake_ocr(_pixels, **_options):
        return [[[], next(texts), 0.95]], [0.01]

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fake_ocr)
    path = tmp_path / "vision.json"
    settings = Settings(vision_profile=str(path), web_dist=str(tmp_path / "dist"))
    image = Image.new("RGB", (100, 12), (64, 64, 64))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        uploaded = client.post("/api/images", content=payload.getvalue())
        assert uploaded.status_code == 201
        image_id = uploaded.json()["image_id"]
        preview = client.get(f"/api/images/{image_id}/preview")
        assert Image.open(io.BytesIO(preview.content)).size == (100, 12)
        body = profile().model_dump()
        body["player_level_min_confidence"] = 0.65
        body["player_info"] = {"x": 0, "y": 0, "width": 100, "height": 12}
        body["player_name"] = {"x": 1, "y": 1, "width": 50, "height": 10}
        body["hp_text"] = {"x": 0, "y": 0, "width": 40, "height": 12}
        body["mp_text"] = {"x": 50, "y": 0, "width": 40, "height": 12}
        for kind in ("player_level", "player_job", "exp_text"):
            body[kind] = {"x": 0, "y": 0, "width": 40, "height": 12}
        result = client.post(f"/api/images/{image_id}/analyze", json=body).json()
        assert "hp" not in result and "mp" not in result
        assert result["session_id"] == image_id
        assert result["source"] == "screenshot"
        assert result["player_name"]["text"] == "测试角色"
        assert result["player_name"]["bbox"] == [1, 1, 50, 10]
        assert result["hp_numbers"]["current"] == 25
        assert result["hp_numbers"]["total"] == 100
        assert result["hp_numbers"]["ratio"] == 0.25
        assert result["mp_numbers"]["current"] == 0
        assert result["mp_numbers"]["total"] == 50
        assert result["mp_numbers"]["ratio"] == 0
        assert result["player_level"]["value"] == 55
        assert result["player_job"]["text"] == "剑客"
        assert result["experience"]["value"] == 503851
        assert result["experience"]["percentage"] == 54.37
        assert client.put("/api/vision/profile", json=body).status_code == 200
        assert client.get("/api/vision/profile").json()["player_level_min_confidence"] == 0.65
        assert json.loads(path.read_text())["player_level_min_confidence"] == 0.65
        assert json.loads(path.read_text())["reference_size"] == [100, 12]
        assert "hp" not in client.get("/api/vision/profile").json()
        assert "exp" not in json.loads(path.read_text())
        assert "min_channel" not in json.loads(path.read_text())
        assert client.put("/api/vision/profile", json={**body, "hp": None}).status_code == 422
        for kind in ("player_info", "player_name", "hp_text", "mp_text",
                     "player_level", "player_job", "exp_text"):
            assert client.get("/api/vision/profile").json()[kind] == body[kind]
            assert json.loads(path.read_text())[kind] == body[kind]
        replacement = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        assert replacement != image_id
        assert client.get(f"/api/images/{image_id}/preview").status_code == 404
        assert client.delete(f"/api/images/{image_id}").status_code == 204
        assert client.get(f"/api/images/{replacement}/preview").status_code == 200


def test_invalid_image_size_and_region_are_rejected(tmp_path):
    settings = Settings(
        vision_profile=str(tmp_path / "vision.json"), image_max_upload_bytes=100,
        web_dist=str(tmp_path / "dist"),
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/images", content=b"not an image").status_code == 415
        assert client.post("/api/images", content=b"x" * 101).status_code == 413
        body = profile().model_dump()
        body["hp_text"]["x"] = 1
        assert client.put("/api/vision/profile", json=body).status_code == 422
        assert not settings.vision_profile_path.exists()


def test_scene_name_matches_same_uploaded_frame(tmp_path, monkeypatch):
    template = np.random.default_rng(9).integers(0, 255, (10, 10, 3), dtype=np.uint8)
    monkeypatch.setattr(BodyLocator, "load_template", lambda _: (template, "api-template"))
    rows = iter([
        [[[], "测试角色", 0.95]],
        [[[[20, 30], [80, 30], [80, 40], [20, 40]], "测试角色", 0.95]],
    ])
    monkeypatch.setattr(PlayerNameReader, "_create_engine",
                        lambda _: lambda *_a, **_k: (next(rows), []))
    settings = Settings(vision_profile=str(tmp_path / "vision.json"),
                        web_dist=str(tmp_path / "dist"))
    image = Image.new("RGB", (100, 100), (64, 64, 64))
    image.paste(Image.fromarray(template[:, :, ::-1]), (40, 15))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    selected = VisionProfile(
        reference_size=(100, 100), player_name=Rect(x=0, y=80, width=100, height=20),
        scene=Rect(x=0, y=0, width=100, height=70),
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        result = client.post(f"/api/images/{image_id}/analyze", json=selected.model_dump()).json()
        assert result["session_id"] == image_id
        assert result["player_name"]["text"] == result["scene_name"]["target_name"]
        assert result["scene_name"]["status"] == "found"
        assert result["scene_name"]["name_bbox"] == [20, 30, 60, 10]
        assert result["player_body"]["status"] == "found"
        assert result["player_body"]["bbox"] == [40, 15, 10, 10]
        assert result["player_body"]["bottom_center"] == [45, 24]
        assert result["player_body"]["template_version"] == "api-template"
        assert client.put("/api/vision/profile", json=selected.model_dump()).status_code == 200
        assert client.get("/api/vision/profile").json()["scene"] == selected.scene.model_dump()
