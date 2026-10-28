"""One-snapshot lazy perception cache. No input adapters or mutable media buffers."""

from app.state.observation import ObservationSnapshot
from app.vision.dialogue import read_dialogue
from app.vision.models import (
    BodyReading,
    DialogueReading,
    NameReading,
    SceneNameReading,
    VisionProfile,
)
from app.vision.names import PlayerNameReader
from app.vision.npc_body import NpcBodyLocator
from app.vision.scene import locate_name, normalized_name


class SnapshotPerception:
    def __init__(
        self, snapshot: ObservationSnapshot, reader: PlayerNameReader, profile: VisionProfile,
    ) -> None:
        self._snapshot = snapshot
        self._reader = reader
        self._profile = profile
        self._dialogue: DialogueReading | None = None
        self._npc_names: dict[str, SceneNameReading] = {}
        self._npc_bodies: dict[str, BodyReading] = {}
        self._npc_locator = NpcBodyLocator()

    @property
    def cached_dialogue(self) -> DialogueReading | None:
        return self._dialogue

    def dialogue(self) -> DialogueReading:
        if self._dialogue is None:
            self._dialogue = read_dialogue(
                self._reader, self._snapshot.frame.bgr, self._profile,
            )
        return self._dialogue


    def npc_name(self, name: str) -> SceneNameReading:
        key = normalized_name(name)
        if key not in self._npc_names:
            if len(self._npc_names) >= 8:
                raise ValueError("NPC name query limit exceeded")
            self._npc_names[key] = locate_name(
                self._reader, self._snapshot.frame.bgr, self._profile,
                NameReading(status="known", text=name),
            )
        return self._npc_names[key]


    def npc_body(self, name: str) -> BodyReading:
        key = normalized_name(name)
        if key not in self._npc_bodies:
            located_name = self.npc_name(name)
            self._npc_bodies[key] = self._npc_locator.locate(
                self._snapshot.frame.bgr, self._profile, located_name,
            )
        return self._npc_bodies[key]
