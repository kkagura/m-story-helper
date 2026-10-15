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
    hp_text: Rect | None = None
    mp_text: Rect | None = None
    exp_text: Rect | None = None
    player_level: Rect | None = None
    player_job: Rect | None = None
    player_info: Rect | None = None
    player_name: Rect | None = None
    scene: Rect | None = None
    scene_exclusions: tuple[Rect, ...] = Field(default=(), max_length=16)
    scene_name_min_confidence: float = Field(default=0.8, ge=0, le=1)
    player_name_min_confidence: float = Field(default=0.8, ge=0, le=1)
    player_level_min_confidence: float = Field(default=0.6, ge=0, le=1)
    numbers_min_confidence: float = Field(default=0.8, ge=0, le=1)
    body_template: Literal["normal"] | None = "normal"
    body_min_score: float = Field(default=0.85, ge=0, le=1)
    body_search_width: StrictInt = Field(default=220, ge=32, le=1024)
    body_search_height: StrictInt = Field(default=180, ge=32, le=512)

    @model_validator(mode="after")
    def validate_regions(self):
        width, height = self.reference_size
        if not (1 <= width <= 16384 and 1 <= height <= 16384):
            raise ValueError("参考尺寸必须为 1–16384 的整数")
        for roi in (
            self.hp_text, self.mp_text,
            self.exp_text, self.player_level, self.player_job,
            self.player_info, self.player_name,
            self.scene, *self.scene_exclusions,
        ):
            if roi and (roi.x + roi.width > width or roi.y + roi.height > height):
                raise ValueError("识别区域超出参考画面")
        return self

    @property
    def version(self) -> str:
        data = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(data).hexdigest()[:16]


class NameReading(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["known", "unknown"]
    text: str | None = None
    raw_text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    bbox: tuple[int, int, int, int] | None = None
    reason: str | None = None
    processing_ms: float = 0
    backend: str = "rapidocr-onnxruntime/1.4.4"


class NumericReading(NameReading):
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, gt=0)
    ratio: float | None = Field(default=None, ge=0, le=1)


class LevelReading(NameReading):
    value: int | None = Field(default=None, gt=0, le=9999)


class ExperienceReading(NameReading):
    value: int | None = Field(default=None, ge=0)
    percentage: float | None = Field(default=None, ge=0, le=100)


class SceneNameCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str
    confidence: float = Field(ge=0, le=1)
    bbox: tuple[int, int, int, int]


class SceneNameReading(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["found", "not_found", "ambiguous", "unknown"] = "unknown"
    target_name: str | None = None
    name_bbox: tuple[int, int, int, int] | None = None
    candidates: tuple[SceneNameCandidate, ...] = Field(default=(), max_length=32)
    search_bbox: tuple[int, int, int, int] | None = None
    reason: str | None = "scene_not_configured"
    text_count: int = 0
    processing_ms: float = 0
    backend: str = "rapidocr-onnxruntime/1.4.4"


class BodyCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    bbox: tuple[int, int, int, int]
    score: float = Field(ge=0, le=1)


class BodyReading(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["found", "not_found", "ambiguous", "unknown"] = "unknown"
    bbox: tuple[int, int, int, int] | None = None
    bottom_center: tuple[int, int] | None = None
    search_bbox: tuple[int, int, int, int] | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    candidates: tuple[BodyCandidate, ...] = Field(default=(), max_length=8)
    template_id: str | None = None
    template_version: str | None = None
    reason: str | None = "name_not_confirmed"
    processing_ms: float = 0
    method: Literal["template_matching"] = "template_matching"


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
    hp_numbers: NumericReading = Field(
        default_factory=lambda: NumericReading(status="unknown", reason="region_not_configured")
    )
    mp_numbers: NumericReading = Field(
        default_factory=lambda: NumericReading(status="unknown", reason="region_not_configured")
    )
    player_name: NameReading = Field(
        default_factory=lambda: NameReading(status="unknown", reason="region_not_configured")
    )
    player_level: LevelReading = Field(
        default_factory=lambda: LevelReading(status="unknown", reason="region_not_configured")
    )
    player_job: NameReading = Field(
        default_factory=lambda: NameReading(status="unknown", reason="region_not_configured")
    )
    experience: ExperienceReading = Field(
        default_factory=lambda: ExperienceReading(status="unknown", reason="region_not_configured")
    )
    scene_name: SceneNameReading = Field(default_factory=SceneNameReading)
    player_body: BodyReading = Field(default_factory=BodyReading)
