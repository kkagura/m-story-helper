"""Shared service lifecycle; capture and recognition are not implemented yet."""

import logging
import time
from typing import Literal

from pydantic import BaseModel

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
    def __init__(self) -> None:
        self._started_at: float | None = None

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
            capabilities=Capabilities(),
        )
