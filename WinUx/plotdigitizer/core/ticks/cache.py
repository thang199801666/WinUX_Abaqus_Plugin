"""Lifecycle controls for tick-detector caches.

Font/template caches are deliberately retained across images because they are
small reusable assets.  Pixel-derived OCR caches are cleared when a Digitizer
engine switches images so old chart rasters cannot accumulate for the lifetime
of the application.
"""
from __future__ import annotations

from .pixels import _cached_classify_digit, _cached_components
from .source_ocr import (
    _cached_blurred_source_word,
    _cached_rotated_source_word,
    _cached_small_source_word,
    _cached_upscaled_source_word,
)
from .recognition import (
    _cached_fast_independent_word,
    _cached_independent_word,
    _cached_probe_word,
    _cached_word_candidates,
    _independent_digit_scores,
)

_IMAGE_CACHES = (
    _cached_components,
    _cached_classify_digit,
    _cached_upscaled_source_word,
    _cached_blurred_source_word,
    _cached_small_source_word,
    _cached_rotated_source_word,
    _independent_digit_scores,
    _cached_word_candidates,
    _cached_probe_word,
    _cached_fast_independent_word,
    _cached_independent_word,
)


def clear_image_caches():
    """Drop cached raster/OCR work tied to previously opened chart pixels."""
    for function in _IMAGE_CACHES:
        function.cache_clear()


def image_cache_info():
    """Return lightweight diagnostics for benchmarks/tests without exposing data."""
    return {function.__name__: function.cache_info() for function in _IMAGE_CACHES}
