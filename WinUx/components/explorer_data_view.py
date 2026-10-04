"""Sorting, row-data refresh and status presentation for ExplorerListView."""
from __future__ import annotations

from datetime import datetime

import dearpygui.dearpygui as dpg

from .explorer_list_model import human_size
from ..platform.windows_icons import WindowsIconRegistry


class ExplorerDataViewMixin:
    def _update_header_sort_indicator(self):
        """Paint triangle direction/visibility before the deferred row sort."""
        for key, parts in self._header_items.items():
            if dpg.does_item_exist(parts["indicator"]):
                config = dpg.get_item_configuration(parts["indicator"])
                p1, p2, p3 = config["p1"], config["p2"], config["p3"]
                top = min(p1[1], p2[1], p3[1])
                bottom = max(p1[1], p2[1], p3[1])
                base_y, tip_y = (bottom, top) if self.sort_ascending else (top, bottom)
                dpg.configure_item(
                    parts["indicator"],
                    p1=(p1[0], base_y), p2=(p2[0], base_y),
                    p3=(p3[0], tip_y), show=self.sort_key == key,
                )

    def _schedule_sort_refresh(self):
        """Run sorting on the next frame so the arrow paints before row updates."""
        try:
            dpg.set_frame_callback(dpg.get_frame_count() + 1, callback=lambda: self._sort_and_refresh_in_place())
        except Exception:
            self._sort_and_refresh_in_place()

    def _sort_and_refresh_in_place(self):
        state = self._item_model.reorder(
            self.selected, self.last_clicked_index, self._current_index,
            self.sort_key, self.sort_ascending)
        self.selected = state.selected
        self.last_clicked_index = state.anchor
        self._current_index = state.current
        self._sync_qt_selection_from_fields()
        self._refresh_row_content()
        self._layout_all()
        self._update_status_bar()

    def _refresh_row_content(self):
        """Refresh materialized rows while preserving the logical item model."""
        if self._row_virtualization_active():
            self._sync_virtual_rows()
        elif len(self._row_items) != len(self.items):
            self._rebuild_draw_items()
            return
        self._refresh_row_registry_content()

    def _sort_items(self):
        self._item_model.sort(self.sort_key, self.sort_ascending)

    def _display_cell_value(self, item, key):
        override_key = (id(item), key)
        if override_key in self._cell_values:
            value = self._cell_values[override_key]
            return str(value(item, key) if callable(value) else value)
        if key == "name":
            return item.name
        return self._cell_text(item, key)

    def _cell_text(self, item, key):
        override_key = (id(item), key)
        if override_key in self._cell_values:
            value = self._cell_values[override_key]
            return str(value(item, key) if callable(value) else value)
        if key in item.data:
            value = item.data[key]
            return str(value(item, key) if callable(value) else value)
        if key == "date":
            return getattr(item, "cached_date_text", None) or (
                datetime.fromtimestamp(item.mtime).strftime("%m/%d/%Y %I:%M %p")
                if item.mtime else "")
        if key == "type":
            return item.item_type
        if key == "size":
            cached = getattr(item, "cached_size_text", None)
            return cached if cached is not None else (
                "" if item.is_dir else human_size(item.size))
        return ""

    def _update_status_bar(self):
        count = len(self.items)
        dpg.set_value(self.status_items_tag, f"{count} item{'s' if count != 1 else ''}")
        if self.selected:
            selected = self.get_selected()
            total = sum(item.size for item in selected if not item.is_dir)
            size_text = f"    {human_size(total)}" if total else ""
            dpg.set_value(self.status_sel_tag, f"    |    {len(selected)} selected{size_text}")
        else:
            dpg.set_value(self.status_sel_tag, "")
