"""Workflow SDK checks only; no game OCR, input, runner or real completion claims."""

import asyncio
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from pydantic import ValidationError

from app.workflows import create_builtin_registry
from app.workflows.base import ActionReceipt, EvidenceRef, ToolResult, WorkflowResult
from app.workflows.builtin.charlie_exchange import CharlieExchangeParams, CharlieExchangeWorkflow
from app.workflows.context import RunContext, WorkflowControl, WorkflowPaused
from app.workflows.registry import (
    WorkflowEnvironment,
    WorkflowRegistry,
    WorkflowUnavailable,
)
from app.workflows.tools.base import WorkflowTools


def all_capabilities(mode="mock"):
    meta = CharlieExchangeWorkflow.metadata
    return WorkflowEnvironment(
        mode=mode,
        capabilities=frozenset(meta.required_capabilities),
        allowed_actions=frozenset(meta.allowed_actions),
    )


def test_builtin_stays_unavailable_even_with_all_declared_capabilities():
    registry = create_builtin_registry()
    for mode in ("mock", "real"):
        description, = registry.describe(all_capabilities(mode))
        assert description.metadata.id == "orbis_charlie_exchange"
        assert not description.available
        assert "骨架" in description.unavailable_reasons[0]
        with pytest.raises(WorkflowUnavailable):
            registry.prepare(
                description.metadata.id, "1.3.0", {}, all_capabilities(mode),
                task_id="npc_material_exchange",
            )


def test_missing_capabilities_and_actions_are_explicit_and_mode_specific():
    description, = create_builtin_registry().describe(WorkflowEnvironment(mode="real"))
    assert any("real 模式缺少能力：dialogue_ocr" == r
               for r in description.unavailable_reasons)
    assert any("real 模式不允许动作：mouse_click" == r
               for r in description.unavailable_reasons)


@pytest.mark.parametrize("changes", [
    {"material_count": True}, {"material_count": "100"}, {"material_count": 0},
    {"max_scrolls": 21}, {"step_timeout_ms": 0}, {"npc_name": ""},
    {"window_handle": 123},
])
def test_business_parameters_reject_coercion_range_and_host_fields(changes):
    with pytest.raises(ValidationError):
        CharlieExchangeParams.model_validate(changes)


class ReadyTestWorkflow(CharlieExchangeWorkflow):
    """Registration fixture only: never enable the production placeholder."""

    metadata = CharlieExchangeWorkflow.metadata.model_copy(update={"id": "ready_fixture"})


def ready_registry():
    registry = WorkflowRegistry()
    registry.register(ReadyTestWorkflow, implementation_ready=True)
    return registry


def test_prepare_validates_defaults_and_creates_isolated_instances_without_running():
    registry = ready_registry()
    args = ("ready_fixture", "1.3.0", {}, all_capabilities())
    first = registry.prepare(*args, task_id="npc_material_exchange")
    second = registry.prepare(*args, task_id="npc_material_exchange")
    assert first.plugin is not second.plugin
    assert first.params is not second.params
    assert first.params.material_count == 100
    first.plugin.private_state = "first run"
    assert not hasattr(second.plugin, "private_state")
    with pytest.raises(ValidationError):
        first.params.material_count = 200


def test_catalog_schema_changes_cannot_modify_registered_defaults():
    registry = ready_registry()
    first, = registry.describe(all_capabilities())
    first.params_schema["properties"]["material_count"]["default"] = 500
    second, = registry.describe(all_capabilities())
    assert second.params_schema["properties"]["material_count"]["default"] == 100


@pytest.mark.parametrize(("plugin_id", "version", "params", "task_id", "reason"), [
    ("missing", "1.3.0", {}, "npc_material_exchange", "未知"),
    ("ready_fixture", "2.0.0", {}, "npc_material_exchange", "版本"),
    ("ready_fixture", "1.3.0", {}, "different_task", "任务"),
    ("ready_fixture", "1.3.0", {"material_count": False}, "npc_material_exchange", "参数"),
])
def test_invalid_selections_never_prepare(plugin_id, version, params, task_id, reason):
    registry = ready_registry()
    report = registry.validate(
        plugin_id, version, params, all_capabilities(), task_id=task_id,
    )
    assert not report.valid and any(reason in message for message in report.reasons)
    with pytest.raises(WorkflowUnavailable):
        registry.prepare(plugin_id, version, params, all_capabilities(), task_id=task_id)


def test_duplicate_and_unsupported_registration_do_not_replace_existing_plugin():
    registry = ready_registry()
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(ReadyTestWorkflow, implementation_ready=True)

    class Unsupported(ReadyTestWorkflow):
        metadata = ReadyTestWorkflow.metadata.model_copy(update={"id": "other", "api_version": 2})

    with pytest.raises(ValueError, match="Unsupported"):
        registry.register(Unsupported, implementation_ready=True)
    assert len(registry.describe(all_capabilities())) == 1


def test_factory_contract_cannot_change_between_registration_and_preparation():
    calls = []

    def factory():
        calls.append(1)
        return ReadyTestWorkflow() if len(calls) == 1 else CharlieExchangeWorkflow()

    registry = WorkflowRegistry()
    registry.register(factory, implementation_ready=True)
    with pytest.raises(ValueError, match="changed"):
        registry.prepare(
            "ready_fixture", "1.3.0", {}, all_capabilities(), task_id="npc_material_exchange",
        )


def evidence():
    return EvidenceRef(
        id="e1", run_id="run1", observation_id="o1", session_id="session1",
        frame_id=1, size_version=1, profile_version="profile1",
    )


def test_unknown_tool_result_preserves_possible_sent_input_without_success_value():
    receipt = ActionReceipt(
        action_ids=("a1",), effect="outcome_unknown", verification="unknown", evidence=(),
    )
    result = ToolResult[str](
        status="unknown", value=None, code="outcome_unknown", message="等待确认",
        evidence=(), receipt=receipt,
    )
    assert result.receipt.effect == "outcome_unknown"
    with pytest.raises(ValidationError):
        ToolResult[str](
            status="unknown", value="success", code="invalid", message="",
            evidence=(), receipt=receipt,
        )


def test_actions_and_success_claims_require_their_evidence():
    with pytest.raises(ValidationError):
        ActionReceipt(action_ids=(), effect="sent", verification="not_checked", evidence=())
    with pytest.raises(ValidationError):
        WorkflowResult(
            status="succeeded", code="done", message="", last_step=None, data={}, evidence=(),
        )
    claim = WorkflowResult(
        status="succeeded", code="done", message="待独立验证", last_step=None,
        data={"rounds": 1}, evidence=(evidence(),),
    )
    assert claim.status == "succeeded"  # A claim, not an engine-verified run result.


@pytest.mark.parametrize("data", [{"value": float("nan")}, {"text": "x" * 17000}])
def test_summary_data_must_be_finite_and_bounded(data):
    with pytest.raises((ValidationError, ValueError)):
        WorkflowResult(
            status="paused", code="paused", message="", last_step=None, data=data, evidence=(),
        )


def context(now=None, control=None):
    now = [0.0] if now is None else now
    control = WorkflowControl() if control is None else control
    ctx = RunContext(
        run_id="run1", session_id="session1", mode="mock", deadline_monotonic=10.0,
        tools=cast(WorkflowTools, object()), _control=control, _clock=lambda: now[0],
    )
    return ctx, control, now


def test_context_does_not_extend_revisited_steps_and_keeps_run_deadline():
    async def scenario():
        ctx, _, now = context()
        with pytest.raises(FrozenInstanceError):
            ctx.mode = "real"
        await ctx.set_step("intro", timeout_ms=1000)
        now[0] = 0.5
        await ctx.set_step("intro", timeout_ms=60000)
        assert ctx.effective_deadline == 1.0
        await ctx.set_step("trade", timeout_ms=60000)
        assert ctx.effective_deadline == 10.0
        now[0] = 1.1
        with pytest.raises(WorkflowPaused, match="超时") as caught:
            await ctx.set_step("intro", timeout_ms=60000)
        assert caught.value.code == "step_timeout"

    asyncio.run(scenario())


def test_context_rejects_invalid_step_timeout_before_mutating_state():
    async def scenario():
        ctx, state, _ = context()
        for timeout in (True, 99, 60001):
            with pytest.raises(ValueError):
                await ctx.set_step("intro", timeout_ms=timeout)
        assert state.last_step is None and not state.step_deadlines

    asyncio.run(scenario())


@pytest.mark.parametrize(("kind", "code"), [
    ("pause", "pause_requested"), ("session", "session_invalid"), ("timeout", "run_timeout"),
])
def test_cooperative_checks_distinguish_pause_session_and_timeout(kind, code):
    async def scenario():
        ctx, state, now = context()
        if kind == "pause":
            state.pause_reason = "用户暂停"
        elif kind == "session":
            state.session_valid = False
        else:
            now[0] = 10.0
        with pytest.raises(WorkflowPaused) as caught:
            await ctx.checkpoint()
        assert caught.value.code == code

    asyncio.run(scenario())


def test_direct_placeholder_call_propagates_stop_and_never_claims_success():
    async def scenario():
        ctx, state, _ = context()
        result = await CharlieExchangeWorkflow().run(ctx, CharlieExchangeParams())
        assert result.status == "paused" and result.code == "workflow_not_implemented"
        assert not result.evidence
        state.stop_requested = True
        with pytest.raises(asyncio.CancelledError):
            await CharlieExchangeWorkflow().run(ctx, CharlieExchangeParams())

    asyncio.run(scenario())


def test_registration_rejects_unsafe_parameter_models_and_sync_run():
    from app.workflows.base import WorkflowParams

    class MutableParams(WorkflowParams):
        model_config = {"frozen": False}

    class MutableWorkflow(ReadyTestWorkflow):
        params_model = MutableParams

    class SyncWorkflow(ReadyTestWorkflow):
        def run(self, ctx, params):
            raise AssertionError("Registration must not execute run")

    registry = WorkflowRegistry()
    with pytest.raises(ValueError, match="frozen"):
        registry.register(MutableWorkflow, implementation_ready=True)
    with pytest.raises(ValueError, match="async"):
        registry.register(SyncWorkflow, implementation_ready=True)
    assert registry.describe(all_capabilities()) == ()
