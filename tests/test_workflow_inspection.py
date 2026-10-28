"""Read-only decision tests: these do not validate actual model or input behavior."""

import io
import time
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.api.server import create_app
from app.config import Settings
from app.vision.dialogue import extract_dialogue
from app.vision.models import DialogueText, VisionProfile
from app.workflows import create_builtin_registry
from app.workflows.builtin.charlie_exchange import CharlieExchangeParams, CharlieExchangeWorkflow
from app.workflows.inspection import InspectionContext, StepIntent, WorkflowInspection
from app.workflows.perception import SnapshotPerception
from app.workflows.registry import WorkflowEnvironment, WorkflowUnavailable

PANEL = (100, 100, 520, 200)
VERSION = CharlieExchangeWorkflow.metadata.version


def row(text, x=265, y=155, width=330, score=0.95):
    return DialogueText(text=text, confidence=score, bbox=(x, y, width, 14))


def decide(rows, **params):
    reading = extract_dialogue(PANEL, tuple(rows))
    context = InspectionContext(
        snapshot=SimpleNamespace(result=SimpleNamespace(observation_id="fixture")),
        perception=SimpleNamespace(dialogue=lambda: reading),
        deadline_monotonic=time.monotonic() + 60,
    )
    return CharlieExchangeWorkflow().evaluate(context, CharlieExchangeParams(**params))


@pytest.mark.parametrize(("phrase", "button", "stage"), [
    ("不愿意跟我交易呢", "下项", "intro"),
    ("交易其实很简单", "是", "trade"),
    ("你确定要交换吗", "是", "confirmation"),
    ("已经交换成功了", "结束对话", "success"),
])
def test_single_step_decision_preserves_missing_identity(phrase, button, stage):
    result = decide([row(phrase), row(button, x=500, y=280, width=80)])
    assert result.status == "found" and result.stage_id == stage
    assert result.intent.kind == "click" and result.intent.execution_authorized is False
    assert result.missing_conditions and result.fields[0].value is None
    assert any(a.id == result.intent.target_id for a in result.annotations)
    if stage == "success":
        assert any("未判定完成" in condition for condition in result.missing_conditions)


def test_wrong_visible_npc_and_unknown_page_do_not_propose_actions():
    result = decide([
        row("你确定要交换吗"), row("别的中士", x=130, y=210, width=100),
        row("是", x=520, y=280, width=35),
    ])
    assert result.status == "unknown" and result.intent is None
    assert decide([row("请购买商品")]).intent is None


def test_conflict_ambiguity_low_confidence_and_uncertain_fragments_stop_decision():
    cases = [
        [row("你确定要交换吗"), row("已经交换成功了", y=180)],
        [row("你确定要交换吗"), row("是", x=520, y=280, width=35),
         row("是", x=560, y=280, width=35)],
        [row("你确定要交换吗"), row("是", x=520, y=280, width=35, score=0.79)],
        [row("已经", y=150), row("不可靠", y=170, score=0.5), row("交换成功了", y=190)],
    ]
    for rows in cases:
        result = decide(rows)
        assert result.status in ("unknown", "ambiguous") and result.intent is None


def test_business_parameters_control_material_search_without_shared_tool_changes():
    result = decide([
        row("你先决定拿什么东西换吧"), row("自定义材料 ２００ 个", y=185),
    ], material_name="自定义材料", material_count=200)
    assert result.intent.kind == "click"
    hidden = decide([row("你先决定拿什么东西换吧")], max_scrolls=3)
    assert hidden.intent.kind == "scroll" and "3" in hidden.intent.label
    no_scroll = decide([row("你先决定拿什么东西换吧")], max_scrolls=0)
    assert no_scroll.intent.kind == "wait"


def test_chat_text_cannot_create_success_and_success_never_uses_next_button():
    result = decide([
        row("交易其实很简单"), row("已经交换成功了", x=100, y=500),
    ])
    assert result.stage_id == "trade"
    success = decide([row("已经交换成功了"), row("下项", x=520, y=245, width=60)])
    assert success.intent.kind == "wait" and success.intent.target_id is None


def test_inspection_and_execution_availability_are_independent():
    registry = create_builtin_registry()
    env = WorkflowEnvironment(
        capabilities=frozenset({"dialogue_reading", "npc_name_reading", "npc_body_matching"}),
    )
    description, = registry.describe(env)
    assert description.inspection_available and not description.available
    prepared = registry.prepare_inspection("orbis_charlie_exchange", VERSION, {}, env)
    assert isinstance(prepared.params, CharlieExchangeParams)
    with pytest.raises(WorkflowUnavailable):
        registry.prepare(
            "orbis_charlie_exchange", VERSION, {}, env, task_id="npc_material_exchange",
        )
    for plugin_id, version, params in [
        ("unknown", VERSION, {}), ("orbis_charlie_exchange", "0.0.0", {}),
        ("orbis_charlie_exchange", VERSION, {"material_count": True}),
    ]:
        with pytest.raises(WorkflowUnavailable):
            registry.prepare_inspection(plugin_id, version, params, env)


def test_inspection_models_reject_execution_permission_and_bad_target_reference():
    with pytest.raises(ValidationError):
        StepIntent(kind="click", label="点击", reason="测试", execution_authorized=True)
    with pytest.raises(ValidationError):
        WorkflowInspection(
            plugin_id="fixture", plugin_version="1.0.0", observation_id="o1", status="found",
            intent=StepIntent(kind="click", label="点击", reason="测试", target_id="missing"),
        )
    ctx = InspectionContext(None, None, 0)
    assert not hasattr(ctx, "tools") and not hasattr(ctx, "mouse")
    with pytest.raises(TimeoutError):
        ctx.checkpoint()


def test_same_snapshot_dialogue_is_cached(monkeypatch):
    sentinel = object()
    calls = []

    def read(reader, bgr, profile):
        calls.append((reader, bgr, profile))
        return sentinel

    monkeypatch.setattr("app.workflows.perception.read_dialogue", read)
    pixels = np.zeros((1, 1, 3), dtype=np.uint8)
    snapshot = SimpleNamespace(frame=SimpleNamespace(bgr=pixels))
    perception = SnapshotPerception(snapshot, "reader", "profile")
    assert perception.cached_dialogue is None
    assert perception.dialogue() is sentinel and perception.dialogue() is sentinel
    assert len(calls) == 1 and calls[0][1] is pixels


def test_base_analysis_skips_flow_and_api_discovers_registry(tmp_path, monkeypatch):
    def forbidden(*_):
        pytest.fail("No selected flow must not run dialogue perception")

    monkeypatch.setattr("app.workflows.perception.read_dialogue", forbidden)
    settings = Settings(vision_profile=str(tmp_path / "vision.json"), web_dist=str(tmp_path))
    payload = io.BytesIO()
    Image.new("RGB", (100, 100)).save(payload, format="PNG")
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        catalog = client.get("/api/workflows").json()
        assert catalog[0]["inspection_available"] and not catalog[0]["available"]
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        profile = VisionProfile(reference_size=(100, 100))
        response = client.post(
            f"/api/images/{image_id}/analyze", json={"profile": profile.model_dump()},
        )
        assert response.status_code == 200
        assert response.json()["workflow_inspection"] is None
        assert response.json()["dialogue"] is None
        invalid = client.post(f"/api/images/{image_id}/analyze", json={
            "profile": profile.model_dump(), "workflow": {
                "plugin_id": "orbis_charlie_exchange", "plugin_version": VERSION,
                "params": {"material_count": "100"},
            },
        })
        assert invalid.status_code == 422


def test_another_plugin_can_expose_different_fields_without_dialogue_or_frontend_rules(
    tmp_path, monkeypatch,
):
    from app.workflows.base import WorkflowParams
    from app.workflows.inspection import InspectionField

    class OtherParams(WorkflowParams):
        label: str = "来自另一个插件"

    class OtherPlugin(CharlieExchangeWorkflow):
        metadata = CharlieExchangeWorkflow.metadata.model_copy(update={"id": "other_fixture"})
        params_model = OtherParams

        def evaluate(self, ctx, params):
            assert not hasattr(ctx, "tools")
            return WorkflowInspection(
                plugin_id=self.metadata.id, plugin_version=self.metadata.version,
                observation_id=ctx.snapshot.result.observation_id, status="found",
                stage_id="custom_stage", stage_label="自定义阶段",
                fields=(InspectionField(key="custom", label="自定义信息", value=params.label),),
            )

    def forbidden(*_):
        pytest.fail("Plugin without dialogue requirement must not run dialogue OCR")

    monkeypatch.setattr("app.workflows.perception.read_dialogue", forbidden)
    app = create_app(Settings(vision_profile=str(tmp_path / "vision.json"), web_dist=str(tmp_path)))
    app.state.engine.workflows.register(
        OtherPlugin, implementation_ready=False, unavailable_reason="test only",
        inspection_ready=True,
    )
    payload = io.BytesIO()
    Image.new("RGB", (100, 100)).save(payload, format="PNG")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert len(client.get("/api/workflows").json()) == 2
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        response = client.post(f"/api/images/{image_id}/analyze", json={
            "profile": VisionProfile(reference_size=(100, 100)).model_dump(),
            "workflow": {"plugin_id": "other_fixture", "plugin_version": VERSION,
                         "params": {"label": "覆盖参数"}},
        })
        assert response.status_code == 200
        result = response.json()
        assert result["workflow_inspection"]["stage_label"] == "自定义阶段"
        assert result["workflow_inspection"]["fields"][0]["value"] == "覆盖参数"
        assert result["dialogue"] is None


def test_plugin_failure_preserves_base_information_and_returns_no_intent(tmp_path):
    class Broken(CharlieExchangeWorkflow):
        metadata = CharlieExchangeWorkflow.metadata.model_copy(update={"id": "broken_fixture"})

        def evaluate(self, ctx, params):
            raise RuntimeError("Private implementation details")

    app = create_app(Settings(vision_profile=str(tmp_path / "vision.json"), web_dist=str(tmp_path)))
    app.state.engine.workflows.register(
        Broken, implementation_ready=False, unavailable_reason="test only", inspection_ready=True,
    )
    payload = io.BytesIO()
    Image.new("RGB", (100, 100)).save(payload, format="PNG")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        response = client.post(f"/api/images/{image_id}/analyze", json={
            "profile": VisionProfile(reference_size=(100, 100)).model_dump(),
            "workflow": {"plugin_id": "broken_fixture", "plugin_version": VERSION, "params": {}},
        })
        assert response.status_code == 200
        result = response.json()
        assert result["workflow_inspection"]["status"] == "unknown"
        assert result["workflow_inspection"]["intent"] is None
        assert result["player_name"]["status"] == "unknown"
        assert "Private" not in response.text


@pytest.mark.parametrize("failure", ["wrong_frame", "out_of_bounds"])
def test_engine_rejects_cross_frame_or_outside_annotations(tmp_path, failure):
    from app.workflows.inspection import InspectionAnnotation

    class BadResult(CharlieExchangeWorkflow):
        metadata = CharlieExchangeWorkflow.metadata.model_copy(update={"id": "bad_result"})

        def evaluate(self, ctx, params):
            return WorkflowInspection(
                plugin_id=self.metadata.id, plugin_version=self.metadata.version,
                observation_id="different" if failure == "wrong_frame" else
                ctx.snapshot.result.observation_id, status="found",
                annotations=(InspectionAnnotation(
                    id="outside", label="目标", kind="target", bbox=(200, 20, 10, 10),
                ),) if failure == "out_of_bounds" else (),
            )

    app = create_app(Settings(vision_profile=str(tmp_path / "vision.json"), web_dist=str(tmp_path)))
    app.state.engine.workflows.register(
        BadResult, implementation_ready=False, unavailable_reason="fixture", inspection_ready=True,
    )
    payload = io.BytesIO()
    Image.new("RGB", (100, 100)).save(payload, format="PNG")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        image_id = client.post("/api/images", content=payload.getvalue()).json()["image_id"]
        result = client.post(f"/api/images/{image_id}/analyze", json={
            "profile": VisionProfile(reference_size=(100, 100)).model_dump(),
            "workflow": {"plugin_id": "bad_result", "plugin_version": VERSION, "params": {}},
        }).json()
        inspected = result["workflow_inspection"]
        assert inspected["observation_id"] == result["observation_id"]
        assert inspected["status"] == "unknown" and not inspected["annotations"]
        assert inspected["intent"] is None
