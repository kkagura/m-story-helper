"""Tool data and signatures only; no OCR, Mock actions or Windows input here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from app.workflows.base import ActionReceipt, EvidenceRef, ToolResult

if TYPE_CHECKING:
    from app.state.observation import ObservationSnapshot


@dataclass(frozen=True)
class RegionRef:
    id: str
    evidence: EvidenceRef
    bbox: tuple[int, int, int, int]
    kind: str


@dataclass(frozen=True)
class TargetRef:
    id: str
    evidence: EvidenceRef
    bbox: tuple[int, int, int, int]
    kind: str
    identity: str
    confidence: float


@dataclass(frozen=True)
class TextRead:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]
    evidence: EvidenceRef


@dataclass(frozen=True)
class DialogueRef:
    id: str
    npc_name: str
    dialogue_region: RegionRef
    content_region: RegionRef
    list_region: RegionRef | None
    evidence: EvidenceRef


@dataclass(frozen=True)
class DialogueEvidence:
    dialogue: DialogueRef
    matched_text: str
    evidence: EvidenceRef


@dataclass(frozen=True)
class ClosedEvidence:
    dialogue_id: str
    opened: EvidenceRef
    closed: EvidenceRef


@dataclass(frozen=True)
class SelectionEvidence:
    material_name: str
    count: int
    confirmation: DialogueEvidence
    scrolls: int


class VisionTools(Protocol):
    async def observe(self, *, timeout_ms: int) -> ToolResult[ObservationSnapshot]: ...

    async def read_text(self, region: RegionRef, *, timeout_ms: int) -> ToolResult[TextRead]: ...

    async def find_image(
        self, template_id: str, region: RegionRef, *, timeout_ms: int,
    ) -> ToolResult[TargetRef]: ...

    async def find_npc(self, name: str, *, timeout_ms: int) -> ToolResult[TargetRef]: ...


class MouseTools(Protocol):
    async def click(
        self, target: TargetRef, button: Literal["left", "right"] = "left", *, timeout_ms: int,
    ) -> ToolResult[ActionReceipt]: ...

    async def scroll(
        self, region: RegionRef, direction: Literal["up", "down"], steps: int, *, timeout_ms: int,
    ) -> ToolResult[ActionReceipt]: ...


class KeyboardTools(Protocol):
    async def press(
        self, key: str, hold_ms: int, *, timeout_ms: int,
    ) -> ToolResult[ActionReceipt]: ...


class DialogueTools(Protocol):
    async def wait_text(
        self, npc_name: str, text: str, after: EvidenceRef | None = None, *, timeout_ms: int,
    ) -> ToolResult[DialogueEvidence]: ...

    async def click_option(
        self, page: DialogueEvidence, text: str, *, timeout_ms: int,
    ) -> ToolResult[ActionReceipt]: ...

    async def select_material(
        self, page: DialogueEvidence, name: str, count: int, max_scrolls: int,
        direction: Literal["down", "up"] = "down", scroll_steps: int = 3,
        confirmation_text: str = "你确定要交换吗", *, timeout_ms: int,
    ) -> ToolResult[SelectionEvidence]: ...

    async def wait_closed(
        self, dialogue: DialogueRef, after: EvidenceRef, *, timeout_ms: int,
    ) -> ToolResult[ClosedEvidence]: ...


@dataclass(frozen=True)
class WorkflowTools:
    vision: VisionTools
    mouse: MouseTools
    keyboard: KeyboardTools
    dialogue: DialogueTools
