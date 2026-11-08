"""Pure display-orientation composition for one-to-one listening photos.

The stored original is never rewritten.  ``orientation`` is the EXIF code read
when the original was imported (1–8, including mirrored combinations).
``rotation_quarters`` is the teacher's additional clockwise quarter-turn count
(0–3) and is applied *after* the EXIF transpose.  Preview CSS applies the same
quarter turns on top of the browser's EXIF display; Word and AI use this helper
so their working image matches the preview.
"""

from __future__ import annotations

from PIL import Image

EXIF_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}

# PIL's ROTATE_270 is 270° counter-clockwise, i.e. 90° clockwise.
ROTATION_TRANSPOSE = {
    0: None,
    1: Image.Transpose.ROTATE_270,
    2: Image.Transpose.ROTATE_180,
    3: Image.Transpose.ROTATE_90,
}


def normalize_rotation_quarters(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in (0, 1, 2, 3)
    ):
        raise ValueError("rotation_quarters 必须是 0～3 的整数")
    return value


def normalize_exif_orientation(value: object) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 8
    ):
        raise ValueError("orientation 必须是 1～8 或空值")
    return value


def apply_display_orientation(
    image: Image.Image,
    *,
    orientation: object,
    rotation_quarters: object,
) -> Image.Image:
    """Apply EXIF transpose first, then the teacher's clockwise quarters."""
    exif = normalize_exif_orientation(orientation)
    quarters = normalize_rotation_quarters(rotation_quarters)
    working = image
    if exif not in (None, 1):
        operation = EXIF_TRANSPOSE.get(exif)
        if operation is None:  # pragma: no cover - normalize already refuses
            raise ValueError("orientation 不受支持")
        working = working.transpose(operation)
    operation = ROTATION_TRANSPOSE[quarters]
    if operation is not None:
        working = working.transpose(operation)
    return working


__all__ = [
    "EXIF_TRANSPOSE",
    "ROTATION_TRANSPOSE",
    "normalize_rotation_quarters",
    "normalize_exif_orientation",
    "apply_display_orientation",
]
