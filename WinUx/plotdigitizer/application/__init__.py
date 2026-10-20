"""Host-neutral Plot Digitizer application workflows."""
from .references import dataset_xy_points, reference_candidate, unique_series_name
from .tasks import SmartDetectRunner
from .ports import ReferenceSink
from .workspace_state import normalize_workspace_state

__all__ = [
    "dataset_xy_points", "reference_candidate", "unique_series_name",
    "SmartDetectRunner", "ReferenceSink", "normalize_workspace_state",
]
