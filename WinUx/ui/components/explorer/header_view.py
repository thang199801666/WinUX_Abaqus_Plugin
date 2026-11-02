"""QHeaderView-like facade for the draw-list ExplorerListView backend.

The renderer remains 100% Dear ImGui/Dear PyGui.  This adapter only exposes
Qt-style header properties so the file panels and generic ImGui item views can
share one behavioral contract without forcing Explorer onto dpg.table.
"""
from __future__ import annotations


class ExplorerHeaderView:
    Interactive = "interactive"
    Fixed = "fixed"
    Stretch = "stretch"

    def __init__(self, view):
        self._view = view
        self._visible = True
        self._sections_movable = False
        self._sections_clickable = True
        self._stretch_last = False
        self._default_section_size = 100.0
        self._resize_modes = {}

    def _columns(self):
        return list(self._view._visible_columns())

    def _column(self, section):
        try:
            return self._columns()[int(section)]
        except (IndexError, TypeError, ValueError):
            return None

    def isVisible(self):
        return bool(self._visible)

    def setVisible(self, visible):
        self._visible = bool(visible)
        self._view.setHeaderVisible(self._visible)
        return self

    def setStretchLastSection(self, enabled):
        self._stretch_last = bool(enabled)
        columns = self._columns()
        if columns and self._stretch_last:
            self._view.auto_fit_column_key = columns[-1]["key"]
            self._view._ensure_column_widths(force=True)
            self._view._layout_all()
        return self

    def stretchLastSection(self):
        return bool(self._stretch_last)

    def setSectionsMovable(self, enabled):
        # Explorer's draw-list columns intentionally do not reorder while file
        # drag/drop is active.  Keep the property for Qt API parity and report
        # the requested state, but do not mutate column order implicitly.
        self._sections_movable = bool(enabled)
        return self

    def sectionsMovable(self):
        return bool(self._sections_movable)

    def setSectionsClickable(self, enabled):
        self._sections_clickable = bool(enabled)
        self._view._header_sections_clickable = self._sections_clickable
        return self

    def sectionsClickable(self):
        return bool(self._sections_clickable)

    def setDefaultSectionSize(self, size):
        self._default_section_size = max(1.0, float(size))
        return self

    def defaultSectionSize(self):
        return float(self._default_section_size)

    def resizeSection(self, section, size):
        column = self._column(section)
        if column is None:
            return False
        self._view.set_column_width(column["key"], size)
        return True

    def sectionSize(self, section):
        column = self._column(section)
        if column is None:
            return None
        return float(self._view._column_widths.get(
            column["key"], self._view.MIN_COLUMN_WIDTH))

    def setSectionResizeMode(self, section, mode):
        column = self._column(section)
        if column is None:
            return False
        mode = str(mode).lower()
        if mode not in (self.Interactive, self.Fixed, self.Stretch):
            return False
        key = column["key"]
        self._resize_modes[key] = mode
        column["resizable"] = mode != self.Fixed
        if mode == self.Stretch:
            self._view.auto_fit_column_key = key
            self._view._ensure_column_widths(force=True)
        self._view._layout_all()
        return True

    def sectionResizeMode(self, section):
        column = self._column(section)
        if column is None:
            return None
        return self._resize_modes.get(column["key"], self.Interactive)

    def setAutoWidth(self, enabled):
        self._view.set_auto_width(enabled)
        return self

    def autoWidth(self):
        return self._view.auto_width()


__all__ = ["ExplorerHeaderView"]
