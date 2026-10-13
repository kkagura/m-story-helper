import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.server import create_app
from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(web_dist=str(tmp_path / "missing-dist"))


def test_health_status_and_lifecycle(settings):
    application = create_app(settings)
    with TestClient(application, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/health").json()["status"] == "ok"
        status = client.get("/api/status").json()
        assert status["engine"]["state"] == "idle"
        assert status["engine"]["capabilities"]["capture"] is True
        assert status["engine"]["capabilities"]["vision"] is True
        assert status["media"]["state"] == "idle"
        assert status["web_ui_ready"] is False
        assert client.get("/api/media/offer").status_code == 405
    assert application.state.engine.status().state == "stopped"


def test_missing_frontend_gives_instructions(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "pnpm build" in response.text


def test_build_is_served_without_shadowing_api(tmp_path):
    (tmp_path / "index.html").write_text("<h1>frontend fixture</h1>", encoding="utf-8")
    settings = Settings(web_dist=str(tmp_path))
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        assert "frontend fixture" in client.get("/").text
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/status").json()["web_ui_ready"] is True
        assert client.get("/api/not-implemented").status_code == 404


def test_origin_and_host_are_restricted(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/health", headers={"Origin": "https://example.com"})
        assert response.status_code == 403
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert client.get("/api/health", headers={"Host": "example.com"}).status_code == 400


@pytest.mark.parametrize("values", [{"host": "0.0.0.0"}, {"port": 0}, {"port": 65536}])
def test_invalid_local_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(**values)
