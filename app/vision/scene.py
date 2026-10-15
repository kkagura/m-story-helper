"""Find a name tag, not a body or tracked player, in one source frame."""

import math
import time
import unicodedata

import numpy as np
from PIL import Image

from app.vision.models import NameReading, SceneNameCandidate, SceneNameReading, VisionProfile
from app.vision.names import PlayerNameReader


def normalized_name(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def overlaps(box, roi) -> bool:
    x, y, width, height = box
    return (
        x < roi.x + roi.width and x + width > roi.x
        and y < roi.y + roi.height and y + height > roi.y
    )


def locate_name(
    reader: PlayerNameReader, bgr: np.ndarray, profile: VisionProfile, identity: NameReading,
) -> SceneNameReading:
    start = time.monotonic()
    roi = profile.scene
    search = (roi.x, roi.y, roi.width, roi.height) if roi else None

    def result(status="unknown", reason=None, **values):
        return SceneNameReading(
            status=status, reason=reason, search_bbox=search,
            target_name=identity.text if identity.status == "known" else None,
            processing_ms=round((time.monotonic() - start) * 1000, 3), **values,
        )

    if identity.status != "known" or not identity.text or not normalized_name(identity.text):
        return result(reason="identity_unknown")
    if roi is None:
        return result(reason="scene_not_configured")
    height, width = bgr.shape[:2]
    if (width, height) != profile.reference_size:
        return result(reason="reference_size_mismatch")
    if roi.x + roi.width > width or roi.y + roi.height > height:
        return result(reason="region_out_of_bounds")
    error = reader.ensure_engine()
    if error:
        return result(reason=error)
    # Automatically exclude all fixed information regions, plus explicit UI masks.
    excluded = tuple(region for region in (
        profile.player_info, profile.player_name, profile.player_level, profile.player_job,
        profile.hp_text, profile.mp_text, profile.exp_text, *profile.scene_exclusions,
    ) if region is not None)
    try:
        pixels = bgr[roi.y:roi.y + roi.height, roi.x:roi.x + roi.width].copy()
        for region in excluded:
            left, top = max(0, region.x - roi.x), max(0, region.y - roi.y)
            right = min(roi.width, region.x + region.width - roi.x)
            bottom = min(roi.height, region.y + region.height - roi.y)
            if left < right and top < bottom:
                pixels[top:bottom, left:right] = 0
        # Preserve color; map every detected quad back from this bounded image.
        scale = min(1.0, 1536 / max(roi.width, roi.height))
        size = (max(2, round(roi.width * scale)), max(2, round(roi.height * scale)))
        if size != (roi.width, roi.height):
            rgb = Image.fromarray(pixels[:, :, ::-1]).resize(size, Image.Resampling.LANCZOS)
            pixels = np.array(rgb)[:, :, ::-1].copy()
        rows, _ = reader.detect_text(pixels)
        if rows is None:
            rows = []
        if len(rows) > 256:
            return result(reason="scene_text_limit")
        matches = []
        text_count = 0
        for quad, text, confidence, *_ in rows:
            points = np.asarray(quad, dtype=float)
            score = float(confidence)
            if (points.shape != (4, 2) or not np.isfinite(points).all()
                    or not math.isfinite(score) or not 0 <= score <= 1):
                return result(reason="ocr_invalid_output")
            points[:, 0] = points[:, 0] * roi.width / size[0] + roi.x
            points[:, 1] = points[:, 1] * roi.height / size[1] + roi.y
            left = max(roi.x, math.floor(points[:, 0].min()))
            top = max(roi.y, math.floor(points[:, 1].min()))
            right = min(roi.x + roi.width, math.ceil(points[:, 0].max()))
            bottom = min(roi.y + roi.height, math.ceil(points[:, 1].max()))
            box = (left, top, right - left, bottom - top)
            if right <= left or bottom <= top or any(overlaps(box, item) for item in excluded):
                continue
            text_count += 1
            if not isinstance(text, str) or len(text) > 64:
                continue
            if normalized_name(text) == normalized_name(identity.text):
                matches.append(SceneNameCandidate(text=text, confidence=score, bbox=box))
        if len(matches) > 32:
            return result(reason="scene_candidate_limit", text_count=text_count)
        values = {"candidates": tuple(matches), "text_count": text_count}
        if not matches:
            return result(status="not_found", reason="no_matching_name", **values)
        if len(matches) > 1:
            return result(status="ambiguous", reason="multiple_matching_names", **values)
        if matches[0].confidence < profile.scene_name_min_confidence:
            return result(reason="low_confidence", **values)
        return result(status="found", name_bbox=matches[0].bbox, **values)
    except Exception:
        return result(reason="ocr_failed")
