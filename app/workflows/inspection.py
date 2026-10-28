"""Read-only single-step contracts; shared by preview and future run coordination."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Generic, Literal, Protocol

from pydantic import Field, JsonValue, StrictInt, model_validator

from app.workflows.base import Identifier, NonEmpty, ParamsT, WorkflowMetadata, WorkflowModel

if TYPE_CHECKING:
    from app.state.observation import ObservationSnapshot
    from app.vision.models import BodyReading, DialogueReading, SceneNameReading


class InspectionSelection(WorkflowModel):
    plugin_id: Identifier
    plugin_version: NonEmpty
    params: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_params(self) -> InspectionSelection:
        if len(self.params) > 64 or len(json.dumps(self.params, allow_nan=False).encode()) > 16384:
            raise ValueError("Inspection parameters exceed the 64-key / 16 KiB limit")
        return self


class InspectionField(WorkflowModel):
    key: Identifier
    label: NonEmpty
    value: str | int | float | bool | None

    @model_validator(mode="after")
    def bounded_value(self) -> InspectionField:
        if isinstance(self.value, str) and len(self.value) > 2048:
            raise ValueError("Inspection field text exceeds 2048 characters")
        return self


class InspectionAnnotation(WorkflowModel):
    id: Identifier
    label: NonEmpty
    kind: Literal["region", "candidate", "target"]
    bbox: tuple[StrictInt, StrictInt, StrictInt, StrictInt]

    @model_validator(mode="after")
    def check_box(self) -> InspectionAnnotation:
        x, y, w, h = self.bbox
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ValueError("Annotation must be a positive source-frame rectangle")
        return self


class StepIntent(WorkflowModel):
    kind: Literal["click", "scroll", "wait", "observe"]
    label: NonEmpty
    reason: NonEmpty
    target_id: Identifier | None = None
    execution_authorized: Literal[False] = False


class WorkflowInspection(WorkflowModel):
    plugin_id: Identifier
    plugin_version: NonEmpty
    observation_id: NonEmpty
    status: Literal["found", "not_found", "ambiguous", "unknown"]
    stage_id: Identifier = "unknown"
    stage_label: NonEmpty = "未知阶段"
    fields: Annotated[tuple[InspectionField, ...], Field(max_length=64)] = ()
    annotations: Annotated[tuple[InspectionAnnotation, ...], Field(max_length=64)] = ()
    intent: StepIntent | None = None
    missing_conditions: Annotated[tuple[NonEmpty, ...], Field(max_length=32)] = ()
    diagnostics: Annotated[tuple[NonEmpty, ...], Field(max_length=64)] = ()
    processing_ms: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_references(self) -> WorkflowInspection:
        ids = [a.id for a in self.annotations]
        if len(ids) != len(set(ids)) or len({f.key for f in self.fields}) != len(self.fields):
            raise ValueError("Annotation and field IDs must be unique")
        if self.intent and self.intent.target_id and self.intent.target_id not in ids:
            raise ValueError("Intent target must reference an annotation")
        if self.status != "found" and self.intent is not None:
            raise ValueError("Unconfirmed inspection must not propose an intent")
        return self


class ReadOnlyPerception(Protocol):
    def dialogue(self) -> DialogueReading: ...

    def npc_name(self, name: str) -> SceneNameReading: ...

    def npc_body(self, name: str) -> BodyReading: ...


@dataclass(frozen=True)
class InspectionContext:
    snapshot: ObservationSnapshot
    perception: ReadOnlyPerception
    deadline_monotonic: float

    def checkpoint(self) -> None:
        if time.monotonic() >= self.deadline_monotonic:
            raise TimeoutError("Workflow inspection deadline exceeded")


class WorkflowEvaluator(Protocol, Generic[ParamsT]):  # noqa: UP046
    metadata: WorkflowMetadata

    def evaluate(self, ctx: InspectionContext, params: ParamsT) -> WorkflowInspection: ...
