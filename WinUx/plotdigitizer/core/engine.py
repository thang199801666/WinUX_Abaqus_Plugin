from __future__ import annotations

import csv
import json
import copy
import math
import os
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable
from PIL import Image

from .calibration import Calibration
from .models import (
    AxisAnchor, AxisScale, DataPoint, Dataset, ExtractionSettings, SmartDetectionResult,
    DATASET_MARKER_STYLES, default_marker_style, normalize_marker_style,
)
from .extraction import sample_color, detect_plot_area, detect_curve_color, extract_curve
from .tick_detection import detect_calibration_ticks
from .history import recorded
from .reduction import (
    simplify_indices, normalize_breaks, remap_breaks, project_onto_polyline, resample_polyline,
    polyline_cumulative_lengths, select_polyline_indices,
)
from .project_binary import write_pdg, read_pdg


class DigitizerEngine:
    """Headless digitizer engine. No DearPyGui import and no UI ownership."""

    PROJECT_VERSION = 3
    HISTORY_LIMIT = 40

    def __init__(self) -> None:
        self.image: Image.Image | None = None
        self.image_path: str | None = None
        self.calibration = Calibration()
        self.plot_rect: tuple[int, int, int, int] | None = None
        self.datasets: list[Dataset] = [Dataset(marker_style=default_marker_style(0))]
        self.active_dataset_index = 0
        self._listeners: list[Callable[[str, "DigitizerEngine"], None]] = []
        self._undo_stack = []
        self._redo_stack = []
        self._edit_depth = 0
        self.revision = 0
        self.project_view_state = {}
        # Box seed values are not OCR-confirmed calibration.
        self.auto_tick_verified_axes = set()

    def _snapshot(self):
        return copy.deepcopy({"calibration": self.calibration.to_dict(), "plot_rect": self.plot_rect,
                              "datasets": [ds.to_dict() for ds in self.datasets],
                              "active": self.active_dataset_index,
                              "verified_axes": sorted(self.auto_tick_verified_axes)})

    def _restore(self, state):
        self.calibration = Calibration.from_dict(state["calibration"])
        self.auto_tick_verified_axes = set(state.get("verified_axes", {"x", "y"}))
        self.plot_rect = state["plot_rect"]
        self.datasets = [Dataset.from_dict(ds) for ds in copy.deepcopy(state["datasets"])]
        self._ensure_dataset_markers()
        self.active_dataset_index = state["active"]
        self.recompute_all_data()
        self._emit("state_restored")

    @property
    def can_undo(self):
        return bool(self._undo_stack)

    @property
    def can_redo(self):
        return bool(self._redo_stack)

    def undo(self):
        if not self.can_undo:
            return False
        label, state = self._undo_stack.pop()
        self._redo_stack.append((label, self._snapshot()))
        self.revision += 1
        self._restore(state)
        return True

    def redo(self):
        if not self.can_redo:
            return False
        label, state = self._redo_stack.pop()
        self._undo_stack.append((label, self._snapshot()))
        self.revision += 1
        self._restore(state)
        return True

    def merge_region_tick_history(self, region_revision):
        """Treat an untouched Smart Region plus its async OCR as one edit."""
        if (self.revision != region_revision + 1 or len(self._undo_stack) < 2
                or self._undo_stack[-1][0] != "Apply detected tick calibration"
                or self._undo_stack[-2][0] != "Set plot area and calibration anchors"):
            return False
        self._undo_stack.pop()  # Keep the snapshot from before the region gesture.
        self._emit("history_changed")
        return True

    def _next_marker_style(self, used_styles=None) -> str:
        used = [normalize_marker_style(style) for style in (used_styles or []) if style]
        for style in DATASET_MARKER_STYLES:
            if style not in used:
                return style
        return default_marker_style(len(used))

    def _ensure_dataset_markers(self) -> None:
        assigned = []
        for ds in self.datasets:
            style = normalize_marker_style(getattr(ds, "marker_style", None), default="")
            if not style or style in assigned:
                style = self._next_marker_style(assigned)
            ds.marker_style = style
            assigned.append(style)

    def _editable(self, dataset=None):
        ds = dataset if dataset is not None else self.active_dataset
        if ds.locked:
            raise ValueError("Unlock this dataset before editing its data.")
        return ds

    def _pixel(self, px, py):
        px, py = float(px), float(py)
        if not math.isfinite(px) or not math.isfinite(py):
            raise ValueError("Point coordinates must be finite.")
        if self.image is not None and not (0 <= px < self.image.width and 0 <= py < self.image.height):
            raise ValueError("Point must be inside the image.")
        return px, py

    @property
    def active_dataset(self) -> Dataset:
        return self.datasets[self.active_dataset_index]

    def subscribe(self, callback: Callable[[str, "DigitizerEngine"], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit(self, event: str) -> None:
        for cb in tuple(self._listeners):
            cb(event, self)

    @staticmethod
    def read_image(path: str):
        """Decode an image without mutating engine state.

        File decoding can be slow on large TIFF/PNG inputs and is safe to run
        on a worker. ``apply_image`` performs the small state mutation on the
        owning UI thread afterwards.
        """
        resolved = str(Path(path).resolve())
        with Image.open(resolved) as source:
            image = source.convert("RGB")
            image.load()
        return image, resolved

    def apply_image(self, image, path: str) -> None:
        if image is None:
            raise ValueError("Image data is required.")
        self.image = image
        self.image_path = str(Path(path).resolve())
        self.project_view_state = {}
        self.plot_rect = None
        self.calibration = Calibration(snap_to_axes=self.calibration.snap_to_axes)
        for ds in self.datasets:
            ds.extracted_pixels.clear(); ds.extracted_data.clear(); ds.manual_points.clear()
            ds.extracted_breaks = None
            ds.curve_rgb = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.revision += 1
        self._emit("image_changed")

    def clean_project(self):
        """Start an empty in-memory project; never delete saved files."""
        self.image = None
        self.image_path = None
        self.calibration = Calibration()
        self.plot_rect = None
        self.datasets = [Dataset(marker_style=default_marker_style(0))]
        self.active_dataset_index = 0
        self.auto_tick_verified_axes.clear()
        self.project_view_state = {}
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.revision += 1
        self._emit('image_changed')

    @recorded('Clear all markers')
    def clean_markers(self):
        """Clear all datasets and axis markers, preserving image and settings."""
        self.revision += 1  # Also discard workers when the canvas was already empty.
        self.calibration = Calibration(snap_to_axes=self.calibration.snap_to_axes)
        self.plot_rect = None
        self.auto_tick_verified_axes.clear()
        for dataset in self.datasets:
            dataset.manual_points.clear()
            dataset.extracted_pixels.clear()
            dataset.extracted_data.clear()
            dataset.extracted_breaks = None
            dataset.curve_rgb = None
        self._emit('state_restored')

    def load_image(self, path: str) -> None:
        image, resolved = self.read_image(path)
        self.apply_image(image, resolved)

    @recorded("Calibrate axis")
    def set_anchor(self, key: str, px: float, py: float, value: float) -> None:
        px, py = self._pixel(px, py)
        previous = getattr(self.calibration, key, None)
        self.calibration.set_anchor(key, px, py, value)
        if previous is None or previous.value != value:
            self.auto_tick_verified_axes.add(key[0])
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Apply axis calibration")
    def set_anchor_values(self, values):
        """Apply four edited tick values atomically, preserving anchor pixels."""
        keys = ("x1", "x2", "y1", "y2")
        if set(values) != set(keys) or any(getattr(self.calibration, key) is None for key in keys):
            raise ValueError("Pick all four axis anchors before applying calibration.")
        data = self.calibration.to_dict()
        for key in keys:
            data[key]["value"] = float(values[key])
        data["points_x"] = []
        data["points_y"] = []
        calibration = Calibration.from_dict(data)
        calibration.validate()
        self.calibration = calibration
        self.auto_tick_verified_axes = {"x", "y"}
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Prepare manual axis bounds")
    def prepare_manual_axis_bounds(self, axes):
        """Place missing endpoint handles on the Box without confirming values."""
        if self.plot_rect is None or any(axis not in ("x", "y") for axis in axes):
            raise ValueError("Select a plot area before entering axis bounds.")
        candidate = Calibration.from_dict(self.calibration.to_dict())
        left, top, right, bottom = self.plot_rect
        for axis in axes:
            first, second = getattr(candidate, axis + "1"), getattr(candidate, axis + "2")
            values = self._corner_anchor_values(first, second, getattr(candidate, "scale_" + axis))
            for suffix, px, py, value in (("1", left, bottom, values[0]),
                    ("2", right if axis == "x" else left, bottom if axis == "x" else top, values[1])):
                if getattr(candidate, axis + suffix) is None:
                    setattr(candidate, axis + suffix, AxisAnchor(float(px), float(py), value))
        candidate.box_rect = tuple(self.plot_rect)
        candidate.validate()
        self.calibration = candidate
        self._emit("calibration_changed")

    @recorded("Apply missing axis bounds")
    def set_axis_bounds(self, values):
        """Confirm complete endpoint pairs without discarding the other axis."""
        axes = {key[0] for key in values if key in ("x1", "x2", "y1", "y2")}
        expected = {axis + suffix for axis in axes for suffix in ("1", "2")}
        if not axes or set(values) != expected:
            raise ValueError("Enter both endpoint values for each missing axis.")
        data = self.calibration.to_dict()
        for key, value in values.items():
            if data[key] is None:
                raise ValueError("Pick the {} anchor first.".format(key.upper()))
            data[key]["value"] = float(value)
        for axis in axes:
            data["points_" + axis] = []
            data["mapping_" + axis] = "fit"
        candidate = Calibration.from_dict(data)
        candidate.validate()
        self.calibration = candidate
        self.auto_tick_verified_axes.update(axes)
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Edit calibration points")
    def set_calibration_points(self, axis, points):
        """Replace one axis atomically, keeping the other axis and Undo intact."""
        candidate = Calibration.from_dict(self.calibration.to_dict())
        checked = []
        for point in points:
            px, py = self._pixel(point.px, point.py)
            checked.append(AxisAnchor(px, py, float(point.value)))
        candidate.set_axis_points(axis, checked, sync_anchors=True)
        self.calibration = candidate
        if candidate.box_rect is not None:
            self.plot_rect = tuple(int(round(v)) for v in candidate.box_rect)
        if len(checked) >= 2:
            self.auto_tick_verified_axes.add(axis)
        else:
            self.auto_tick_verified_axes.discard(axis)
        self.recompute_all_data()
        self._emit("calibration_changed")

    def add_calibration_point(self, axis, px, py, value):
        points = self.calibration_points(axis)
        points.append(AxisAnchor(float(px), float(py), float(value)))
        self.set_calibration_points(axis, points)

    def calibration_points(self, axis):
        points = self.calibration.axis_points(axis)
        # Box seeds are placeholders, never measurements in the point editor.
        if not getattr(self.calibration, "points_" + axis) and axis not in self.auto_tick_verified_axes:
            return []
        return points

    def update_calibration_point(self, axis, index, *, value=None, px=None, py=None):
        points = self.calibration.axis_points(axis)
        if not 0 <= index < len(points):
            raise IndexError("Select a calibration point first.")
        old = points[index]
        points[index] = AxisAnchor(old.px if px is None else float(px),
                                   old.py if py is None else float(py),
                                   old.value if value is None else float(value))
        self.set_calibration_points(axis, points)

    def remove_calibration_point(self, axis, index):
        points = self.calibration.axis_points(axis)
        if not 0 <= index < len(points):
            raise IndexError("Select a calibration point first.")
        del points[index]
        self.set_calibration_points(axis, points)

    def move_anchor(self, key: str, px: float, py: float, *, finalize: bool = False) -> None:
        """Move an existing calibration anchor without rebuilding all data on every drag frame.

        Use ``finalize=False`` during pointer movement and ``finalize=True`` on release.
        This keeps DearPyGui interaction responsive while preserving a clean core API.
        """
        anchor = getattr(self.calibration, key, None)
        if anchor is None:
            raise ValueError(f"Calibration anchor {key!r} is not set.")
        self.calibration.set_anchor(key, px, py, anchor.value)
        if finalize:
            self.recompute_all_data()
            self._emit("calibration_changed")
        else:
            self._emit("calibration_preview_changed")

    @recorded("Clear axis anchor")
    def clear_anchor(self, key: str) -> None:
        self.calibration.clear_anchor(key)
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Reset calibration")
    def reset_calibration(self):
        self.calibration = Calibration(scale_x=self.calibration.scale_x, scale_y=self.calibration.scale_y,
                                       snap_to_axes=self.calibration.snap_to_axes)
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Change extraction settings")
    def set_settings(self, settings):
        from dataclasses import replace
        self._validate_settings(settings)
        self._editable().settings = replace(settings)
        self._emit("settings_changed")

    @staticmethod
    def _validate_settings(settings):
        values = (settings.tolerance, settings.continuity, settings.stride, settings.min_hits,
                  settings.smoothing, settings.max_gap_columns, settings.minimum_saturation)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("Extraction settings must contain integer values.")
        if (settings.tolerance < 1 or settings.continuity < 1 or settings.stride < 1 or
                settings.min_hits < 1 or settings.smoothing < 0 or settings.max_gap_columns < 0 or
                not 0 <= settings.minimum_saturation <= 255):
            raise ValueError("Invalid extraction settings.")

    @recorded("Change axis scale")
    def set_axis_scale(self, x: AxisScale | str | None = None, y: AxisScale | str | None = None) -> None:
        from dataclasses import replace
        candidate = replace(
            self.calibration,
            scale_x=AxisScale(x) if x is not None else self.calibration.scale_x,
            scale_y=AxisScale(y) if y is not None else self.calibration.scale_y,
        )
        candidate.validate()
        self.calibration = candidate
        self.recompute_all_data()
        self._emit("calibration_changed")

    def calibration_ready(self) -> bool:
        if any(
                axis not in self.auto_tick_verified_axes and
                len(getattr(self.calibration, "points_" + axis)) < 2 for axis in ("x", "y")):
            return False  # Safe Box seeds are not confirmed axis values.
        return self.calibration.ready()

    @recorded('Change axis snapping')
    def set_axis_snapping(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Snap to Axes must be a boolean.')
        self.calibration.snap_to_axes = enabled
        # This changes the policy for subsequent jobs, never moves an existing
        # region or changes measured tick coordinates retroactively.
        self._emit('calibration_changed')

    def pixel_to_data(self, px: float, py: float):
        return self.calibration.pixel_to_data(px, py)

    def plot_roi(self):
        if self.image is None:
            return (0, 0, 0, 0)
        if self.plot_rect:
            return self.plot_rect
        c = self.calibration
        if c.ready():
            assert c.x1 and c.x2 and c.y1 and c.y2
            left, right = int(min(c.x1.px, c.x2.px)), int(max(c.x1.px, c.x2.px))
            top, bottom = int(min(c.y1.py, c.y2.py)), int(max(c.y1.py, c.y2.py))
            return left, top, right, bottom
        return 0, 0, self.image.width - 1, self.image.height - 1

    @recorded("Choose curve color")
    def set_curve_color(self, rgb):
        ds = self._editable()
        if len(rgb) != 3 or any(not math.isfinite(float(c)) or not 0 <= float(c) <= 255 for c in rgb):
            raise ValueError("Curve color must contain three RGB values in 0..255.")
        ds.curve_rgb = tuple(round(float(c)) for c in rgb)
        self._emit("dataset_changed")
        return ds.curve_rgb

    def sample_curve_color(self, px: float, py: float, radius: int = 2):
        if self.image is None:
            raise RuntimeError("No image loaded.")
        px, py = self._pixel(px, py)
        return self.set_curve_color(sample_color(self.image, round(px), round(py), radius))

    @recorded("Set plot area")
    def set_plot_rect(self, rect):
        if self.image is None:
            raise ValueError("Open an image first.")
        if rect is None:
            self.plot_rect = None
        else:
            x0, y0, x1, y1 = map(float, rect)
            if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
                raise ValueError("Plot area coordinates must be finite.")
            left, right = sorted((max(0, min(self.image.width - 1, round(x0))),
                                  max(0, min(self.image.width - 1, round(x1)))))
            top, bottom = sorted((max(0, min(self.image.height - 1, round(y0))),
                                  max(0, min(self.image.height - 1, round(y1)))))
            if right - left < 2 or bottom - top < 2:
                raise ValueError("Plot area must be at least 3 by 3 pixels.")
            self.plot_rect = (left, top, right, bottom)
        self._emit("roi_changed")

    @staticmethod
    def _corner_anchor_values(first, second, scale):
        """Return a valid value pair for box-assigned calibration anchors.

        Existing axis values are preserved whenever possible. Missing values
        receive stable linear (0, 1) or logarithmic (1, 10) seeds so drawing a
        plot-area box can immediately create usable X1/X2/Y1/Y2 anchors.
        """
        logarithmic = scale in (AxisScale.LOG10, AxisScale.LN)
        default_first, default_second = ((1.0, 10.0) if logarithmic else (0.0, 1.0))
        first_value = first.value if first is not None else default_first
        second_value = second.value if second is not None else default_second
        if logarithmic:
            if first_value <= 0:
                first_value = default_first
            if second_value <= 0:
                second_value = default_second
        if first_value == second_value:
            if first is None:
                first_value = second_value / 10.0 if logarithmic else second_value - 1.0
            else:
                second_value = first_value * 10.0 if logarithmic else first_value + 1.0
        return float(first_value), float(second_value)

    @recorded("Set plot area and calibration anchors")
    def set_plot_rect_with_corner_anchors(self, rect, *, detect_ticks=True):
        """Set a chart box and its four corner anchors.

        ``detect_ticks=False`` is the non-blocking UI path: the Box and safe
        seed values are committed immediately, while numeric tick detection can
        run on a worker and later be applied with
        :meth:`apply_tick_calibration_detection`.  Headless callers retain the
        previous synchronous behavior by leaving ``detect_ticks`` enabled.
        """
        self.set_plot_rect(rect)
        self.auto_tick_verified_axes = set()
        if self.plot_rect is None:
            raise ValueError("Plot area is required to assign calibration anchors.")
        left, top, right, bottom = self.plot_rect
        old = self.calibration
        x1_value, x2_value = self._corner_anchor_values(old.x1, old.x2, old.scale_x)
        y1_value, y2_value = self._corner_anchor_values(old.y1, old.y2, old.scale_y)
        detection = None
        if detect_ticks:
            detection = detect_calibration_ticks(
                self.image, self.plot_rect, old.scale_x, old.scale_y)
            if detection.x.ready:
                self.auto_tick_verified_axes.add("x")
            if detection.y.ready:
                self.auto_tick_verified_axes.add("y")

        candidate = Calibration(scale_x=old.scale_x, scale_y=old.scale_y,
                                snap_to_axes=old.snap_to_axes)
        for key, px, py, value in (
                ("x1", left, bottom, x1_value),
                ("x2", right, bottom, x2_value),
                ("y1", left, bottom, y1_value),
                ("y2", left, top, y2_value)):
            candidate.set_anchor(key, px, py, value)
        candidate.box_rect = tuple(self.plot_rect)
        self._retain_detected_axis_points(candidate, detection)
        self.calibration = candidate
        self.recompute_all_data()
        self._emit("calibration_changed")
        return detection

    @recorded("Apply detected tick calibration")
    def apply_tick_calibration_detection(self, detection, *, expected_rect=None):
        """Apply a completed background tick detection to the current Box.

        Returns ``False`` when the result is unusable or belongs to an older
        Box.  This method performs no OCR and therefore remains cheap on the UI
        thread.
        """
        if detection is None or self.plot_rect is None:
            return False
        if expected_rect is not None:
            expected = tuple(int(round(value)) for value in expected_rect)
            if tuple(self.plot_rect) != expected:
                return False
        aligned = getattr(detection, 'aligned_rect', None) if self.calibration.snap_to_axes else None
        if not (detection.x.ready or detection.y.ready) and (aligned is None or tuple(aligned) == tuple(self.plot_rect)):
            return False

        selected_rect = tuple(self.plot_rect)
        region = tuple(aligned) if aligned is not None else selected_rect
        if (len(region) != 4 or not all(math.isfinite(v) for v in region) or
                region[2] - region[0] < 2 or region[3] - region[1] < 2):
            return False
        if self.image is not None and not (0 <= region[0] < region[2] < self.image.width and
                                           0 <= region[1] < region[3] < self.image.height):
            return False
        left, top, right, bottom = region
        old = self.calibration
        x1_value, x2_value = self._corner_anchor_values(old.x1, old.x2, old.scale_x)
        y1_value, y2_value = self._corner_anchor_values(old.y1, old.y2, old.scale_y)
        if detection.x.ready:
            self.auto_tick_verified_axes.add("x")
        if detection.y.ready:
            self.auto_tick_verified_axes.add("y")

        candidate = Calibration(scale_x=old.scale_x, scale_y=old.scale_y,
                                snap_to_axes=old.snap_to_axes)
        for key, px, py, value in (
                ("x1", left, bottom, x1_value),
                ("x2", right, bottom, x2_value),
                ("y1", left, bottom, y1_value),
                ("y2", left, top, y2_value)):
            candidate.set_anchor(key, px, py, value)
        candidate.box_rect = region
        for reading in (detection.x, detection.y):
            if not reading.ready and reading.axis in self.auto_tick_verified_axes:
                axis = reading.axis
                setattr(candidate, "points_" + axis, copy.deepcopy(getattr(old, "points_" + axis)))
                setattr(candidate, "mapping_" + axis, getattr(old, "mapping_" + axis))
        self._retain_detected_axis_points(candidate, detection)
        self.calibration = candidate
        self.recompute_all_data()
        if tuple(self.plot_rect) != selected_rect:
            self._emit('roi_changed')
        self._emit("calibration_changed")
        return True

    def _retain_detected_axis_points(self, calibration, detection):
        """Keep OCR samples separate from the Box's derived corner handles."""
        if detection is None or self.plot_rect is None:
            return
        left, _, _, bottom = calibration.box_rect or self.plot_rect
        for axis, reading in (("x", detection.x), ("y", detection.y)):
            if not reading.ready:
                continue
            points = [AxisAnchor(t.position if axis == "x" else left,
                                 bottom if axis == "x" else t.position, t.value)
                      for t in reading.ticks if t.bbox != (0, 0, 0, 0)]
            if len(points) >= 2:
                setattr(calibration, "scale_" + axis, reading.scale)
                setattr(calibration, "mapping_" + axis, "ticks")
                calibration.set_axis_points(axis, points, sync_anchors=True)
        if calibration.box_rect is not None:
            self.plot_rect = tuple(int(round(v)) for v in calibration.box_rect)

    @recorded("Calibrate plot area")
    def calibrate_plot_rect(self, x_min, x_max, y_min, y_max):
        if self.plot_rect is None:
            raise ValueError("Select or detect the plot area first.")
        left, top, right, bottom = self.plot_rect
        candidate = Calibration(scale_x=self.calibration.scale_x, scale_y=self.calibration.scale_y,
                                snap_to_axes=self.calibration.snap_to_axes)
        for key, px, py, value in (("x1", left, bottom, x_min), ("x2", right, bottom, x_max),
                                   ("y1", left, bottom, y_min), ("y2", left, top, y_max)):
            candidate.set_anchor(key, px, py, value)
        self.calibration = candidate
        self.auto_tick_verified_axes = {"x", "y"}
        self.recompute_all_data()
        self._emit("calibration_changed")

    @recorded("Detect plot area")
    def detect_plot_area(self) -> bool:
        if self.image is None:
            return False
        self.plot_rect = detect_plot_area(self.image)
        self._emit("roi_changed")
        return self.plot_rect is not None

    def auto_detect_curve_color(self, minimum_saturation: int | None = None) -> bool:
        if self.image is None:
            return False
        ds = self.active_dataset
        sat = ds.settings.minimum_saturation if minimum_saturation is None else minimum_saturation
        rgb = detect_curve_color(self.image, self.plot_roi(), sat)
        if rgb is not None:
            self.set_curve_color(rgb)
        return rgb is not None

    def _calibrated_origin_pixel(self):
        """Return the exact image pixel for chart data origin (0, 0), when representable.

        Automatic generation uses this to guarantee one explicit origin sample.
        Logarithmic axes cannot represent zero, and an extrapolated origin outside
        the image is intentionally rejected rather than creating an invalid point.
        """
        if not self.calibration.ready():
            return None
        if self.calibration.scale_x in (AxisScale.LOG10, AxisScale.LN):
            return None
        if self.calibration.scale_y in (AxisScale.LOG10, AxisScale.LN):
            return None
        try:
            px, py = self.calibration.data_to_pixel(0.0, 0.0)
        except (ValueError, OverflowError):
            return None
        if not all(math.isfinite(value) for value in (px, py)):
            return None
        if self.image is not None and not (0 <= px < self.image.width and 0 <= py < self.image.height):
            return None
        return float(px), float(py)

    def _ensure_automatic_origin_sample(self, ds: Dataset) -> bool:
        """Ensure auto-generated data contains exactly one explicit (0, 0) sample.

        The origin is inserted at the closest arc position in extraction order,
        so a reversed/backtracking curve is not re-sorted by X or Y.  If an
        extracted point is already effectively at the origin, its pixel is snapped
        to the exact calibrated origin instead of adding a duplicate.
        """
        if not ds.extracted_pixels:
            return False
        origin = self._calibrated_origin_pixel()
        if origin is None:
            return False
        ox, oy = origin
        snap_tolerance = 0.75

        nearest_index = min(
            range(len(ds.extracted_pixels)),
            key=lambda index: math.hypot(ds.extracted_pixels[index][0] - ox,
                                         ds.extracted_pixels[index][1] - oy),
        )
        nearest = ds.extracted_pixels[nearest_index]
        if math.hypot(nearest[0] - ox, nearest[1] - oy) <= snap_tolerance:
            ds.extracted_pixels[nearest_index] = origin
            return True

        if len(ds.extracted_pixels) == 1:
            insert_at = 0 if math.hypot(ox - nearest[0], oy - nearest[1]) else 1
        else:
            _distance, along = project_onto_polyline(origin, ds.extracted_pixels)
            cumulative, _total = polyline_cumulative_lengths(ds.extracted_pixels)
            insert_at = len(ds.extracted_pixels)
            for index, arc in enumerate(cumulative):
                if along <= arc:
                    insert_at = index
                    break

        ds.extracted_pixels.insert(insert_at, origin)
        if ds.extracted_breaks is not None:
            ds.extracted_breaks = [break_index + 1 if break_index >= insert_at else break_index
                                   for break_index in ds.extracted_breaks]
        return True

    @recorded("Extract curve")
    def extract(self, settings: ExtractionSettings | None = None) -> bool:
        if self.image is None:
            return False
        ds = self._editable()
        if ds.curve_rgb is None:
            return False
        if settings is not None:
            ds.settings = settings
        ds.extracted_pixels = extract_curve(self.image, self.plot_roi(), ds.curve_rgb, ds.settings)
        ds.extracted_breaks = None
        self._ensure_automatic_origin_sample(ds)
        self.recompute_dataset_data(ds)
        self._emit("data_changed")
        return bool(ds.extracted_pixels)

    def compute_smart_detect(
        self,
        settings: ExtractionSettings | None = None,
        *,
        image: Image.Image | None = None,
        roi: tuple[int, int, int, int] | None = None,
        curve_rgb: tuple[int, int, int] | None = None,
        cancelled=None,
    ) -> SmartDetectionResult:
        """Compute smart detection without mutating engine state.

        This method is safe to run in a worker thread when ``image`` is a snapshot/copy.
        UI code can later call :meth:`apply_smart_detect_result` on the main thread.
        """
        img = image if image is not None else self.image
        if img is None:
            return SmartDetectionResult(error="No image loaded.")
        cfg = settings or self.active_dataset.settings
        try:
            def check_cancelled():
                if cancelled is not None and cancelled():
                    raise CancelledError('Curve extraction cancelled.')
            check_cancelled()
            # Normalize once for the complete worker pipeline; direct callers
            # may supply palette/grayscale/RGBA images rather than engine RGB.
            if img.mode != 'RGB':
                img = img.convert('RGB')
            options = {'cancelled': cancelled} if cancelled is not None else {}
            rect = roi or detect_plot_area(img, **options)
            roi = rect or (0, 0, img.width - 1, img.height - 1)
            check_cancelled()
            rgb = curve_rgb if curve_rgb is not None else detect_curve_color(img, roi, cfg.minimum_saturation, **options)
            if rgb is None:
                return SmartDetectionResult(plot_rect=rect, error="Could not detect curve color.")
            check_cancelled()
            points = extract_curve(img, roi, rgb, cfg, **options)
            check_cancelled()
            if not points:
                return SmartDetectionResult(plot_rect=rect, curve_rgb=rgb, error="No continuous curve could be extracted.")
            return SmartDetectionResult(plot_rect=rect, curve_rgb=rgb, extracted_pixels=points)
        except CancelledError:
            raise
        except Exception as exc:
            return SmartDetectionResult(error=str(exc))

    @recorded("Extract curve")
    def apply_smart_detect_result(
        self,
        result: SmartDetectionResult,
        settings: ExtractionSettings | None = None,
        *,
        dataset_index: int | None = None,
    ) -> bool:
        if result.error or result.curve_rgb is None or not result.extracted_pixels:
            return False
        index = self.active_dataset_index if dataset_index is None else int(dataset_index)
        if not 0 <= index < len(self.datasets):
            return False
        ds = self._editable(self.datasets[index])
        if settings is not None:
            ds.settings = settings
        self.plot_rect = result.plot_rect
        ds.curve_rgb = result.curve_rgb
        ds.extracted_pixels = list(result.extracted_pixels)
        ds.extracted_breaks = None
        self._ensure_automatic_origin_sample(ds)
        self.recompute_dataset_data(ds)
        self._emit("roi_changed")
        self._emit("dataset_changed")
        self._emit("data_changed")
        return True

    @recorded("Extract curve")
    def smart_detect(self, settings: ExtractionSettings | None = None) -> bool:
        ds = self._editable()
        if settings is not None:
            ds.settings = settings
        roi = self.plot_roi() if self.plot_rect or self.calibration_ready() else None
        result = self.compute_smart_detect(ds.settings, roi=roi, curve_rgb=ds.curve_rgb)
        return self.apply_smart_detect_result(result, ds.settings)

    @recorded("Add point")
    def add_manual_point(self, px: float, py: float) -> DataPoint:
        self._editable()
        px, py = self._pixel(px, py)
        p = DataPoint(float(px), float(py), source="manual")
        if self.calibration.ready():
            p.x, p.y = self.pixel_to_data(px, py)
        self.active_dataset.manual_points.append(p)
        self._emit("data_changed")
        return p

    def remove_manual_point(self, index: int) -> None:
        self.remove_points([("manual", index)])

    @recorded("Clear manual points")
    def clear_manual_points(self) -> None:
        self._editable()
        self.active_dataset.manual_points.clear()
        self._emit("data_changed")

    def point_pixels(self, source, index):
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("Point index must be a non-negative integer.")
        if source == "auto":
            return self.active_dataset.extracted_pixels[index]
        if source == "manual":
            point = self.active_dataset.manual_points[index]
            return point.px, point.py
        raise ValueError("Unknown point source.")

    @recorded("Move point")
    def move_point(self, source, index, px, py):
        ds = self._editable()
        px, py = self._pixel(px, py)
        self.point_pixels(source, index)
        if source == "auto":
            ds.extracted_pixels[index] = (px, py)
        else:
            ds.manual_points[index].px, ds.manual_points[index].py = px, py
        self.recompute_dataset_data(ds)
        self._emit("data_changed")

    def set_point_values(self, source, index, x, y):
        px, py = self.calibration.data_to_pixel(x, y)
        self.move_point(source, index, px, py)

    @recorded("Delete points")
    def remove_points(self, points):
        ds = self._editable()
        points = set(points)
        for source, index in points:
            self.point_pixels(source, index)
            if index < 0:
                raise ValueError("Point index must be non-negative.")
        deleted_auto = {index for source, index in points if source == "auto"}
        ds.extracted_breaks = remap_breaks(ds.extracted_breaks,
            [index for index in range(len(ds.extracted_pixels)) if index not in deleted_auto])
        for source in ("auto", "manual"):
            collection = ds.extracted_pixels if source == "auto" else ds.manual_points
            for index in sorted((i for s, i in points if s == source), reverse=True):
                del collection[index]
        self.recompute_dataset_data(ds)
        self._emit("data_changed")

    @recorded("Clear dataset points")
    def clear_points(self):
        ds = self._editable()
        ds.extracted_pixels.clear()
        ds.extracted_breaks = None
        ds.manual_points.clear()
        self.recompute_dataset_data(ds)
        self._emit("data_changed")

    @recorded("Reduce samples")
    def reduce_samples(self, max_error: float = 0.5) -> int:
        """Remove redundant samples from the active dataset, preserving shape.

        Automatic and manual paths are simplified independently. Store known
        extraction gaps so subsequent reduction does not mistake sparse,
        already-reduced samples for new gaps.
        """
        ds = self._editable()
        breaks = normalize_breaks(len(ds.extracted_pixels), ds.extracted_breaks)
        if breaks is None:
            gap = ds.settings.stride * (ds.settings.max_gap_columns + 1)
            breaks = [index for index in range(1, len(ds.extracted_pixels))
                      if ds.extracted_pixels[index][0] - ds.extracted_pixels[index - 1][0] > gap]
        manual_pixels = [(point.px, point.py) for point in ds.manual_points]
        cal = self.calibration
        logarithmic = cal.ready() and any(scale in (AxisScale.LOG10, AxisScale.LN)
                                         for scale in (cal.scale_x, cal.scale_y))

        def chart_geometry(pixels):
            if not logarithmic:
                return None
            # Normalize numeric XY to the calibrated pixel spans. Check both
            # spaces: a straight stroke on log axes is not a straight XY curve.
            return [((x - cal.x1.value) / (cal.x2.value - cal.x1.value) * abs(cal.x2.px - cal.x1.px),
                     (y - cal.y1.value) / (cal.y2.value - cal.y1.value) * abs(cal.y2.py - cal.y1.py))
                    for x, y in (self.pixel_to_data(*point) for point in pixels)]

        auto = simplify_indices(ds.extracted_pixels, max_error, breaks=breaks,
                                metric_points=chart_geometry(ds.extracted_pixels))
        manual = simplify_indices(manual_pixels, max_error, metric_points=chart_geometry(manual_pixels))
        removed = len(ds.extracted_pixels) + len(ds.manual_points) - len(auto) - len(manual)
        if not removed:
            return 0
        ds.extracted_breaks = remap_breaks(breaks, auto)
        ds.extracted_pixels = [ds.extracted_pixels[index] for index in auto]
        ds.manual_points = [ds.manual_points[index] for index in manual]
        self.recompute_dataset_data(ds)
        self._emit("data_changed")
        return removed

    def _ordered_curve_segments(self, ds):
        """Return continuous curve segments as (source, index, pixel) entries.

        Automatic extraction order defines the reference path when available;
        manual points are merged by nearest projected arc position.  This is
        intentionally the same ordering policy used by Smooth Curve so sample
        count changes never impose an X- or Y-sort.
        """
        auto = [tuple(map(float, point)) for point in ds.extracted_pixels]
        manual = [(float(point.px), float(point.py)) for point in ds.manual_points]
        if len(auto) >= 2:
            breaks = normalize_breaks(len(auto), ds.extracted_breaks)
            if breaks is None:
                gap = ds.settings.stride * (ds.settings.max_gap_columns + 1)
                breaks = [index for index in range(1, len(auto))
                          if auto[index][0] - auto[index - 1][0] > gap]
            boundaries = [0, *(breaks or []), len(auto)]
            segments = []
            for start, stop in zip(boundaries, boundaries[1:]):
                if stop <= start:
                    continue
                points = auto[start:stop]
                segments.append({"start": start, "stop": stop, "points": points, "manual": []})
            for manual_index, point in enumerate(manual):
                candidates = []
                for segment_index, segment in enumerate(segments):
                    distance, along = project_onto_polyline(point, segment["points"])
                    candidates.append((distance, segment_index, along))
                _distance, segment_index, along = min(candidates)
                segments[segment_index]["manual"].append((along, manual_index, point))
            ordered_segments = []
            for segment in segments:
                cumulative, _ = polyline_cumulative_lengths(segment["points"])
                ordered = [(cumulative[local], 0, "auto", segment["start"] + local, point)
                           for local, point in enumerate(segment["points"])]
                ordered.extend((along, 1, "manual", index, point)
                               for along, index, point in segment["manual"])
                ordered.sort(key=lambda item: (item[0], item[1], item[3]))
                ordered_segments.append([(item[2], item[3], item[4]) for item in ordered])
            return ordered_segments, breaks

        ordered = []
        if auto:
            ordered.append(("auto", 0, auto[0]))
        ordered.extend(("manual", index, point) for index, point in enumerate(manual))
        return ([ordered] if ordered else []), []

    @staticmethod
    def _proportional_counts(total, weights, *, capacities=None):
        """Integer proportional allocation with deterministic largest remainder."""
        if total <= 0:
            return [0] * len(weights)
        weights = [max(0.0, float(weight)) for weight in weights]
        capacities = [None] * len(weights) if capacities is None else list(capacities)
        result = [0] * len(weights)
        remaining = int(total)
        while remaining > 0:
            available = [index for index in range(len(weights))
                         if capacities[index] is None or result[index] < capacities[index]]
            if not available:
                break
            weight_total = sum(weights[index] for index in available)
            if weight_total <= 0:
                # Degenerate zero-length geometry: distribute evenly by index.
                for index in available:
                    if remaining <= 0:
                        break
                    result[index] += 1
                    remaining -= 1
                continue
            quotas = {index: remaining * weights[index] / weight_total for index in available}
            added = 0
            for index in available:
                whole = int(math.floor(quotas[index]))
                if capacities[index] is not None:
                    whole = min(whole, capacities[index] - result[index])
                if whole > 0:
                    result[index] += whole
                    remaining -= whole
                    added += whole
            if remaining <= 0:
                break
            available = [index for index in available
                         if capacities[index] is None or result[index] < capacities[index]]
            if not available:
                break
            # Largest fractional remainder; stable index tie-break.
            index = max(available, key=lambda i: (quotas.get(i, 0.0) - math.floor(quotas.get(i, 0.0)),
                                                   weights[i], -i))
            result[index] += 1
            remaining -= 1
            if added == 0 and remaining > 0 and all(weights[i] <= 0 for i in available):
                continue
        return result

    @recorded("Increase samples")
    def increase_samples(self, target_count: int | None = None) -> int:
        """Insert samples on the existing curve without changing its geometry.

        All original vertices are retained exactly. New points are inserted on
        existing finite line segments, distributed by segment arc length.  This
        makes repeated increases safe: they densify the digitized polyline but
        cannot overshoot it like a spline can.
        """
        ds = self._editable()
        current = len(ds.extracted_pixels) + len(ds.manual_points)
        if current < 2:
            raise ValueError("At least 2 points are required to increase samples.")
        if target_count is None:
            target_count = current * 2
        if isinstance(target_count, bool) or not isinstance(target_count, int):
            raise ValueError("Target sample count must be an integer.")
        if target_count <= current:
            return 0

        segments, _breaks = self._ordered_curve_segments(ds)
        edges = []
        for segment_index, segment in enumerate(segments):
            for edge_index, (first, last) in enumerate(zip(segment, segment[1:])):
                length = math.hypot(last[2][0] - first[2][0], last[2][1] - first[2][1])
                if length > 0:
                    edges.append((segment_index, edge_index, length))
        if not edges:
            raise ValueError("Cannot increase samples on a zero-length curve.")

        allocations = self._proportional_counts(target_count - current, [edge[2] for edge in edges])
        per_edge = {(segment_index, edge_index): count
                    for (segment_index, edge_index, _length), count in zip(edges, allocations) if count}
        inserted = []
        rebuilt_manual_only = [] if not ds.extracted_pixels else None

        for segment_index, segment in enumerate(segments):
            if not segment:
                continue
            if rebuilt_manual_only is not None:
                source, index, _point = segment[0]
                rebuilt_manual_only.append(ds.manual_points[index])
            for edge_index, (first, last) in enumerate(zip(segment, segment[1:])):
                count = per_edge.get((segment_index, edge_index), 0)
                x0, y0 = first[2]
                x1, y1 = last[2]
                for number in range(1, count + 1):
                    ratio = number / (count + 1)
                    coordinate = (x0 + (x1 - x0) * ratio, y0 + (y1 - y0) * ratio)
                    point = DataPoint(*coordinate)
                    if rebuilt_manual_only is not None:
                        rebuilt_manual_only.append(point)
                    else:
                        inserted.append(point)
                if rebuilt_manual_only is not None:
                    source, index, _point = last
                    if source != "manual":
                        raise ValueError("Unexpected automatic point in manual-only curve.")
                    rebuilt_manual_only.append(ds.manual_points[index])

        if rebuilt_manual_only is not None:
            ds.manual_points = rebuilt_manual_only
        else:
            ds.manual_points.extend(inserted)
        added = target_count - current
        self.recompute_dataset_data(ds)
        self._emit("data_changed")
        return added

    @recorded("Reduce sample count")
    def reduce_sample_count(self, target_count: int | None = None) -> int:
        """Reduce point count with curvature-aware selection of existing vertices.

        The default target is roughly half the current count. Continuous-curve
        endpoints are retained, and high-error/corner vertices are selected
        before points on straight spans. No X/Y sorting is used.
        """
        ds = self._editable()
        current = len(ds.extracted_pixels) + len(ds.manual_points)
        if current < 3:
            return 0
        segments, breaks = self._ordered_curve_segments(ds)
        if not segments:
            return 0

        required = []
        minimums = []
        lengths = []
        for segment in segments:
            coords = [item[2] for item in segment]
            _cumulative, length = polyline_cumulative_lengths(coords)
            lengths.append(length if length > 0 else float(len(segment)))
            local_required = set()
            if segment:
                local_required.update((0, len(segment) - 1))
            auto_positions = [pos for pos, item in enumerate(segment) if item[0] == "auto"]
            if auto_positions:
                local_required.update((auto_positions[0], auto_positions[-1]))
            # Hard corners/reversals are structural curve anchors.  Retaining
            # them prevents count-based reduction from cutting across an L, V
            # or backtracking branch merely to hit the nominal 50% target.
            for position in range(1, len(coords) - 1):
                ax, ay = coords[position - 1]
                bx, by = coords[position]
                cx, cy = coords[position + 1]
                first = (bx - ax, by - ay)
                second = (cx - bx, cy - by)
                first_len = math.hypot(*first)
                second_len = math.hypot(*second)
                if first_len <= 1e-12 or second_len <= 1e-12:
                    continue
                cosine = max(-1.0, min(1.0,
                    (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)))
                turn = math.acos(cosine)
                if turn >= math.radians(35.0):
                    local_required.add(position)
            required.append(local_required)
            minimums.append(len(local_required))

        minimum_total = sum(minimums)
        if target_count is None:
            target_count = max(minimum_total, int(math.ceil(current / 2.0)))
        if isinstance(target_count, bool) or not isinstance(target_count, int):
            raise ValueError("Target sample count must be an integer.")
        target_count = max(minimum_total, target_count)
        if target_count >= current:
            return 0

        extra = target_count - minimum_total
        capacities = [len(segment) - minimum for segment, minimum in zip(segments, minimums)]
        additions = self._proportional_counts(extra, lengths, capacities=capacities)
        keep_auto = set()
        keep_manual = set()
        for segment, local_required, minimum, addition in zip(segments, required, minimums, additions):
            desired = min(len(segment), minimum + addition)
            indices = select_polyline_indices([item[2] for item in segment], desired,
                                               required_indices=local_required)
            for local_index in indices:
                source, source_index, _coordinate = segment[local_index]
                (keep_auto if source == "auto" else keep_manual).add(source_index)

        retained_auto = sorted(keep_auto)
        retained_manual = sorted(keep_manual)
        new_count = len(retained_auto) + len(retained_manual)
        if new_count >= current:
            return 0
        ds.extracted_breaks = remap_breaks(breaks, retained_auto) if breaks is not None else None
        ds.extracted_pixels = [ds.extracted_pixels[index] for index in retained_auto]
        ds.manual_points = [ds.manual_points[index] for index in retained_manual]
        self.recompute_dataset_data(ds)
        self._emit("data_changed")
        return current - new_count

    @recorded("Smooth curve")
    def smooth_curve(self) -> int:
        """Redistribute active-dataset points uniformly along curve arc length.

        Manual and automatic samples are treated as one geometric curve.  The
        automatic extraction order is used as the reference path when it is
        available; manual samples are inserted by nearest arc position.  With a
        manual-only dataset, acquisition order is retained.  Point count and
        source identity are preserved, and every new coordinate lies on the
        pre-smoothing polyline rather than on a potentially overshooting spline.
        Disconnected automatic extraction segments are resampled independently.
        """
        ds = self._editable()
        auto = [tuple(map(float, point)) for point in ds.extracted_pixels]
        manual = [(float(point.px), float(point.py)) for point in ds.manual_points]
        total_count = len(auto) + len(manual)
        if total_count < 3:
            raise ValueError("At least 3 points are required to smooth the curve.")

        assignments = {}

        if len(auto) >= 2:
            breaks = normalize_breaks(len(auto), ds.extracted_breaks)
            if breaks is None:
                gap = ds.settings.stride * (ds.settings.max_gap_columns + 1)
                breaks = [index for index in range(1, len(auto))
                          if auto[index][0] - auto[index - 1][0] > gap]
            boundaries = [0, *(breaks or []), len(auto)]
            segments = []
            for start, stop in zip(boundaries, boundaries[1:]):
                if stop <= start:
                    continue
                segment_points = auto[start:stop]
                segments.append({
                    "start": start,
                    "stop": stop,
                    "points": segment_points,
                    "manual": [],
                })

            # Attach each manual point to the closest extracted segment, using
            # projected arc position solely for ordering.  The actual manual
            # coordinate remains part of the geometry and therefore can bridge
            # small gaps or correct an imperfect automatic extraction.
            for manual_index, point in enumerate(manual):
                candidates = []
                for segment_index, segment in enumerate(segments):
                    distance, along = project_onto_polyline(point, segment["points"])
                    candidates.append((distance, segment_index, along))
                _distance, segment_index, along = min(candidates)
                segments[segment_index]["manual"].append((along, manual_index, point))

            for segment in segments:
                reference = segment["points"]
                # Arc positions of automatic samples are exact and retain their
                # extraction order even for vertical, backtracking or looped paths.
                cumulative, _ = polyline_cumulative_lengths(reference)
                ordered = [(cumulative[local], 0, "auto", segment["start"] + local, point)
                           for local, point in enumerate(reference)]
                ordered.extend((along, 1, "manual", index, point)
                               for along, index, point in segment["manual"])
                ordered.sort(key=lambda item: (item[0], item[1], item[3]))
                geometry = [item[4] for item in ordered]
                smoothed = resample_polyline(geometry, len(ordered))
                for item, coordinate in zip(ordered, smoothed):
                    assignments[(item[2], item[3])] = coordinate
        else:
            # No reliable automatic path exists.  Preserve manual acquisition
            # order rather than silently imposing X- or Y-monotonic sorting.
            ordered = []
            if auto:
                ordered.append(("auto", 0, auto[0]))
            ordered.extend(("manual", index, point) for index, point in enumerate(manual))
            geometry = [item[2] for item in ordered]
            smoothed = resample_polyline(geometry, len(ordered))
            for item, coordinate in zip(ordered, smoothed):
                assignments[(item[0], item[1])] = coordinate

        moved = 0
        tolerance = 1e-9
        for index, old in enumerate(auto):
            coordinate = assignments[("auto", index)]
            if math.hypot(coordinate[0] - old[0], coordinate[1] - old[1]) > tolerance:
                moved += 1
            ds.extracted_pixels[index] = coordinate
        for index, old in enumerate(manual):
            coordinate = assignments[("manual", index)]
            if math.hypot(coordinate[0] - old[0], coordinate[1] - old[1]) > tolerance:
                moved += 1
            ds.manual_points[index].px, ds.manual_points[index].py = coordinate

        if moved:
            self.recompute_dataset_data(ds)
            self._emit("data_changed")
        return moved

    @recorded("Edit dataset")
    def update_dataset(self, *, name=None, visible=None, locked=None, dataset_index=None):
        ds = self.active_dataset if dataset_index is None else self.datasets[self._dataset_index(dataset_index)]
        if name is not None:
            name = str(name).strip()
            if not name:
                raise ValueError("Dataset name cannot be empty.")
            ds.name = name
        if visible is not None:
            ds.visible = bool(visible)
        if locked is not None:
            ds.locked = bool(locked)
        self._emit("dataset_changed")

    def recompute_dataset_data(self, ds: Dataset) -> None:
        if self.calibration.ready():
            origin = self._calibrated_origin_pixel()

            def calibrated_value(px, py):
                if origin is not None and math.hypot(float(px) - origin[0], float(py) - origin[1]) <= 1e-9:
                    return 0.0, 0.0
                return self.pixel_to_data(px, py)

            ds.extracted_data = [calibrated_value(px, py) for px, py in ds.extracted_pixels]
            for p in ds.manual_points:
                p.x, p.y = calibrated_value(p.px, p.py)
        else:
            ds.extracted_data = []
            for p in ds.manual_points:
                p.x = p.y = None

    def recompute_all_data(self) -> None:
        for ds in self.datasets:
            self.recompute_dataset_data(ds)

    @recorded("Add dataset")
    def add_dataset(self, name: str | None = None) -> int:
        idx = len(self.datasets)
        if name is None:
            used = {ds.name.casefold() for ds in self.datasets}
            number = idx + 1
            while f"Serie-{number}".casefold() in used:
                number += 1
            name = f"Serie-{number}"
        self.datasets.append(Dataset(name=name, marker_style=self._next_marker_style([ds.marker_style for ds in self.datasets])))
        self.active_dataset_index = idx
        self._emit("dataset_list_changed")
        return idx

    def _dataset_index(self, index):
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(self.datasets):
            raise IndexError("Dataset index is out of range.")
        return index

    @recorded("Duplicate dataset")
    def duplicate_dataset(self, index: int | None = None) -> int:
        """Create an independent, editable copy, including points and settings."""
        index = self._dataset_index(self.active_dataset_index if index is None else index)
        source = self.datasets[index]
        used = {ds.name.casefold() for ds in self.datasets}
        name, number = f"{source.name} (copy)", 2
        while name.casefold() in used:
            name = f"{source.name} (copy {number})"
            number += 1
        duplicate = copy.deepcopy(source)
        duplicate.name = name
        duplicate.locked = False
        duplicate.marker_style = self._next_marker_style([ds.marker_style for ds in self.datasets])
        self.datasets.append(duplicate)
        self.active_dataset_index = len(self.datasets) - 1
        self._emit("dataset_list_changed")
        return self.active_dataset_index

    @recorded("Delete dataset")
    def remove_dataset(self, index: int) -> None:
        index = self._dataset_index(index)
        if len(self.datasets) == 1:
            raise ValueError("At least one dataset is required.")
        self._editable(self.datasets[index])
        del self.datasets[index]
        if index < self.active_dataset_index:
            self.active_dataset_index -= 1
        else:
            self.active_dataset_index = min(self.active_dataset_index, len(self.datasets) - 1)
        self._emit("dataset_list_changed")

    def set_active_dataset(self, index: int) -> None:
        index = self._dataset_index(index)
        if self.active_dataset_index == index:
            return
        self.active_dataset_index = index
        self._emit("active_dataset_changed")

    def _project_payload(self, path):
        image_relative = None
        if self.image_path:
            try:
                image_relative = os.path.relpath(self.image_path, Path(path).resolve().parent)
            except ValueError:  # Image and project can live on different Windows drives.
                pass
        return {
            "version": self.PROJECT_VERSION,
            "image_path": self.image_path,
            "image_path_relative": image_relative,
            "plot_rect": self.plot_rect,
            "calibration": self.calibration.to_dict(),
            "verified_axes": sorted(self.auto_tick_verified_axes),
            "active_dataset_index": self.active_dataset_index,
            "datasets": [d.to_dict() for d in self.datasets],
        }
    def save_project(self, path: str, *, view_state=None) -> None:
        payload = self._project_payload(path)
        if Path(path).suffix.casefold() == ".pdg":
            for stored, dataset in zip(payload["datasets"], self.datasets):
                stored["extracted_data"] = list(dataset.extracted_data)
            write_pdg(path, {
                "project": payload,
                "view_state": copy.deepcopy(self.project_view_state if view_state is None else view_state),
                "history": {"undo": self._undo_stack, "redo": self._redo_stack},
            }, self.image)
        else:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def _project_candidate(cls, data, project_path, *, embedded=False, image=None):
        if not isinstance(data, dict):
            raise ValueError("Project must contain a JSON object.")
        version = data.get("version", 1)
        if not isinstance(version, int) or not 1 <= version <= cls.PROJECT_VERSION:
            raise ValueError("Unsupported Plot Digitizer project version.")
        candidate = cls()
        image_path = data.get("image_path")
        relative = data.get("image_path_relative")
        if embedded:
            candidate.image = image
            candidate.image_path = str(image_path) if image_path else None
        elif relative and (project_path.parent / relative).is_file():
            image_path = project_path.parent / relative
        elif image_path and not Path(image_path).is_absolute():
            image_path = project_path.parent / image_path
        if image_path and not embedded:
            candidate.load_image(str(image_path))
        pr = data.get("plot_rect")
        if pr is not None:
            candidate.set_plot_rect(pr)
        candidate.calibration = Calibration.from_dict(data.get("calibration", {}))
        candidate.calibration.validate()
        verified = data.get("verified_axes", ["x", "y"])
        if not isinstance(verified, list) or any(axis not in ("x", "y") for axis in verified):
            raise ValueError("Invalid verified calibration axes.")
        candidate.auto_tick_verified_axes = set(verified)
        for key in ("x1", "x2", "y1", "y2"):
            anchor = getattr(candidate.calibration, key)
            if anchor is not None:
                candidate._pixel(anchor.px, anchor.py)
        for anchor in candidate.calibration.points_x + candidate.calibration.points_y:
            candidate._pixel(anchor.px, anchor.py)
        candidate.datasets = [Dataset.from_dict(d) for d in data.get("datasets", [])] or [Dataset(marker_style=default_marker_style(0))]
        candidate._ensure_dataset_markers()
        for ds in candidate.datasets:
            cls._validate_settings(ds.settings)
            if ds.curve_rgb is not None and (len(ds.curve_rgb) != 3 or any(
                    not math.isfinite(float(c)) or not 0 <= float(c) <= 255 for c in ds.curve_rgb)):
                raise ValueError("Curve color must contain three RGB values in 0..255.")
            ds.extracted_pixels = [candidate._pixel(*p) for p in ds.extracted_pixels]
            ds.extracted_breaks = normalize_breaks(len(ds.extracted_pixels), ds.extracted_breaks)
            for point in ds.manual_points:
                point.px, point.py = candidate._pixel(point.px, point.py)
        candidate.active_dataset_index = max(0, min(int(data.get("active_dataset_index", 0)), len(candidate.datasets) - 1))
        candidate.recompute_all_data()
        return candidate

    def _project_history(self, entries, candidate, project_path):
        if not isinstance(entries, list) or len(entries) > self.HISTORY_LIMIT:
            raise ValueError("Invalid PDG edit history.")
        result = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2 or not isinstance(entry[0], str):
                raise ValueError("Invalid PDG edit history entry.")
            state = entry[1]
            if not isinstance(state, dict) or not {"active", "datasets", "calibration", "plot_rect"} <= state.keys():
                raise ValueError("Invalid PDG edit history state.")
            active, datasets = state["active"], state["datasets"]
            if (not isinstance(datasets, list) or not datasets or not isinstance(active, int) or
                    isinstance(active, bool) or not 0 <= active < len(datasets)):
                raise ValueError("Invalid PDG history dataset selection.")
            restored = self._project_candidate({
                "version": self.PROJECT_VERSION, "image_path": candidate.image_path,
                "plot_rect": state["plot_rect"], "calibration": state["calibration"],
                "datasets": datasets, "active_dataset_index": active,
                "verified_axes": state.get("verified_axes", ["x", "y"]),
            }, project_path, embedded=True, image=candidate.image)
            result.append((entry[0], restored._snapshot()))
        return result

    def load_project(self, path: str, *, view_validator=None):
        """Validate image, data, history and view off-state, then commit once."""
        project_path = Path(path).resolve()
        binary = project_path.suffix.casefold() == ".pdg"
        undo, redo, view_state = [], [], {}
        if binary:
            document, image = read_pdg(project_path)
            candidate = self._project_candidate(document.get("project"), project_path, embedded=True, image=image)
            view_state = document.get("view_state", {})
            if not isinstance(view_state, dict):
                raise ValueError("Invalid PDG workspace state.")
            history = document.get("history", {})
            if not isinstance(history, dict):
                raise ValueError("Invalid PDG edit history.")
            undo = self._project_history(history.get("undo", []), candidate, project_path)
            redo = self._project_history(history.get("redo", []), candidate, project_path)
        else:
            candidate = self._project_candidate(json.loads(project_path.read_text(encoding="utf-8")), project_path)
        if view_validator is not None:
            view_state = view_validator(view_state, candidate)
        self.image, self.image_path = candidate.image, candidate.image_path
        self.plot_rect, self.calibration = candidate.plot_rect, candidate.calibration
        self.auto_tick_verified_axes = set(candidate.auto_tick_verified_axes)
        self.datasets = candidate.datasets
        self.active_dataset_index = candidate.active_dataset_index
        self.project_view_state = copy.deepcopy(view_state)
        self._undo_stack, self._redo_stack = undo, redo
        self.revision += 1
        self._emit("project_loaded")
        return copy.deepcopy(view_state)

    def to_result_dict(self, *, status: str = "accepted") -> dict:
        """Return a JSON-serializable snapshot for external-process integration.

        This is intentionally UI-agnostic so WinUx, Abaqus launchers, or other
        hosts can exchange data with the standalone dialog through a result file.
        """
        datasets = []
        for ds in self.datasets:
            points = []
            for i, ((px, py), xy) in enumerate(zip(ds.extracted_pixels, ds.extracted_data), 1):
                x, y = xy
                points.append({
                    "index": i,
                    "x": x,
                    "y": y,
                    "pixel_x": px,
                    "pixel_y": py,
                    "source": "Smart",
                })
            base = len(points)
            for j, p in enumerate(ds.manual_points, 1):
                points.append({
                    "index": base + j,
                    "x": p.x,
                    "y": p.y,
                    "pixel_x": p.px,
                    "pixel_y": p.py,
                    "source": "Manual",
                })
            datasets.append({
                "name": ds.name,
                "visible": ds.visible,
                "locked": ds.locked,
                "curve_rgb": ds.curve_rgb,
                "marker_style": ds.marker_style,
                "points": points,
            })
        return {
            "status": status,
            "image_path": self.image_path,
            "plot_rect": self.plot_rect,
            "active_dataset_index": self.active_dataset_index,
            "calibration": self.calibration.to_dict(),
            "datasets": datasets,
        }

    def export_csv(self, path: str, dataset_index: int | None = None, *,
                   sort_by_x: bool = False, sort_by: str | None = None) -> None:
        # Retain the old keyword for integrations; the explicit axis wins.
        if sort_by is None and sort_by_x:
            sort_by = "x"
        if sort_by not in (None, "x", "y"):
            raise ValueError("CSV sort axis must be x, y or None.")
        if not self.calibration_ready():
            raise ValueError("Set X1, X2, Y1 and Y2 calibration before exporting chart data.")
        indices = [self._dataset_index(dataset_index)] if dataset_index is not None else list(range(len(self.datasets)))
        if not any(self.datasets[i].extracted_data or self.datasets[i].manual_points for i in indices):
            raise ValueError("Extract a curve or add points before exporting chart data.")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Dataset", "Index", "X", "Y", "PixelX", "PixelY", "Source"])
            for di in indices:
                ds = self.datasets[di]
                points = [(x, y, px, py, "Smart")
                          for (px, py), (x, y) in zip(ds.extracted_pixels, ds.extracted_data)]
                points.extend((p.x, p.y, p.px, p.py, "Manual") for p in ds.manual_points)
                if sort_by is not None:
                    # Stable sorting combines manual/automatic points without
                    # changing acquisition order or point identities in the UI.
                    points.sort(key=lambda point: point[0 if sort_by == "x" else 1])
                for i, point in enumerate(points, 1):
                    w.writerow([ds.name, i, *point])
