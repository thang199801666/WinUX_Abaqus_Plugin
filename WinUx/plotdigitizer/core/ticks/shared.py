from __future__ import annotations

from contextvars import ContextVar

# Shared immutable/runtime primitives used by multiple detector subsystems.
_NUMERIC_CHARS = "0123456789"
_SOURCE_OCR_CANCEL = ContextVar("digitizer_source_ocr_cancel", default=None)
_BINARY_TO_255_LUT = bytes(0 if value == 0 else 255 for value in range(256))
_NEUTRAL_CHROMA_LUT = tuple(255 if value <= 24 else 0 for value in range(256))
_GUIDE_CHROMA_LUT = bytes(255 if value >= 12 else 0 for value in range(256))
_GUIDE_BRIGHT_LUT = tuple(255 if value >= 90 else 0 for value in range(256))
_LINE_STRENGTH_LUT = tuple(
    0 if value < 4 else min(255, int(round(255 * min(1.0, value / 26.0))))
    for value in range(256)
)
