import numpy as np

from app.vision.models import BarReading, Rect, VisionProfile


def read_bar(bgr: np.ndarray, roi: Rect | None, kind: str, profile: VisionProfile) -> BarReading:
    bbox = (roi.x, roi.y, roi.width, roi.height) if roi else None

    def unknown(reason: str) -> BarReading:
        return BarReading(status="unknown", bbox=bbox, reason=reason)

    if roi is None:
        return unknown("region_not_configured")
    height, width = bgr.shape[:2]
    if (width, height) != profile.reference_size:
        return unknown("reference_size_mismatch")
    if roi.x + roi.width > width or roi.y + roi.height > height:
        return unknown("region_out_of_bounds")
    pixels = bgr[roi.y:roi.y + roi.height, roi.x:roi.x + roi.width].astype(np.int16)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    difference = profile.min_color_difference
    if kind == "hp":
        mask = (red >= profile.min_channel) & (red - np.maximum(blue, green) >= difference)
    else:
        mask = (
            (blue >= profile.min_channel)
            & (blue - red >= difference)
            & (blue >= green * 0.8)
        )
    columns = mask.mean(axis=0) >= profile.min_column_fraction
    positions = np.flatnonzero(columns)
    # No foreground cannot distinguish an empty bar from a wrong/hidden region.
    if positions.size == 0:
        return unknown("no_fill_color")
    if positions[0] > max(2, int(roi.width * 0.02)):
        return unknown("fill_not_left_aligned")
    end = int(positions[-1]) + 1
    continuity = float(columns[:end].mean())
    if continuity < profile.min_continuity:
        return unknown("fill_not_contiguous")
    return BarReading(
        status="known", bbox=bbox, ratio=round(end / roi.width, 4),
        quality=round(continuity, 4),
    )
