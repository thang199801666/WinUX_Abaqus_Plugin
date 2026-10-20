"""Plot Digitizer public feature API.

Core and application layers are intentionally host-neutral. WinUx-specific UI
and adapters are lazy/explicit imports under ``ui`` and ``integration``.
"""
from .core import (
    DigitizerEngine, AxisScale, AxisAnchor, DataPoint, Dataset,
    ExtractionSettings, SmartDetectionResult,
)
from .application import (
    SmartDetectRunner, dataset_xy_points, reference_candidate,
    unique_series_name,
)

__all__ = [
    "DigitizerEngine", "AxisScale", "AxisAnchor", "DataPoint", "Dataset",
    "ExtractionSettings", "SmartDetectionResult", "SmartDetectRunner",
    "dataset_xy_points", "reference_candidate", "unique_series_name",
]
