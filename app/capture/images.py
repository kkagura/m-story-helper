import io
import time
from dataclasses import dataclass
from uuid import uuid4

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.media.frames import ReceivedFrame
from app.vision.models import VisionFailure


@dataclass(frozen=True)
class Screenshot:
    frame: ReceivedFrame
    preview_png: bytes


def decode_screenshot(payload: bytes, max_pixels: int) -> Screenshot:
    try:
        with Image.open(io.BytesIO(payload), formats=["PNG", "JPEG"]) as image:
            if image.width * image.height > max_pixels:
                raise VisionFailure(413, "图片尺寸超过配置上限。")
            if getattr(image, "n_frames", 1) != 1:
                raise VisionFailure(415, "仅支持单帧 PNG/JPEG 图片。")
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            # Preview and recognition share the same normalized, oriented image.
            bgr = np.asarray(rgb)[:, :, ::-1].copy()
            bgr.flags.writeable = False
            output = io.BytesIO()
            rgb.save(output, format="PNG")
            stamp = time.monotonic()
            frame = ReceivedFrame(
                session_id=str(uuid4()), frame_id=1, size_version=1,
                received_at_monotonic=stamp, converted_at_monotonic=stamp,
                media_timestamp_ms=None, width=rgb.width, height=rgb.height,
                bgr=bgr, source="screenshot",
            )
            return Screenshot(frame=frame, preview_png=output.getvalue())
    except VisionFailure:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise VisionFailure(415, "无法解码图片，请选择完整的 PNG/JPEG 截图。") from exc
