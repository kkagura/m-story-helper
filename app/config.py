"""Configuration paths are resolved from the checkout, not the shell directory."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: Literal["127.0.0.1", "localhost"] = "127.0.0.1"
    port: StrictInt = Field(default=8765, ge=1, le=65535)
    dev_frontend_port: StrictInt = Field(default=5173, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    web_dist: str = "web/dist"
    media_negotiation_timeout_seconds: float = Field(default=15, ge=1, le=60)
    media_connect_timeout_seconds: float = Field(default=15, ge=1, le=60)
    media_frame_timeout_seconds: float = Field(default=8, ge=1, le=60)
    media_heartbeat_timeout_seconds: float = Field(default=10, ge=2, le=60)
    media_max_frame_pixels: StrictInt = Field(default=8_294_400, ge=1, le=33_177_600)
    image_max_upload_bytes: StrictInt = Field(default=10_485_760, ge=1, le=52_428_800)
    vision_profile: str = "configs/vision.json"

    @property
    def vision_profile_path(self) -> Path:
        path = Path(self.vision_profile)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @property
    def web_dist_path(self) -> Path:
        path = Path(self.web_dist)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @property
    def allowed_origins(self) -> set[str]:
        return {
            f"http://{host}:{port}"
            for host in ("127.0.0.1", "localhost")
            for port in (self.port, self.dev_frontend_port)
        }


def load_settings(path: Path = DEFAULT_CONFIG) -> Settings:
    """An explicitly provided relative config path is relative to the current directory."""
    with path.open(encoding="utf-8") as handle:
        return Settings.model_validate(json.load(handle))
