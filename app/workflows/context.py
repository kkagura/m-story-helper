"""Cooperative context primitives, not a task runner or input watchdog."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import TypeAdapter

from app.workflows.base import Identifier, Mode
from app.workflows.tools.base import WorkflowTools

_STEP_ID = TypeAdapter(Identifier)


class WorkflowPaused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class WorkflowControl:
    """Host-owned control handle; do not pass it to workflow plugins."""

    stop_requested: bool = False
    pause_reason: str | None = None
    session_valid: bool = True
    last_step: str | None = None
    step_deadlines: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    session_id: str
    mode: Mode
    deadline_monotonic: float
    tools: WorkflowTools
    _control: WorkflowControl = field(repr=False)
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        if any(type(value) is not str or not 1 <= len(value) <= 256
               for value in (self.run_id, self.session_id)):
            raise ValueError("Run and session IDs must not be empty")
        if self.mode not in ("mock", "real"):
            raise ValueError("Unknown workflow mode")
        if (type(self.deadline_monotonic) not in (int, float)
                or not math.isfinite(self.deadline_monotonic)):
            raise ValueError("Run deadline must be finite")

    @property
    def last_step(self) -> str | None:
        return self._control.last_step

    @property
    def effective_deadline(self) -> float:
        step = self.last_step
        if step is None:
            return self.deadline_monotonic
        return min(self.deadline_monotonic, self._control.step_deadlines[step])

    async def checkpoint(self) -> None:
        # Yield even when no tool is called so well-behaved loops remain cancellable.
        await asyncio.sleep(0)
        state = self._control
        if state.stop_requested:
            raise asyncio.CancelledError
        if state.pause_reason is not None:
            raise WorkflowPaused("pause_requested", state.pause_reason)
        if not state.session_valid:
            raise WorkflowPaused("session_invalid", "捕获会话已失效。")
        now = self._clock()
        if now >= self.deadline_monotonic:
            raise WorkflowPaused("run_timeout", "流程运行时间已耗尽。")
        if now >= self.effective_deadline:
            raise WorkflowPaused("step_timeout", "当前步骤已超时。")

    async def set_step(self, step_id: str, *, timeout_ms: int) -> None:
        _STEP_ID.validate_python(step_id, strict=True)
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 60000:
            raise ValueError("Step timeout must be an integer in 100..60000 ms")
        await self.checkpoint()
        state = self._control
        if step_id not in state.step_deadlines and len(state.step_deadlines) >= 256:
            raise WorkflowPaused("step_limit", "业务步骤数量已达到上限。")
        proposed = min(self.deadline_monotonic, self._clock() + timeout_ms / 1000)
        state.step_deadlines[step_id] = min(state.step_deadlines.get(step_id, proposed), proposed)
        state.last_step = step_id
        await self.checkpoint()
