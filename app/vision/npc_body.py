"""Registered NPC appearance references, reusing bounded name-associated matching."""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from app.vision.body import BodyLocator
from app.vision.models import BodyReading, SceneNameReading, VisionProfile

_SOURCE = Path(__file__).resolve().parents[2] / "samples" / "tasks" / "1.png"
# Reference artwork only: full hat-to-boots crop, no name tag or speech bubble.
_CROP = (411, 408, 461, 477)


class NpcBodyLocator(BodyLocator):
    def load_template(self):
        if self._template is None:
            with Image.open(_SOURCE) as source:
                if source.size != (1382, 807):
                    raise ValueError("Invalid NPC reference size")
                rgb = np.array(source.convert("RGB").crop(_CROP))
            self._template = rgb[:, :, ::-1].copy()
            self._template.flags.writeable = False
            self._version = hashlib.sha256(self._template.tobytes()).hexdigest()[:16]
        return self._template, self._version

    def locate(
        self, bgr: np.ndarray, profile: VisionProfile, name: SceneNameReading,
    ) -> BodyReading:
        # NPC settings are independent of the player template/threshold/switch.
        npc_profile = profile.model_copy(update={
            "body_template": "normal", "body_min_score": 0.85,
            "body_search_width": 200, "body_search_height": 150,
        })
        reading = super().locate(bgr, npc_profile, name)
        return reading.model_copy(update={"template_id": "npc_charlie"})
