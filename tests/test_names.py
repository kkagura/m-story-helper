"""OCR response stubs test contracts; they do not establish model accuracy."""

import asyncio
import threading
import time

import numpy as np
import pytest

from app.engine import EngineService
from app.media.frames import ReceivedFrame
from app.vision.models import Rect, VisionFailure, VisionProfile
from app.vision.names import PlayerNameReader


def profile():
    return VisionProfile(
        reference_size=(120, 40), player_name=Rect(x=10, y=20, width=80, height=15),
    )


@pytest.mark.parametrize(
    ("rows", "status", "reason", "text"),
    [
        ([[[], "角色Ab12", 0.95]], "known", None, "角色Ab12"),
        ([[[], "候选名", 0.6]], "unknown", "low_confidence", None),
        (None, "unknown", "no_text", None),
        ([[[], "职业", 0.99], [[], "姓名", 0.99]],
         "unknown", "multiple_text_regions", None),
        ([[[], "错误", float("nan")]], "unknown", "ocr_invalid_output", None),
    ],
)
def test_name_result_policy_and_source_is_unchanged(monkeypatch, rows, status, reason, text):
    image = np.full((40, 120, 3), 30, dtype=np.uint8)
    original = image.copy()

    def fake_ocr(pixels, **options):
        assert pixels.shape == (61, 256, 3)
        assert options == {"use_cls": False, "text_score": 0.0}
        return rows, [0.01]

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fake_ocr)
    reading = PlayerNameReader().read(image, profile())
    assert (reading.status, reading.reason, reading.text) == (status, reason, text)
    assert reading.bbox == (10, 20, 80, 15)
    assert reading.processing_ms >= 0
    if reason == "low_confidence":
        assert reading.raw_text == "候选名"
        assert reading.confidence == 0.6
    np.testing.assert_array_equal(image, original)


def test_missing_region_and_mismatched_size_skip_model_loading(monkeypatch):
    def unexpected_load(_):
        pytest.fail("Invalid or missing ROI must not load OCR")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", unexpected_load)
    reader = PlayerNameReader()
    image = np.zeros((40, 120, 3), dtype=np.uint8)
    assert reader.read(image, VisionProfile(reference_size=(120, 40))).text is None
    assert reader.read(image[:, :100], profile()).reason == "reference_size_mismatch"


@pytest.mark.parametrize("error", [ImportError, RuntimeError])
def test_initialization_failure_is_cached_and_sanitized(monkeypatch, error):
    loads = []

    def fail_load(_):
        loads.append(True)
        raise error("private path or data")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", fail_load)
    reader = PlayerNameReader()
    image = np.zeros((40, 120, 3), dtype=np.uint8)
    first = reader.read(image, profile())
    second = reader.read(image, profile())
    assert first.reason == second.reason
    assert first.reason in {"ocr_dependency_missing", "ocr_initialization_failed"}
    assert len(loads) == 1
    assert "private" not in first.model_dump_json()


def test_inference_failure_returns_unknown_without_exception_details(monkeypatch):
    def fail_ocr(_pixels, **_options):
        raise RuntimeError("private text or path")

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: fail_ocr)
    reading = PlayerNameReader().read(np.zeros((40, 120, 3), dtype=np.uint8), profile())
    assert reading.reason == "ocr_failed"
    assert reading.text is None
    assert "private" not in reading.model_dump_json()


def test_engine_cancellation_does_not_allow_second_ocr_job(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow_ocr(_pixels, **_options):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test timed out")
        return [[[], "角色", 0.99]], [0.01]

    monkeypatch.setattr(PlayerNameReader, "_create_engine", lambda _: slow_ocr)

    async def scenario():
        engine = EngineService()
        frame = ReceivedFrame(
            session_id="test", frame_id=1, size_version=1,
            received_at_monotonic=time.monotonic(), converted_at_monotonic=time.monotonic(),
            media_timestamp_ms=None, width=120, height=40,
            bgr=np.zeros((40, 120, 3), dtype=np.uint8), source="screenshot",
        )
        task = asyncio.create_task(engine.analyze(frame, profile()))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(VisionFailure) as failure:
                await engine.analyze(frame, profile())
            assert failure.value.status_code == 429
        finally:
            release.set()
            await engine.close_jobs()

    asyncio.run(scenario())
