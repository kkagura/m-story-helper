"""Initial NPC name localization and preview decisions, not body/click verification."""

import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.vision.models import (
    BodyReading,
    DialogueReading,
    Rect,
    SceneNameCandidate,
    SceneNameReading,
    VisionProfile,
)
from app.vision.names import PlayerNameReader
from app.workflows.builtin.charlie_exchange import CharlieExchangeParams, CharlieExchangeWorkflow
from app.workflows.inspection import InspectionContext
from app.workflows.perception import SnapshotPerception


def candidate(score=0.95):
    return SceneNameCandidate(text="查里中士", confidence=score, bbox=(40, 50, 80, 16))


@pytest.mark.parametrize(("status", "candidates", "reason"), [
    ("found", (candidate(),), None),
    ("ambiguous", (candidate(), candidate()), "multiple_matching_names"),
    ("unknown", (candidate(0.7),), "low_confidence"),
    ("not_found", (), "no_matching_name"),
    ("unknown", (), "scene_not_configured"),
])
def test_initial_stage_requires_unique_confirmed_name(status, candidates, reason):
    reading = SceneNameReading(
        status=status, candidates=candidates, reason=reason,
        name_bbox=candidates[0].bbox if status == "found" else None,
    )
    ctx = InspectionContext(
        snapshot=SimpleNamespace(result=SimpleNamespace(observation_id="frame1")),
        perception=SimpleNamespace(
            dialogue=lambda: DialogueReading(status="not_found", reason="no_dialogue_panel"),
            npc_name=lambda _: reading,
            npc_body=lambda _: BodyReading(status="found", bbox=(50, 10, 40, 38)),
        ), deadline_monotonic=time.monotonic() + 60,
    )
    result = CharlieExchangeWorkflow().evaluate(ctx, CharlieExchangeParams())
    if status == "found":
        assert result.stage_id == "await_npc_interaction" and result.fields[0].value == "查里中士"
        assert result.intent.target_id == "npc_body"
        assert not result.intent.execution_authorized
        assert any("模板矩形" in condition for condition in result.missing_conditions)
    else:
        assert result.stage_id == "search_npc" and result.intent is None
        assert result.fields[0].value is None


def test_dialogue_ambiguity_does_not_fall_through_to_scene_search():
    def forbidden(_):
        pytest.fail("Uncertain dialogue must not be treated as an initial scene")

    ctx = InspectionContext(
        SimpleNamespace(result=SimpleNamespace(observation_id="frame1")),
        SimpleNamespace(dialogue=lambda: DialogueReading(status="ambiguous"), npc_name=forbidden),
        time.monotonic() + 60,
    )
    assert CharlieExchangeWorkflow().evaluate(ctx, CharlieExchangeParams()).intent is None


def test_scene_name_reader_uses_snapshot_and_caches_same_target(monkeypatch):
    rows = [[[[40, 50], [120, 50], [120, 66], [40, 66]], "查里中士", 0.95]]
    calls = []

    def ocr(pixels, **_):
        calls.append(pixels.shape)
        return rows, []

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: ocr)
    snapshot = SimpleNamespace(frame=SimpleNamespace(bgr=np.zeros((200, 300, 3), dtype=np.uint8)))
    profile = VisionProfile(reference_size=(300, 200), scene=Rect(x=0, y=0, width=300, height=180))
    perception = SnapshotPerception(snapshot, PlayerNameReader(), profile)
    first = perception.npc_name("查里中士")
    assert first.status == "found" and first.name_bbox == (40, 50, 80, 16)
    assert perception.npc_name("查里 中士") is first and len(calls) == 1


def test_missing_scene_does_not_infer_npc_from_requested_name():
    snapshot = SimpleNamespace(frame=SimpleNamespace(bgr=np.zeros((200, 300, 3), dtype=np.uint8)))
    perception = SnapshotPerception(
        snapshot, PlayerNameReader(), VisionProfile(reference_size=(300, 200)),
    )
    result = perception.npc_name("查里中士")
    assert result.status == "unknown" and result.name_bbox is None
    assert not result.candidates and result.reason == "scene_not_configured"


@pytest.mark.parametrize("status", ["not_found", "unknown", "ambiguous"])
def test_confirmed_name_without_confirmed_body_never_clicks_the_name(status):
    ctx = InspectionContext(
        SimpleNamespace(result=SimpleNamespace(observation_id="frame1")),
        SimpleNamespace(
            dialogue=lambda: DialogueReading(status="not_found", reason="no_dialogue_panel"),
            npc_name=lambda _: SceneNameReading(
                status="found", name_bbox=(40, 50, 80, 16), candidates=(candidate(),),
            ),
            npc_body=lambda _: BodyReading(status=status, reason="fixture_failure"),
        ), time.monotonic() + 60,
    )
    result = CharlieExchangeWorkflow().evaluate(ctx, CharlieExchangeParams())
    assert result.fields[0].value == "查里中士" and result.intent is None
    assert result.stage_id == "locate_npc_body"
