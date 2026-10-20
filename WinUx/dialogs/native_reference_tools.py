"""Retained application tools sharing WinUx's native DearUIQt context."""
from .inprocess.common import RetainedTool
from .reference_chart_form import (
    ReferenceChartDialog as ReferenceChartForm,
    _draft_reference_series, _reference_series_signature,
)
from ..plotdigitizer.ui.dialog import PlotDigitizerDialog as PlotDigitizerForm
from ..plotdigitizer.integration.winux import WinUxReferenceSink


class ReferenceChartDialog(RetainedTool, ReferenceChartForm):
    def __init__(self, view, series, on_result, history_outputs=None):
        ReferenceChartForm.__init__(self, view, series, on_result, history_outputs)
        self._init_inprocess_lifetime(view)

    def begin_session(self, series, on_result, history_outputs=None, source_revision=None):
        self.on_result = on_result
        self._history_outputs = list(history_outputs or [])
        signature = _reference_series_signature(series)
        source_changed = (
            source_revision is not None
            and source_revision != getattr(self, "_source_revision", None)
        ) or signature != getattr(self, "_source_signature", ())
        # A finished retained dialog always starts a fresh draft, even if the
        # library revision did not change (Cancel must discard prior edits).
        if self._finished or source_changed:
            self._finished = False
            self._source_revision = source_revision
            self._source_signature = signature
            self._series = _draft_reference_series(series)
            self._editor_dirty = False
            self._editing_id = None
            self._rename_name = None
            self._refresh_list(select_first=True)
            selected = self._selected()
            if selected is not None:
                self._load_item(selected)
            else:
                self._new_input()

    def focus(self):
        self.show()
        return self.activateWindow()


class PlotDigitizerDialog(RetainedTool, PlotDigitizerForm):
    def __init__(self, view, reference_library=None):
        PlotDigitizerForm.__init__(self, view, reference_sink=WinUxReferenceSink(reference_library))
        self._init_inprocess_lifetime(view)

    def focus(self):
        self.show()
        return self.activateWindow()
