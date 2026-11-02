from __future__ import annotations

"""Backward-compatible facade for Plot Digitizer tick detection.

Implementation is split under :mod:`.ticks` by responsibility.  The facade keeps
the historical public/private symbol surface because existing tests and plugins
monkey-patch several detector helpers directly.
"""

import sys
import types

from .models import AxisScale
from .region_detection import align_region_to_axes
from .ticks.shared import (
    _BINARY_TO_255_LUT, _GUIDE_BRIGHT_LUT, _GUIDE_CHROMA_LUT,
    _LINE_STRENGTH_LUT, _NEUTRAL_CHROMA_LUT, _NUMERIC_CHARS,
    _SOURCE_OCR_CANCEL,
)
from .ticks.types import AxisTickDetection, TickCalibrationDetection, TickReading
from .ticks import axis_math as _axis_math_module
from .ticks import pipeline as _pipeline_module
from .ticks import pixels as _pixels_module
from .ticks import recognition as _recognition_module
from .ticks import sequences as _sequences_module
from .ticks import source_ocr as _source_ocr_module

from .ticks.pixels import (
    _threshold_lut, _point_lut, _column_sums, _font_candidates, _template_fonts,
    _template_font_indexes, _otsu_threshold, _flat_pixels, _binary_mask, _bbox, _crop_mask,
    _projection_bands, _components, _cached_components, _components_uncached, _hole_centers,
    _mask_image, _shift_mask_image, _dilate_binary_square, _normalized_mask, _glyph_templates,
    _glyph_score, _normalized_glyph_score, _split_wide_component, _numeric_glyph_boxes,
    _classify_digit, _cached_classify_digit, _BINARY_BYTE_LUT
)

from .ticks.axis_math import (
    _median_spacing, _transform_value, _inverse_value, _nice_step, _nice_log_step, _linear_fit,
    _robust_axis_values
)

from .ticks.recognition import (
    _numeric_text_hypotheses, _ocr_numeric, _faint_label_mask, _x_label_masks,
    _x_label_masks_native, _y_label_masks, _y_label_masks_native, _rgb_luminance,
    _plot_background_luminance, _axis_line_score, _remove_long_rules,
    _axis_edge_tick_candidates, _major_axis_edge_subset, _coherent_major_mark_subset,
    _merge_axis_mark_sources, _line_peak_candidates, _regular_grid_lattice,
    _nearest_axis_text_mask, _rotate_mask, _expanded_slot_label, _word_alignment_score,
    _principal_word_angle, _normalise_word_angle, _label_deskew_angle, _transformed_label_plan,
    _slot_oriented_masks, _slot_numeric_candidates, _normalize_word_mask, _template_text_bbox,
    _template_prefix_advance, _binary_template_glyph, _composed_numeric_word,
    _render_binary_word, _word_templates, _quick_word_templates, _normalized_quick_word_score,
    _normalized_word_template_score, _gray_difference, _word_template_score,
    _same_numeric_value, _consensus_numeric_reading, _read_scientific_glyph_word,
    _read_scientific_word, _scientific_reading_beats, _independent_digit_scores,
    _tight_glyph_templates, _independent_word_candidates, _cached_word_candidates,
    _small_word_templates, _sized_template_font, _small_word_score, _read_independent_word,
    _read_probe_word, _cached_probe_word, _read_fast_independent_word,
    _cached_fast_independent_word, _cached_independent_word, _remove_plot_scan_rules,
    _x_tick_label_band, _isolated_word_group, _physical_tick_words, _word_contrast_masks,
    _scale_model_error, _logarithmic_scale_kind, _observed_axis_scale, _WORD_TEMPLATE_LUT
)

from .ticks.source_ocr import (
    _gray_contrast_lut, _autocontrast_gray, _normalized_gray_word, _rotated_gray_templates,
    _rotated_gray_score, _compressed_gray_score, _small_source_font_rasters,
    _small_source_rasters, _phase_raster_score, _phase_raster_fit, _blurred_source_fit,
    _read_small_source_word, _cached_upscaled_source_word, _cached_blurred_source_word,
    _read_blurred_source_word, _deoccluded_colored_word_mask, _read_deoccluded_colored_word,
    _read_upscaled_source_word, _cached_small_source_word, _read_rotated_source_word,
    _cached_rotated_source_word, _check_tick_cancelled
)

from .ticks.sequences import (
    _format_tick_value, _format_tick_value_variants, _normalized_value_template_score,
    _value_template_score, _nice_step_candidates, _zero_anchored_template_detection,
    _sequence_image_error, _refine_tick_positions, _build_axis_detection, _slot_probe_axis,
    _verified_y_detection, _complete_lattice_ticks, _fast_label_axis, _detect_axis_native,
    _recover_transformed_slots, _detect_transformed_axis, _complete_regular_mark_positions,
    _colored_guide_occlusion_score, _infer_occluded_linear_outliers,
    _recover_occluded_axis_readings, _axis_completion_supported, _linear_completion_supported,
    _infer_template_supported_linear_outliers, _infer_template_supported_log_outliers,
    _repair_ambiguous_linear_readings, _label_driven_words,
    _augment_regular_positions_from_labels, _upright_sequence_words, _iso_date_part_candidates,
    _iso_date_word_candidates, _iso_datetime_sequence_detection, _year_sequence_detection,
    _candidate_supported_linear_sequence, _log_decade_template_detection
)

from .ticks.pipeline import (
    _detect_axis, _detect_axis_impl, _retry_small_y_labels, _small_y_retry_is_worthwhile,
    detect_calibration_ticks, estimate_axis_value_at
)

# Preserve the historical pickle/repr module path for public result types.
TickReading.__module__ = __name__
AxisTickDetection.__module__ = __name__
TickCalibrationDetection.__module__ = __name__


_TICK_IMPLEMENTATION_MODULES = (
    _pixels_module, _axis_math_module, _recognition_module,
    _source_ocr_module, _sequences_module, _pipeline_module,
)


class _TickDetectionFacadeModule(types.ModuleType):
    """Keep historical monkey-patch points synchronized with split modules.

    ``patch.object(tick_detection, name, ...)`` was part of the detector's test
    and plugin surface long before the implementation was modularized.  When a
    facade attribute is replaced, mirror that binding into every subsystem that
    imported/defines the same symbol.  Restoring the patch mirrors the original
    binding back as well.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        modules = self.__dict__.get('_TICK_IMPLEMENTATION_MODULES', ())
        for module in modules:
            if name in module.__dict__:
                module.__dict__[name] = value


_module = sys.modules[__name__]
if not isinstance(_module, _TickDetectionFacadeModule):
    _module.__class__ = _TickDetectionFacadeModule

del _module
