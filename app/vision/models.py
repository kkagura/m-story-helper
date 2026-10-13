import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class VisionFailure(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class Rect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    width: StrictInt = Field(ge=2)
    height: StrictInt = Field(ge=2)


class VisionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    reference_size: tuple[StrictInt, StrictInt]
    hp: Rect | None = None
    mp: Rect | None = None
    exp: Rect | None = None
    player_info: Rect | None = None
    player_name: Rect | None = None
    min_channel: StrictInt = Field(default=80, ge=1, le=255)
    min_color_difference: StrictInt = Field(default=35, ge=1, le=255)
    min_column_fraction: float = Field(default=0.3, gt=0, le=1)
    min_continuity: float = Field(default=0.9, gt=0, le=1)

    @model_validator(mode="after")
    def validate_regions(self):
        width, height = self.reference_size
        if not (1 <= width <= 16384 and 1 <= height <= 16384):
            raise ValueError("参考尺寸必须为 1–16384 的整数")
        for roi in (self.hp, self.mp, self.exp, self.player_info, self.player_name):
            if roi and (roi.x + roi.width > width or roi.y + roi.height > height):
                raise ValueError("识别区域超出参考画面")
        return self

    @property
    def version(self) -> str:
        data = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(data).hexdigest()[:16]


class BarReading(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["known", "unknown"]
    ratio: float | None = Field(default=None, ge=0, le=1)
    bbox: tuple[int, int, int, int] | None = None
    quality: float = Field(default=0, ge=0, le=1)
    reason: str | None = None


class ObservationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: str
    session_id: str
    frame_id: int
    size_version: int
    source: Literal["webrtc", "screenshot"]
    source_size: tuple[int, int]
    profile_version: str
    bbox_format: Literal["xywh"] = "xywh"
    processing_ms: float
    hp: BarReading
    mp: BarReading
