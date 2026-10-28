"""Single-frame dialogue inspection. Suggestions never authorize or execute input."""

import math
import re
import time
import unicodedata

import numpy as np
from PIL import Image

from app.vision.models import Box, DialogueOption, DialogueReading, DialogueText, VisionProfile
from app.vision.names import PlayerNameReader

MIN_CONFIDENCE = 0.8


def normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def find_panels(bgr: np.ndarray) -> tuple[Box, ...]:
    """Locate large light rectangular panel interiors; do not use fixture coordinates."""
    import cv2

    height, width = bgr.shape[:2]
    if width < 320 or height < 200:
        return ()
    scale = min(1.0, 1600 / width, 1000 / height)
    reduced = cv2.resize(bgr, (round(width * scale), round(height * scale)))
    low = reduced.min(axis=2)
    spread = reduced.max(axis=2).astype(np.int16) - low
    light = ((low >= 165) & (spread <= 55)).astype(np.uint8)
    rh, rw = light.shape

    def plausible(x, y, w, h):
        fraction = w * h / (rw * rh)
        return (w >= rw * 0.28 and 1.35 <= w / h <= 4.5
                and 0.025 <= fraction <= 0.4 and y >= rh * 0.12 and y + h <= rh * 0.9)

    # A dark divider/portrait must not have to join the white text surface.
    # RETR_LIST retains rectangular borders nested inside unrelated background edges.
    edges = cv2.Canny(cv2.cvtColor(reduced, cv2.COLOR_BGR2GRAY), 40, 140)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    framed = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:512]:
        x, y, w, h = cv2.boundingRect(contour)
        if not plausible(x, y, w, h) or cv2.contourArea(contour) / (w * h) < 0.85:
            continue
        polygon = cv2.approxPolyDP(contour, 0.015 * cv2.arcLength(contour, True), True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        tolerance = max(3, round(min(w, h) * 0.04))
        corners = polygon[:, 0, :]
        if any(min(abs(a - x), abs(a - (x + w - 1))) > tolerance
               or min(abs(b - y), abs(b - (y + h - 1))) > tolerance for a, b in corners):
            continue
        body = light[y + round(h * 0.1):y + round(h * 0.78),
                     x + round(w * 0.3):x + round(w * 0.95)]
        if not body.size or float(body.mean()) < 0.7:
            continue
        framed.append((x, y, w, h))

    def source_box(box):
        x, y, w, h = box
        left, top = math.floor(x / scale), math.floor(y / scale)
        right = min(width, math.ceil((x + w) / scale))
        bottom = min(height, math.ceil((y + h) / scale))
        return (left, top, right - left, bottom - top)

    def unique_boxes(boxes):
        kept = []
        for box in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
            x, y, w, h = box
            duplicate = False
            for a, b, c, d in kept:
                intersection = max(0, min(x + w, a + c) - max(x, a)) * max(
                    0, min(y + h, b + d) - max(y, b),
                )
                # Collapse nested frame strokes; distinct panels stay ambiguous.
                if intersection / (w * h) >= 0.95:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(box)
            if len(kept) >= 8:
                break
        return tuple(kept)

    if framed:
        # Border candidates already include the button bar: do not expand a footer again.
        return unique_boxes([source_box(box) for box in framed])

    mask = cv2.morphologyEx(light * 255, cv2.MORPH_CLOSE, np.ones((9, 9), dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not plausible(x, y, w, h):
            continue
        if cv2.contourArea(contour) / (w * h) < 0.85:
            continue
        # The light interior excludes the narrow frame and colored bottom button bar.
        margin = max(3, round(w * 0.018))
        footer = round(w * 0.08)
        left, top = max(0, x - margin), max(0, y - margin)
        right, bottom = min(rw, x + w + margin), min(rh, y + h + footer)
        box = (math.floor(left / scale), math.floor(top / scale),
               math.ceil((right - left) / scale), math.ceil((bottom - top) / scale))
        box = (box[0], box[1], min(box[2], width - box[0]), min(box[3], height - box[1]))
        candidates.append(box)
    return unique_boxes(candidates)


def extract_dialogue(panel: Box, texts: tuple[DialogueText, ...]) -> DialogueReading:
    """Read shared panel geometry and visible text without task-specific rules."""
    x, y, w, h = panel
    npc_rows, body_rows, options = [], [], []
    inside = []
    for row in texts:
        a, b, c, d = row.bbox
        if not (x <= a < a + c <= x + w and y <= b < b + d <= y + h):
            continue
        inside.append(row)
        norm = normalize(row.text)
        if a + c <= x + w * 0.29 and y + h * 0.4 <= b <= y + h * 0.82:
            if row.confidence >= MIN_CONFIDENCE and re.fullmatch(r"[\w\u4e00-\u9fff]{2,32}", norm):
                npc_rows.append(row)
            continue
        button = norm.strip("<>›▶◀→←")
        if button in ("下项", "是", "不是", "结束对话") and b >= y + h * 0.55:
            options.append(DialogueOption(**row.model_dump(), kind="button"))
            continue
        if a >= x + w * 0.27 and b + d <= y + h * 0.86:
            body_rows.append(row)
            match = re.fullmatch(r"[>›▶·•◆◇\-]*(.+?)([0-9]{1,4})个", norm)
            if match:
                options.append(DialogueOption(
                    **row.model_dump(), kind="material", count=int(match[2]),
                ))
    body_rows.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    npc = npc_rows[0] if len(npc_rows) == 1 else None
    return DialogueReading(
        status="ambiguous" if len(npc_rows) > 1 else "found", panel_bbox=panel,
        text="\n".join(r.text for r in body_rows), texts=tuple(inside),
        body_texts=tuple(body_rows), options=tuple(options),
        npc_name=normalize(npc.text) if npc else None,
        npc_confidence=npc.confidence if npc else None, npc_bbox=npc.bbox if npc else None,
        reason="npc_ambiguous" if len(npc_rows) > 1 else None,
    )


def read_dialogue(
    reader: PlayerNameReader, bgr: np.ndarray, profile: VisionProfile,
) -> DialogueReading:
    start = time.monotonic()

    def finish(reading: DialogueReading) -> DialogueReading:
        return reading.model_copy(update={
            "processing_ms": round((time.monotonic() - start) * 1000, 3),
        })

    height, width = bgr.shape[:2]
    if (width, height) != profile.reference_size:
        return finish(DialogueReading(reason="reference_size_mismatch"))
    try:
        panels = find_panels(bgr)
    except ImportError:
        return finish(DialogueReading(reason="dialogue_dependency_missing"))
    except Exception:
        return finish(DialogueReading(reason="panel_detection_failed"))
    if not panels:
        return finish(DialogueReading(status="not_found", reason="no_dialogue_panel"))
    if len(panels) > 1:
        return finish(DialogueReading(
            status="ambiguous", candidates=panels, reason="multiple_dialogue_panels",
        ))
    panel = panels[0]
    error = reader.ensure_engine()
    if error:
        return finish(DialogueReading(panel_bbox=panel, reason=error))
    x, y, w, h = panel
    scale = min(2.0, 1536 / w, 1024 / h)
    size = (max(2, round(w * scale)), max(2, round(h * scale)))
    try:
        crop = Image.fromarray(bgr[y:y + h, x:x + w, ::-1])
        pixels = np.array(crop.resize(size, Image.Resampling.LANCZOS))[:, :, ::-1].copy()
        rows, _ = reader.detect_text(pixels)
        rows = [] if rows is None else rows
        if len(rows) > 64:
            return finish(DialogueReading(panel_bbox=panel, reason="dialogue_text_limit"))
        texts = []
        for quad, text, confidence, *_ in rows:
            points = np.asarray(quad, dtype=float)
            score = float(confidence)
            if (points.shape != (4, 2) or not np.isfinite(points).all()
                    or not math.isfinite(score) or not 0 <= score <= 1
                    or not isinstance(text, str) or len(text) > 256):
                return finish(DialogueReading(panel_bbox=panel, reason="ocr_invalid_output"))
            left = max(x, x + math.floor(points[:, 0].min() * w / size[0]))
            top = max(y, y + math.floor(points[:, 1].min() * h / size[1]))
            right = min(x + w, x + math.ceil(points[:, 0].max() * w / size[0]))
            bottom = min(y + h, y + math.ceil(points[:, 1].max() * h / size[1]))
            if right > left and bottom > top and text.strip():
                texts.append(DialogueText(
                    text=text.strip(), confidence=score, bbox=(left, top, right-left, bottom-top),
                ))
        return finish(extract_dialogue(panel, tuple(texts)))
    except Exception:
        return finish(DialogueReading(panel_bbox=panel, reason="ocr_failed"))
