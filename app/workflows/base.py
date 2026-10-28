"""Validated workflow contracts, independent of capture and input implementations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

if TYPE_CHECKING:
    from app.workflows.tools.base import WorkflowTools

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
NonEmpty = Annotated[str, Field(min_length=1, max_length=256)]
Mode = Literal["mock", "real"]
T = TypeVar("T")
ParamsT = TypeVar("ParamsT", bound=BaseModel)


class WorkflowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, validate_default=True, allow_inf_nan=False,
    )


class WorkflowParams(WorkflowModel):
    """Base for strict, frozen business parameter models."""


class WorkflowMetadata(WorkflowModel):
    id: Identifier
    api_version: Annotated[int, Field(ge=1)]
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)]
    task_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=100)]
    category: Literal["observation", "navigation", "combat", "quest"]
    description: Annotated[str, Field(max_length=2000)]
    tags: Annotated[tuple[NonEmpty, ...], Field(max_length=16)]
    required_capabilities: Annotated[tuple[Identifier, ...], Field(max_length=64)]
    allowed_actions: Annotated[tuple[Identifier, ...], Field(max_length=64)]

    @model_validator(mode="after")
    def unique_requirements(self) -> WorkflowMetadata:
        for values in (self.required_capabilities, self.allowed_actions):
            if len(set(values)) != len(values):
                raise ValueError("Capabilities and actions must not contain duplicate IDs")
        return self


class EvidenceRef(WorkflowModel):
    id: NonEmpty
    run_id: NonEmpty
    observation_id: NonEmpty
    session_id: NonEmpty
    frame_id: Annotated[int, Field(ge=0)]
    size_version: Annotated[int, Field(ge=1)]
    profile_version: NonEmpty


Evidence = Annotated[tuple[EvidenceRef, ...], Field(max_length=32)]


class ActionReceipt(WorkflowModel):
    action_ids: Annotated[tuple[NonEmpty, ...], Field(max_length=64)]
    effect: Literal["not_sent", "sent", "outcome_unknown"]
    verification: Literal["not_checked", "confirmed", "unknown"]
    evidence: Evidence

    @model_validator(mode="after")
    def check_effect(self) -> ActionReceipt:
        if self.effect != "not_sent" and not self.action_ids:
            raise ValueError("Possibly sent input must identify its recorded actions")
        if self.verification == "confirmed" and not self.evidence:
            raise ValueError("Confirmed verification requires evidence")
        return self


class ToolResult(WorkflowModel, Generic[T]):  # noqa: UP046
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["ok", "not_found", "ambiguous", "unknown", "timeout", "rejected", "error"]
    value: T | None
    code: Identifier
    message: Annotated[str, Field(max_length=1000)]
    evidence: Evidence
    receipt: ActionReceipt | None

    @model_validator(mode="after")
    def check_value(self) -> ToolResult[T]:
        if (self.status == "ok") != (self.value is not None):
            raise ValueError("Only ok results must contain a value")
        if isinstance(self.value, ActionReceipt) and self.value != self.receipt:
            raise ValueError("Action value and receipt must match")
        return self


class WorkflowResult(WorkflowModel):
    status: Literal["succeeded", "failed", "paused", "cancelled"]
    code: Identifier
    message: Annotated[str, Field(max_length=1000)]
    last_step: Identifier | None
    data: dict[str, JsonValue]
    evidence: Evidence

    @model_validator(mode="after")
    def check_summary(self) -> WorkflowResult:
        if self.status == "succeeded" and not self.evidence:
            raise ValueError("Success claims require evidence and independent verification")
        encoded = json.dumps(self.data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 16384:
            raise ValueError("Workflow summary exceeds 16 KiB")
        return self


class WorkflowContext(Protocol):
    @property
    def run_id(self) -> str: ...

    @property
    def session_id(self) -> str: ...

    @property
    def mode(self) -> Mode: ...

    @property
    def deadline_monotonic(self) -> float: ...

    @property
    def tools(self) -> WorkflowTools: ...

    async def checkpoint(self) -> None: ...

    async def set_step(self, step_id: str, *, timeout_ms: int) -> None: ...


class WorkflowPlugin(Protocol, Generic[ParamsT]):  # noqa: UP046
    metadata: WorkflowMetadata
    params_model: type[ParamsT]

    async def run(self, ctx: WorkflowContext, params: ParamsT) -> WorkflowResult: ...
