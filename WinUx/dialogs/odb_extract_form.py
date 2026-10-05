from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog, QtTable
from .theme import DialogMetrics
from .logic.odb import format_extract_number as _number, history_item_label as _item_label


class ODBExtractDialog(QtDialog):
    REVERSE_OPTIONS = ("As is", "Reverse X", "Reverse Y", "Reverse Both")

    def __init__(self, view, catalog, on_result):
        self.catalog = dict(catalog or {})
        self.on_result = on_result
        self._finished = False
        self._items = list(self.catalog.get("historyOutputs") or [])
        self._items_by_id = {str(item.get("id")): item for item in self._items}
        self._x_ids, self._y_ids = [], []
        super().__init__(view, "Extract ODB History Data", 980, 590)
        self.header("Extract History Output", "Select X and Y sources to create all combinations.")
        self.history = QtTable(self.content, ("Output Variables", "Points"), height=205, multiple=True)
        self.history.set_rows([(str(item.get("id")), (_item_label(item), item.get("points", 0))) for item in self._items])

        # X/Y selection panes share one layout row.  The old vertical stack
        # made a simple selection workflow feel like three unrelated panels;
        # placing them side-by-side mirrors a compact Qt splitter/form without
        # introducing another dock or custom widget.
        axes_layout = dpg.add_table(
            parent=self.content, header_row=False, width=-1,
            policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=False, borders_outerH=False,
            borders_innerV=False, borders_outerV=False,
        )
        dpg.add_table_column(parent=axes_layout, width_stretch=True, init_width_or_weight=1.0)
        dpg.add_table_column(parent=axes_layout, width_stretch=True, init_width_or_weight=1.0)
        self.axes = {}
        with dpg.table_row(parent=axes_layout):
            for axis in ("x", "y"):
                with dpg.group() as axis_panel:
                    with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP, parent=axis_panel) as axis_actions:
                        self.action(
                            "Add to {}".format(axis.upper()), lambda axis=axis: self._add_selected(axis),
                            "secondary", parent=axis_actions, width=84,
                        )
                        self.action(
                            "Remove {}".format(axis.upper()), lambda axis=axis: self._remove_selected(axis),
                            "secondary", parent=axis_actions, width=84,
                        )
                    self.axes[axis] = QtTable(axis_panel, (axis.upper() + " Data",), height=125, multiple=True)

        form = self.form_layout(label_width=118)
        self.reverse = self.form_layout_row(
            form, "Combine operation",
            lambda parent: self.combo(self.REVERSE_OPTIONS, parent=parent, default_value="As is"),
        )
        self.summary = self.status_text()
        self.ok_button = self.button_box([("Extract", self._accept, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False)])[0]
        self._refresh_axis_lists()

    def _add_selected(self, axis):
        target = self._x_ids if axis == "x" else self._y_ids
        for item in self._items:
            key = str(item.get("id"))
            if key in self.history.selected and key not in target:
                target.append(key)
        self._refresh_axis_lists()

    def _remove_selected(self, axis):
        target = self._x_ids if axis == "x" else self._y_ids
        target[:] = [key for key in target if key not in self.axes[axis].selected]
        self._refresh_axis_lists()

    def _refresh_axis_lists(self):
        for axis, ids in (("x", self._x_ids), ("y", self._y_ids)):
            self.axes[axis].set_rows([(key, ("{}{}  {}".format(axis.upper(), i, _item_label(self._items_by_id[key])),))
                                      for i, key in enumerate(ids, 1)])
        count = len(self._x_ids) * len(self._y_ids)
        dpg.set_value(self.summary, "{} X inputs x {} Y inputs = {} combined data set(s)".format(len(self._x_ids), len(self._y_ids), count))
        dpg.configure_item(self.ok_button, enabled=bool(count))

    def _accept(self):
        if self._x_ids and self._y_ids:
            self.finish({"x": [dict(self._items_by_id[key]) for key in self._x_ids],
                         "y": [dict(self._items_by_id[key]) for key in self._y_ids],
                         "reverse": dpg.get_value(self.reverse)})

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        try:
            if value is not None and callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _window_finished = finish


class ODBXYResultDialog(QtDialog):
    def __init__(self, view, result):
        self.result = dict(result or {})
        self.curves = list(self.result.get("curves") or [])
        super().__init__(view, "Extracted ODB Data", 600, 520, modal=False)
        self.header("Combined History Output data", "Choose a data set to inspect or copy its XY values.")
        self._labels = ["{}: {} | {} : {}".format(i+1, curve.get("name", "XY"),
            (curve.get("x") or {}).get("output", "X"), (curve.get("y") or {}).get("output", "Y"))
            for i, curve in enumerate(self.curves)]
        self.combo = self.combo(self._labels, parent=self.content,
            default_value=self._labels[0] if self._labels else "", callback=lambda s,v: self._show_curve(v))
        self.details = self.status_text(wrap=530)
        self.table = QtTable(self.content, ("X", "Y"), height=-1, multiple=True)
        self.button_box([("Select All", self._select_all, "secondary", False),
                         ("Copy", self._copy_selected, "secondary", False),
                         ("Close", self.destroy, "secondary", False)])
        self._show_curve(self._labels[0] if self._labels else "")
        self.shortcuts[(dpg.mvKey_C, True)] = self._copy_selected

    def _show_curve(self, label):
        self.table.selected.clear()
        curve = self.curves[self._labels.index(label)] if label in self._labels else {}
        self.table.set_rows([(i, (_number(x), _number(y))) for i, (x,y) in enumerate(curve.get("points") or [])])
        dpg.set_value(self.details, "{} points | X: {} | Y: {}".format(len(curve.get("points") or []),
            _item_label(curve.get("x") or {}), _item_label(curve.get("y") or {})))

    def _select_all(self):
        self.table.selected = {key for key, values in self.table.rows}
        for item in self.table.items.values():
            dpg.set_value(item, True)

    def _copy_selected(self):
        dpg.set_clipboard_text("\r\n".join("\t".join(values) for key, values in self.table.rows if key in self.table.selected))
