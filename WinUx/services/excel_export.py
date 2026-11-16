"""Optional XLPP-backed Excel export helpers.

XLPP is imported lazily so WinUx startup never depends on a native Excel
extension.  The bundled CPython extension can therefore coexist with Abaqus
installations that use a different Python ABI; only Excel export reports the
compatibility problem.
"""
from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path


class ExcelExportUnavailable(RuntimeError):
    """Raised when the optional XLPP backend cannot be loaded."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundled_extensions() -> tuple[Path, ...]:
    vendor = _project_root() / "vendor"
    return tuple(sorted(vendor.glob("xlpp*.pyd"))) if vendor.is_dir() else ()


def _load_xlpp():
    """Load XLPP only when Excel export is requested.

    A system/PyPI XLPP installation is accepted too.  If import fails, produce
    a diagnostic that explains the ABI of the bundled native extension instead
    of letting an opaque ImportError escape into the UI.
    """
    try:
        return importlib.import_module("xlpp")
    except Exception as exc:
        bundled = _bundled_extensions()
        abi = "CPython {}.{} {}".format(sys.version_info.major, sys.version_info.minor,
                                         platform.machine() or "unknown")
        if bundled:
            names = ", ".join(path.name for path in bundled)
            message = (
                "XLPP could not be loaded by {}. Bundled backend: {}. "
                "Install/build an XLPP Python binding that matches this WinUx/Abaqus Python runtime."
            ).format(abi, names)
        else:
            message = (
                "XLPP is not available. Install the xlpp Python package or bundle a native "
                "extension matching {}."
            ).format(abi)
        raise ExcelExportUnavailable(message) from exc


def _axis_scale_name(scale) -> str:
    value = getattr(scale, "value", scale)
    return str(value)


def _dataset_points(dataset, sort_by: str | None = None):
    points = [(x, y, px, py, "Smart")
              for (px, py), (x, y) in zip(dataset.extracted_pixels, dataset.extracted_data)]
    points.extend((p.x, p.y, p.px, p.py, "Manual") for p in dataset.manual_points)
    if sort_by is not None:
        points.sort(key=lambda point: point[0 if sort_by == "x" else 1])
    return points


def export_plot_digitizer_xlsx(engine, path: str, dataset_index: int | None = None,
                                *, sort_by: str | None = None) -> None:
    """Export calibrated Plot Digitizer data through XLPP.

    The workbook intentionally uses only the stable, minimal XLPP Python API
    (Workbook, add_worksheet, Worksheet.append, Workbook.save).  Advanced chart
    creation can be layered on later without coupling the core export path to a
    larger binding surface.
    """
    if sort_by not in (None, "x", "y"):
        raise ValueError("Excel sort axis must be x, y or None.")
    if not engine.calibration_ready():
        raise ValueError("Set X1, X2, Y1 and Y2 calibration before exporting chart data.")
    indices = ([engine._dataset_index(dataset_index)] if dataset_index is not None
               else list(range(len(engine.datasets))))
    if not any(engine.datasets[i].extracted_data or engine.datasets[i].manual_points for i in indices):
        raise ValueError("Extract a curve or add points before exporting chart data.")

    xlpp = _load_xlpp()
    workbook = xlpp.Workbook()

    data = workbook.add_worksheet("XY Data")
    data.append(["Dataset", "Index", "X", "Y", "PixelX", "PixelY", "Source"])
    for di in indices:
        dataset = engine.datasets[di]
        for index, point in enumerate(_dataset_points(dataset, sort_by), 1):
            data.append([dataset.name, index, *point])

    calibration = workbook.add_worksheet("Calibration")
    calibration.append(["Property", "Value"])
    cal = engine.calibration
    for key, value in (
        ("X scale", _axis_scale_name(cal.scale_x)),
        ("Y scale", _axis_scale_name(cal.scale_y)),
        ("X mapping", cal.mapping_x),
        ("Y mapping", cal.mapping_y),
        ("Snap to axes", bool(cal.snap_to_axes)),
    ):
        calibration.append([key, value])
    calibration.append([])
    calibration.append(["Anchor", "PixelX", "PixelY", "Value"])
    for key in ("x1", "x2", "y1", "y2"):
        anchor = getattr(cal, key)
        if anchor is not None:
            calibration.append([key.upper(), anchor.px, anchor.py, anchor.value])
    for axis in ("x", "y"):
        points = getattr(cal, "points_" + axis)
        if points:
            calibration.append([])
            calibration.append([axis.upper() + " tick", "PixelX", "PixelY", "Value"])
            for index, anchor in enumerate(points, 1):
                calibration.append([index, anchor.px, anchor.py, anchor.value])

    metadata = workbook.add_worksheet("Metadata")
    metadata.append(["Property", "Value"])
    metadata.append(["Image path", engine.image_path or ""])
    metadata.append(["Active dataset", engine.active_dataset.name])
    metadata.append(["Exported datasets", len(indices)])
    if engine.plot_rect is not None:
        left, top, right, bottom = engine.plot_rect
        metadata.append(["Plot left", left])
        metadata.append(["Plot top", top])
        metadata.append(["Plot right", right])
        metadata.append(["Plot bottom", bottom])

    output = str(path)
    if not output.lower().endswith(".xlsx"):
        output += ".xlsx"
    workbook.save(output)
