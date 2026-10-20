from __future__ import annotations

import csv
import json
import copy
import math
import os
from pathlib import Path
from typing import Callable
from PIL import Image

from .calibration import Calibration
from .models import (
    AxisScale, DataPoint, Dataset, ExtractionSettings, SmartDetectionResult,
    DATASET_MARKER_STYLES, default_marker_style, normalize_marker_style,
)
from .extraction import sample_color, detect_plot_area, detect_curve_color, extract_curve
from .history import recorded
from .reduction import simplify_indices, normalize_breaks, remap_breaks
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

    def _snapshot(self):
        return copy.deepcopy({"calibration": self.calibration.to_dict(), "plot_rect": self.plot_rect,
                              "datasets": [ds.to_dict() for ds in self.datasets],
                              "active": self.active_dataset_index})

    def _restore(self, state):
        self.calibration = Calibration.from_dict(state["calibration"])
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
        self.calibration = Calibration()
        for ds in self.datasets:
            ds.extracted_pixels.clear(); ds.extracted_data.clear(); ds.manual_points.clear()
            ds.extracted_breaks = None
            ds.curve_rgb = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.revision += 1
        self._emit("image_changed")

    def load_image(self, path: str) -> None:
        image, resolved = self.read_image(path)
        self.apply_image(image, resolved)

    @recorded("Calibrate axis")
    def set_anchor(self, key: str, px: float, py: float, value: float) -> None:
        px, py = self._pixel(px, py)
        self.calibration.set_anchor(key, px, py, value)
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
        calibration = Calibration.from_dict(data)
        calibration.validate()
        self.calibration = calibration
        self.recompute_all_data()
        self._emit("calibration_changed")

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
        self.calibration = Calibration(scale_x=self.calibration.scale_x, scale_y=self.calibration.scale_y)
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
        return self.calibration.ready()

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

    @recorded("Calibrate plot area")
    def calibrate_plot_rect(self, x_min, x_max, y_min, y_max):
        if self.plot_rect is None:
            raise ValueError("Select or detect the plot area first.")
        left, top, right, bottom = self.plot_rect
        candidate = Calibration(scale_x=self.calibration.scale_x, scale_y=self.calibration.scale_y)
        for key, px, py, value in (("x1", left, bottom, x_min), ("x2", right, bottom, x_max),
                                   ("y1", left, bottom, y_min), ("y2", left, top, y_max)):
            candidate.set_anchor(key, px, py, value)
        self.calibration = candidate
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
            rect = roi or detect_plot_area(img)
            roi = rect or (0, 0, img.width - 1, img.height - 1)
            rgb = curve_rgb if curve_rgb is not None else detect_curve_color(img, roi, cfg.minimum_saturation)
            if rgb is None:
                return SmartDetectionResult(plot_rect=rect, error="Could not detect curve color.")
            points = extract_curve(img, roi, rgb, cfg)
            if not points:
                return SmartDetectionResult(plot_rect=rect, curve_rgb=rgb, error="No continuous curve could be extracted.")
            return SmartDetectionResult(plot_rect=rect, curve_rgb=rgb, extracted_pixels=points)
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
            ds.extracted_data = [self.pixel_to_data(px, py) for px, py in ds.extracted_pixels]
            for p in ds.manual_points:
                p.x, p.y = self.pixel_to_data(p.px, p.py)
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
        for key in ("x1", "x2", "y1", "y2"):
            anchor = getattr(candidate.calibration, key)
            if anchor is not None:
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

    def export_csv(self, path: str, dataset_index: int | None = None, *, sort_by_x: bool = False) -> None:
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
                if sort_by_x:
                    # Stable sorting combines manual/automatic points without
                    # changing acquisition order or point identities in the UI.
                    points.sort(key=lambda point: point[0])
                for i, point in enumerate(points, 1):
                    w.writerow([ds.name, i, *point])
