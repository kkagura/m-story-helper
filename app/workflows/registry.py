"""Explicit trusted factories and compatibility checks; never import user paths."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from app.workflows.base import (
    Identifier,
    Mode,
    WorkflowMetadata,
    WorkflowModel,
    WorkflowParams,
    WorkflowPlugin,
)
from app.workflows.inspection import WorkflowEvaluator


class WorkflowEnvironment(WorkflowModel):
    """Available capabilities/actions for exactly this execution mode."""

    mode: Mode = "mock"
    capabilities: frozenset[Identifier] = frozenset()
    allowed_actions: frozenset[Identifier] = frozenset()


class ValidationReport(WorkflowModel):
    valid: bool
    reasons: tuple[str, ...]


class WorkflowDescription(WorkflowModel):
    metadata: WorkflowMetadata
    params_schema: dict[str, Any]
    mode: Mode
    available: bool
    unavailable_reasons: tuple[str, ...]
    inspection_available: bool
    inspection_unavailable_reasons: tuple[str, ...]


class WorkflowUnavailable(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("; ".join(report.reasons))
        self.report = report


@dataclass(frozen=True)
class _Registration:
    factory: Callable[[], WorkflowPlugin[Any]]
    metadata: WorkflowMetadata
    params_model: type[WorkflowParams]
    implementation_ready: bool
    unavailable_reason: str | None
    inspection_ready: bool
    inspection_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class PreparedWorkflow:
    plugin: WorkflowPlugin[Any]
    params: WorkflowParams


@dataclass(frozen=True)
class PreparedInspection:
    plugin: WorkflowEvaluator[Any]
    params: WorkflowParams


class WorkflowRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Registration] = {}

    def register(
        self, factory: Callable[[], WorkflowPlugin[Any]], *, implementation_ready: bool,
        unavailable_reason: str | None = None, inspection_ready: bool = False,
        inspection_capabilities: tuple[str, ...] = (),
    ) -> None:
        probe = factory()
        metadata = probe.metadata
        if not isinstance(metadata, WorkflowMetadata):
            raise ValueError("Plugin metadata must be WorkflowMetadata")
        if metadata.id in self._entries:
            raise ValueError(f"Duplicate workflow ID: {metadata.id}")
        if metadata.api_version != 1:
            raise ValueError(f"Unsupported workflow API version: {metadata.api_version}")
        model = probe.params_model
        if not isinstance(model, type) or not issubclass(model, WorkflowParams):
            raise ValueError("Parameter model must inherit WorkflowParams")
        for key, expected in (
            ("strict", True), ("frozen", True), ("extra", "forbid"), ("validate_default", True),
        ):
            if model.model_config.get(key) != expected:
                raise ValueError(f"Parameter model must set {key}={expected}")
        model.model_json_schema()
        if not inspect.iscoroutinefunction(probe.run):
            raise ValueError("Workflow run must be an async method")
        if type(implementation_ready) is not bool:
            raise ValueError("implementation_ready must be a boolean")
        if not implementation_ready and not unavailable_reason:
            raise ValueError("Unimplemented workflows must explain why they are unavailable")
        if type(inspection_ready) is not bool:
            raise ValueError("inspection_ready must be a boolean")
        inspection_capabilities = TypeAdapter(tuple[Identifier, ...]).validate_python(
            inspection_capabilities, strict=True,
        )
        if len(set(inspection_capabilities)) != len(inspection_capabilities):
            raise ValueError("Inspection capabilities must be unique")
        if inspection_ready and (not callable(getattr(probe, "evaluate", None))
                                 or inspect.iscoroutinefunction(probe.evaluate)):
            raise ValueError("Inspection requires a synchronous evaluate method")
        self._entries[metadata.id] = _Registration(
            factory, metadata, model, implementation_ready, unavailable_reason,
            inspection_ready, inspection_capabilities,
        )

    @staticmethod
    def _availability(entry: _Registration, env: WorkflowEnvironment) -> list[str]:
        reasons = []
        if not entry.implementation_ready:
            reasons.append(entry.unavailable_reason or "流程尚未实现。")
        for capability in sorted(set(entry.metadata.required_capabilities) - env.capabilities):
            reasons.append(f"{env.mode} 模式缺少能力：{capability}")
        for action in sorted(set(entry.metadata.allowed_actions) - env.allowed_actions):
            reasons.append(f"{env.mode} 模式不允许动作：{action}")
        return reasons

    @staticmethod
    def _inspection_availability(entry: _Registration, env: WorkflowEnvironment) -> list[str]:
        if not entry.inspection_ready:
            return ["该插件尚未提供单步判断"]
        return [f"缺少只读感知能力：{cap}" for cap in entry.inspection_capabilities
                if cap not in env.capabilities]

    def describe(self, environment: WorkflowEnvironment) -> tuple[WorkflowDescription, ...]:
        descriptions = []
        for entry in self._entries.values():
            reasons = self._availability(entry, environment)
            descriptions.append(WorkflowDescription(
                metadata=entry.metadata,
                params_schema=entry.params_model.model_json_schema(),
                mode=environment.mode,
                available=not reasons,
                unavailable_reasons=tuple(reasons),
                inspection_available=not self._inspection_availability(entry, environment),
                inspection_unavailable_reasons=tuple(
                    self._inspection_availability(entry, environment)
                ),
            ))
        return tuple(descriptions)

    def _check(
        self, plugin_id: str, plugin_version: str, params: Mapping[str, object],
        environment: WorkflowEnvironment, task_id: str | None, inspection: bool = False,
    ) -> tuple[ValidationReport, WorkflowParams | None]:
        entry = self._entries.get(plugin_id)
        if entry is None:
            return ValidationReport(valid=False, reasons=("未知流程插件。",)), None
        reasons = (self._inspection_availability(entry, environment) if inspection
                   else self._availability(entry, environment))
        if plugin_version != entry.metadata.version:
            reasons.append("插件版本不匹配。")
        if task_id is not None and task_id != entry.metadata.task_id:
            reasons.append("任务与流程插件不匹配。")
        validated = None
        try:
            validated = entry.params_model.model_validate(params, strict=True)
        except ValidationError as exc:
            for error in exc.errors(include_input=False, include_url=False):
                location = ".".join(str(part) for part in error["loc"])
                reasons.append(f"参数 {location}：{error['msg']}")
        return ValidationReport(valid=not reasons, reasons=tuple(reasons)), validated

    def validate(
        self, plugin_id: str, plugin_version: str, params: Mapping[str, object],
        environment: WorkflowEnvironment, *, task_id: str,
    ) -> ValidationReport:
        report, _ = self._check(plugin_id, plugin_version, params, environment, task_id)
        return report

    def prepare(
        self, plugin_id: str, plugin_version: str, params: Mapping[str, object],
        environment: WorkflowEnvironment, *, task_id: str,
    ) -> PreparedWorkflow:
        report, validated = self._check(plugin_id, plugin_version, params, environment, task_id)
        if not report.valid:
            raise WorkflowUnavailable(report)
        return self._instantiate(plugin_id, validated)

    def prepare_inspection(
        self, plugin_id: str, plugin_version: str, params: Mapping[str, object],
        environment: WorkflowEnvironment,
    ) -> PreparedInspection:
        report, validated = self._check(
            plugin_id, plugin_version, params, environment, None, inspection=True,
        )
        if not report.valid:
            raise WorkflowUnavailable(report)
        prepared = self._instantiate(plugin_id, validated)
        return PreparedInspection(
            plugin=cast(WorkflowEvaluator[Any], prepared.plugin), params=prepared.params,
        )

    def _instantiate(self, plugin_id: str, validated: WorkflowParams | None) -> PreparedWorkflow:
        entry = self._entries[plugin_id]
        plugin = entry.factory()
        if plugin.metadata != entry.metadata or plugin.params_model is not entry.params_model:
            raise ValueError("Workflow factory changed its registered contract")
        if entry.inspection_ready and not callable(getattr(plugin, "evaluate", None)):
            raise ValueError("Workflow factory removed its registered evaluator")
        if validated is None:
            raise ValueError("Validated workflow parameters are missing")
        return PreparedWorkflow(plugin=plugin, params=validated)
