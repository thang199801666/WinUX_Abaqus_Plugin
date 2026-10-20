"""WinUx adapters using the application's native floating-dialog lifecycle."""
from __future__ import annotations

import json

from ..application import reference_candidate
from ...services.reference_charts import validate_reference
from ...dialogs.floating_dialog import FloatingDialogController


class WinUxReferenceSink:
    def __init__(self, library):
        self.library = library

    @property
    def available(self):
        return self.library is not None

    def add_dataset(self, dataset):
        if self.library is None:
            raise RuntimeError("Reference library is unavailable.")
        series = self.library.snapshot()
        candidate = reference_candidate(dataset, (item.get("name", "") for item in series))
        item = validate_reference(candidate)
        series.append(item)
        self.library.replace(series)
        return item


class StandalonePlotDigitizerController(FloatingDialogController):
    """Modeless tool HWND, with the same typography/chrome/focus as WinUx dialogs."""

    def __init__(self, view, reference_library=None):
        self.reference_library = reference_library
        super().__init__(
            view, "plotdigitizer", "Plot Digitizer",
            {"reference_available": reference_library is not None},
            width=1240, height=780, modal=False, resizable=True,
            allow_minimize=True, allow_maximize=True,
            # Keep the heavy Plot Digitizer object/DPG tree resident exactly
            # like a long-lived Qt tool window. X/Escape hides it; application
            # shutdown still calls destroy() and performs terminal cleanup.
            retain_on_close=True)

    @property
    def process(self):
        return self._process

    def _import_candidate(self, line):
        candidate = json.loads(line) if isinstance(line, str) else line
        if self.reference_library is None:
            raise RuntimeError("Reference library is unavailable.")
        series = self.reference_library.snapshot()
        used = {str(item.get("name") or "").casefold() for item in series}
        base = str(candidate.get("name") or "Digitized Curve").strip() or "Digitized Curve"
        candidate = dict(candidate)
        name, index = base, 2
        while name.casefold() in used:
            name = "{} ({})".format(base, index)
            index += 1
        candidate["name"] = name
        item = validate_reference(candidate)
        series.append(item)
        self.reference_library.replace(series)
        return item

    def handle_event(self, event, message):
        if event != "reference":
            return
        try:
            item = self._import_candidate(message.get("candidate"))
            self.post("reference_status", "Added '{}' to Reference Chart.".format(item["name"]))
        except (TypeError, ValueError, RuntimeError) as exc:
            self.post("reference_status", "Could not add reference: {}".format(exc))

    def close(self):
        return super().close()


PlotDigitizerWindow = StandalonePlotDigitizerController


def open_plot_digitizer(view, reference_library=None):
    # Plot Digitizer is a retained QApplication tool.  The legacy floating
    # process controller remains importable for explicit compatibility use, but
    # the application path no longer spawns a dialog process.
    from ...dialogs.native_reference_tools import PlotDigitizerDialog
    return PlotDigitizerDialog(view, reference_library)
