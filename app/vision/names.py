"""Local name OCR; called only by the engine's single background analysis job."""

import math
import time

import numpy as np
from PIL import Image, ImageOps

from app.vision.models import NameReading, Rect, VisionProfile


class PlayerNameReader:
    def __init__(self) -> None:
        self._engine = None
        self._initialization_error: str | None = None

    def _create_engine(self):
        # This pinned distribution includes its default ONNX models.
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR(
            det_limit_type="max", det_limit_side_len=1536,
            intra_op_num_threads=2, inter_op_num_threads=1,
        )

    def read(self, bgr: np.ndarray, profile: VisionProfile) -> NameReading:
        return self.read_region(
            bgr, profile, profile.player_name, profile.player_name_min_confidence,
        )

    def ensure_engine(self) -> str | None:
        if self._initialization_error:
            return self._initialization_error
        if self._engine is None:
            try:
                self._engine = self._create_engine()
            except ImportError:
                self._initialization_error = "ocr_dependency_missing"
            except Exception:
                self._initialization_error = "ocr_initialization_failed"
        return self._initialization_error

    def detect_text(self, pixels: np.ndarray):
        return self._engine(pixels, use_cls=False, text_score=0.0)

    def read_region(
        self, bgr: np.ndarray, profile: VisionProfile, roi: Rect | None, min_confidence: float,
    ) -> NameReading:
        start = time.monotonic()
        bbox = (roi.x, roi.y, roi.width, roi.height) if roi else None

        def result(**values) -> NameReading:
            return NameReading(
                bbox=bbox, processing_ms=round((time.monotonic() - start) * 1000, 3),
                **values,
            )

        def unknown(reason: str, **values) -> NameReading:
            return result(status="unknown", reason=reason, **values)

        if roi is None:
            return unknown("region_not_configured")
        height, width = bgr.shape[:2]
        if (width, height) != profile.reference_size:
            return unknown("reference_size_mismatch")
        if roi.x + roi.width > width or roi.y + roi.height > height:
            return unknown("region_out_of_bounds")
        if roi.width * roi.height > 1_000_000:
            return unknown("ocr_region_too_large")
        error = self.ensure_engine()
        if error:
            return unknown(error)

        try:
            # White game text on dark UI becomes dark text on a light background.
            crop = bgr[roi.y:roi.y + roi.height, roi.x:roi.x + roi.width]
            image = ImageOps.invert(Image.fromarray(crop[:, :, ::-1]).convert("L"))
            scale = min(3.0, 2048 / roi.width, 256 / roi.height)
            size = (max(2, round(roi.width * scale)), max(2, round(roi.height * scale)))
            image = image.resize(size, Image.Resampling.LANCZOS)
            image = ImageOps.expand(image, border=8, fill=255).convert("RGB")
            pixels = np.array(image)[:, :, ::-1].copy()
            rows, _ = self.detect_text(pixels)
            candidates = []
            for row in rows or []:
                raw = str(row[1]).strip()
                score = float(row[2])
                if not math.isfinite(score) or not 0 <= score <= 1:
                    return unknown("ocr_invalid_output")
                if raw:
                    candidates.append((raw, score))
            if not candidates:
                return unknown("no_text")
            if len(candidates) != 1:
                return unknown("multiple_text_regions")
            raw, score = candidates[0]
            if len(raw) > 64:
                return unknown("ocr_invalid_output")
            if score < min_confidence:
                return unknown("low_confidence", raw_text=raw, confidence=score)
            return result(status="known", text=raw, raw_text=raw, confidence=score)
        except Exception:
            # Do not return dependency exceptions, paths or recognized text in logs.
            return unknown("ocr_failed")
