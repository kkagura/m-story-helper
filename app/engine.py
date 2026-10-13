"""Shared service lifecycle and implemented capabilities, separate from active sessions."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from app.media.frames import ReceivedFrame
from app.state.observation import ObservationSnapshot
from app.vision.character import read_character
from app.vision.models import ObservationResult, VisionFailure, VisionProfile
from app.vision.names import PlayerNameReader
from app.vision.numbers import read_values

logger = logging.getLogger(__name__)


class Capabilities(BaseModel):
    capture: bool = False
    vision: bool = False
    planning: bool = False
    input: bool = False


class EngineStatus(BaseModel):
    state: Literal["stopped", "idle"]
    uptime_seconds: float
    capabilities: Capabilities


class EngineService:
    def __init__(
        self, *, capture_available: bool = False, profile_path: Path | None = None
    ) -> None:
        self._started_at: float | None = None
        self._capture_available = capture_available
        self._profile_path = profile_path
        self._profile = (
            VisionProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
            if profile_path and profile_path.is_file()
            else VisionProfile(reference_size=(1, 1))
        )
        self._analysis_task: asyncio.Task | None = None
        self._profile_lock = asyncio.Lock()
        self._name_reader = PlayerNameReader()

    @property
    def profile(self) -> VisionProfile:
        return self._profile

    async def save_profile(self, profile: VisionProfile) -> None:
        if self._profile_path is None:
            raise VisionFailure(409, "未配置区域保存路径。")
        async with self._profile_lock:
            path = self._profile_path

            def write():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
                try:
                    temporary.write_text(
                        json.dumps(profile.model_dump(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)

            async def persist():
                try:
                    await asyncio.to_thread(write)
                except OSError as exc:
                    raise VisionFailure(500, "保存区域配置失败，请检查文件写入权限。") from exc
                self._profile = profile

            task = asyncio.create_task(persist())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def analyze(
        self, frame: ReceivedFrame, profile: VisionProfile | None = None
    ) -> ObservationSnapshot:
        if self._analysis_task is not None and not self._analysis_task.done():
            raise VisionFailure(429, "已有识别正在进行，请稍后重试。")
        selected = profile if profile is not None else self.profile

        def run():
            start = time.monotonic()
            player_name = self._name_reader.read(frame.bgr, selected)
            hp_numbers = read_values(self._name_reader, frame.bgr, selected, "hp")
            mp_numbers = read_values(self._name_reader, frame.bgr, selected, "mp")
            player_level, player_job, experience = read_character(
                self._name_reader, frame.bgr, selected,
            )
            result = ObservationResult(
                observation_id=f"{frame.session_id}:{frame.frame_id}:{selected.version}",
                session_id=frame.session_id, frame_id=frame.frame_id,
                size_version=frame.size_version, source=frame.source,
                source_size=(frame.width, frame.height), profile_version=selected.version,
                processing_ms=round((time.monotonic() - start) * 1000, 3),
                player_name=player_name,
                hp_numbers=hp_numbers, mp_numbers=mp_numbers,
                player_level=player_level, player_job=player_job, experience=experience,
            )
            return ObservationSnapshot(frame=frame, result=result)

        task = asyncio.create_task(asyncio.to_thread(run))
        self._analysis_task = task

        def finished(completed):
            if self._analysis_task is completed:
                self._analysis_task = None
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def close_jobs(self) -> None:
        if self._analysis_task is not None:
            await asyncio.gather(self._analysis_task, return_exceptions=True)

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = time.monotonic()
            logger.info("Engine service started; no capture or task is active")

    def stop(self) -> None:
        self._started_at = None
        logger.info("Engine service stopped")

    def status(self) -> EngineStatus:
        started_at = self._started_at
        return EngineStatus(
            state="idle" if started_at is not None else "stopped",
            uptime_seconds=(
                round(time.monotonic() - started_at, 3) if started_at is not None else 0.0
            ),
            capabilities=Capabilities(
                capture=self._capture_available, vision=self._profile_path is not None
            ),
        )
