import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.api.server import create_app
from app.config import Settings
from app.vision.bars import read_bar
from app.vision.models import Rect, VisionProfile


def profile():
    return VisionProfile(reference_size=(100, 12), hp=Rect(x=0, y=0, width=100, height=12))


def test_experience_region_optional_and_validated():
    legacy = profile().model_dump(exclude={"exp"})
    assert VisionProfile.model_validate(legacy).exp is None
    legacy["exp"] = {"x": 0, "y": 0, "width": 100, "height": 12}
    assert VisionProfile.model_validate(legacy).exp.width == 100
    legacy["exp"]["x"] = 1
    with pytest.raises(ValidationError):
        VisionProfile.model_validate(legacy)


@pytest.mark.parametrize("fraction", [0.1, 0.5, 1.0])
@pytest.mark.parametrize("kind", ["hp", "mp"])
def test_bar_fill_ratio(fraction, kind):
    image = np.full((12, 100, 3), 64, dtype=np.uint8)
    image[:, :int(fraction * 100)] = (0, 0, 200) if kind == "hp" else (200, 150, 0)
    selected = profile()
    reading = read_bar(image, selected.hp, kind, selected)
    assert reading.ratio == pytest.approx(fraction, abs=0.01)
    assert reading.status == "known"


def test_unknown_is_not_zero_and_scattered_color_is_rejected():
    image = np.full((12, 100, 3), 64, dtype=np.uint8)
    selected = profile()
    assert read_bar(image, selected.hp, "hp", selected).ratio is None
    image[:, :50] = (0, 0, 200)
    image[:, 95] = (0, 0, 200)
    assert read_bar(image, selected.hp, "hp", selected).reason == "fill_not_contiguous"
    wrong_size = image[:, :80]
    assert read_bar(wrong_size, selected.hp, "hp", selected).ratio is None


def test_upload_preview_analysis_and_saved_profile(tmp_path):
    path = tmp_path / "vision.json"
    settings = Settings(vision_profile=str(path), web_dist=str(tmp_path / "dist"))
    image = Image.new("RGB", (100, 12), (64, 64, 64))
    for x in range(50):
        for y in range(12):
            image.putpixel((x, y), (200, 0, 0))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        uploaded = client.post("/api/images", content=payload.getvalue())
        assert uploaded.status_code == 201
        image_id = uploaded.json()["image_id"]
        preview = client.get(f"/api/images/{image_id}/preview")
        assert Image.open(io.BytesIO(preview.content)).size == (100, 12)
        body = profile().model_dump()
        body["exp"] = {"x": 0, "y": 0, "width": 100, "height": 12}
        result = client.post(f"/api/images/{image_id}/analyze", json=body).json()
        assert result["hp"]["ratio"] == pytest.approx(0.5)
        assert result["mp"]["ratio"] is None
        assert result["session_id"] == image_id
        assert result["source"] == "screenshot"
        assert client.put("/api/vision/profile", json=body).status_code == 200
        assert json.loads(path.read_text())["reference_size"] == [100, 12]
        assert client.get("/api/vision/profile").json()["hp"]["width"] == 100
        assert client.get("/api/vision/profile").json()["exp"] == body["exp"]
        assert json.loads(path.read_text())["exp"] == body["exp"]
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
        body["hp"]["x"] = 1
        assert client.put("/api/vision/profile", json=body).status_code == 422
        assert not settings.vision_profile_path.exists()
