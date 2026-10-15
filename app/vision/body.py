"""Bounded appearance-template matching above a confirmed name tag."""

import hashlib
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.vision.models import BodyCandidate, BodyReading, SceneNameReading, VisionProfile
from app.vision.scene import overlaps

_NORMAL_SOURCE = Path(__file__).resolve().parents[2] / "samples" / "normal.png"
# Development reference only: include the avatar, exclude its name/guild/pets.
_NORMAL_CROP = (653, 378, 724, 453)


class BodyLocator:
    def __init__(self):
        self._template: np.ndarray | None = None
        self._version: str | None = None

    def load_template(self):
        if self._template is None:
            with Image.open(_NORMAL_SOURCE) as source:
                if source.size != (1382, 807):
                    raise ValueError("Invalid reference size")
                rgb = np.array(source.convert("RGB").crop(_NORMAL_CROP))
            self._template = rgb[:, :, ::-1].copy()
            self._template.flags.writeable = False
            self._version = hashlib.sha256(self._template.tobytes()).hexdigest()[:16]
        return self._template, self._version

    def locate(
        self, bgr: np.ndarray, profile: VisionProfile, name: SceneNameReading,
    ) -> BodyReading:
        start = time.monotonic()
        search = None
        version = None

        def result(status="unknown", reason=None, **values):
            return BodyReading(
                status=status, reason=reason, search_bbox=search,
                template_id=profile.body_template, template_version=version,
                processing_ms=round((time.monotonic() - start) * 1000, 3), **values,
            )

        if name.status != "found" or name.name_bbox is None:
            return result(reason="name_not_confirmed")
        if profile.body_template is None:
            return result(reason="body_template_disabled")
        height, width = bgr.shape[:2]
        if (width, height) != profile.reference_size:
            return result(reason="reference_size_mismatch")
        if profile.scene is None:
            return result(reason="scene_not_configured")
        x, y, name_width, _ = name.name_bbox
        middle = x + name_width / 2
        scene = profile.scene
        left = max(scene.x, int(middle - profile.body_search_width / 2))
        right = min(width, scene.x + scene.width, int(middle + profile.body_search_width / 2))
        top = max(scene.y, y - profile.body_search_height)
        bottom = min(height, scene.y + scene.height, y)
        if right <= left or bottom <= top:
            return result(reason="body_search_empty")
        search = (left, top, right - left, bottom - top)
        try:
            import cv2
        except ImportError:
            return result(reason="body_dependency_missing")
        try:
            template, version = self.load_template()
        except (OSError, ValueError):
            return result(reason="body_template_unavailable")
        try:
            th, tw = template.shape[:2]
            if th > bottom - top or tw > right - left:
                return result(reason="body_search_too_small")
            # CCOEFF on constant templates/searches can be misleading; reject them.
            gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            patch = cv2.cvtColor(bgr[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
            if gray_template.std() < 1 or patch.std() < 1:
                return result(status="not_found", reason="body_low_texture")
            scores = cv2.matchTemplate(patch, gray_template, cv2.TM_CCOEFF_NORMED)
            scores[~np.isfinite(scores)] = -1
            excluded = tuple(region for region in (
                profile.player_info, profile.player_name, profile.player_level, profile.player_job,
                profile.hp_text, profile.mp_text, profile.exp_text, *profile.scene_exclusions,
            ) if region is not None)
            candidates = []
            best = max(0.0, min(1.0, float(scores.max())))
            # At most 9 peaks; the ninth means overflow rather than silent truncation.
            for _ in range(9):
                _, score, _, location = cv2.minMaxLoc(scores)
                if score < profile.body_min_score or score <= 0:
                    break
                px, py = location
                box = (left + px, top + py, tw, th)
                if box[0] + tw <= x or box[0] >= x + name_width:
                    return result(reason="body_not_above_name", score=best)
                if any(overlaps(box, roi) for roi in excluded):
                    scores[py, px] = -1
                    # Bound invalid-peak handling; do not interpret remaining peaks as unique.
                    return result(reason="body_overlaps_ui", score=best)
                candidates.append(BodyCandidate(bbox=box, score=min(1.0, score)))
                # Suppress overlapping placements of the same template instance.
                scores[max(0, py - th + 1):py + th, max(0, px - tw + 1):px + tw] = -1
            if len(candidates) > 8:
                return result(reason="body_candidate_limit", score=best)
            if not candidates:
                return result(status="not_found", reason="no_body_match", score=best)
            if len(candidates) > 1:
                return result(status="ambiguous", reason="multiple_body_matches",
                              candidates=tuple(candidates), score=best)
            box = candidates[0].bbox
            # Derived box anchor; this is not an anatomical foot/ground detector.
            anchor = (box[0] + box[2] // 2, box[1] + box[3] - 1)
            return result(status="found", bbox=box, bottom_center=anchor,
                          candidates=tuple(candidates), score=best)
        except Exception:
            return result(reason="body_matching_failed")
