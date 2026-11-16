from __future__ import annotations

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog, QtTable
from DearUIQt.themes import DialogMetrics
from DearUIQt.gui.palette import QtFusionPalette
from DearUIQt.tooltip import add_styled_tooltip
from DearUIQt.layouts import QGridLayout, QVBoxLayout, QHBoxLayout
from ..logic.odb import format_extract_number as _number, history_item_label as _item_label


# Session-only ODB extraction choices.  This intentionally lives only in
# process memory: no settings/preferences/file persistence is involved.
# Keys are ODB paths (or another stable session key supplied by the controller).
_ODB_EXTRACT_SESSION_CHOICES = {}


def _style_odb_table(table):
    """Use the stable DearUIQt QTableView/QTableWidget-style native header.

    ODB-specific presentation is deliberately limited to row/grid behavior and
    column sizing.  Header rendering stays native so labels are never rebuilt
    through temporary presentation widgets.
    """
    table.setAlternatingRowColors(False)
    table.setShowGrid(True)
    return table


def _text_width(text):
    try:
        return float(dpg.get_text_size(str(text or ""))[0])
    except Exception:
        return float(len(str(text or "")) * 7)


def _center_with_spaces(text, width, *, inset=8):
    """Return a visually centered native-table label without custom headers."""
    text = str(text or "")
    available = max(0.0, float(width) - 2.0 * float(inset))
    missing = max(0.0, available - _text_width(text))
    try:
        space = max(2.0, float(dpg.get_text_size(" ")[0]))
    except Exception:
        space = 4.0
    return (" " * max(0, int(round((missing * 0.5) / space)))) + text


class ODBExtractDialog(QtDialog):
    REUSABLE_HOST = True
    REVERSE_OPTIONS = ("As is", "Reverse X", "Reverse Y", "Reverse Both")

    def __init__(self, view, catalog, on_result):
        self.catalog = dict(catalog or {})
        self._session_key = str(
            self.catalog.get("sessionKey") or self.catalog.get("path") or
            self.catalog.get("odb") or "")
        self.on_result = on_result
        self._finished = False
        self._loading = bool(self.catalog.get("loading"))
        self._catalog_message = str(self.catalog.get("message") or "")
        self._items = list(self.catalog.get("historyOutputs") or [])
        self._items_by_id = {str(item.get("id")): item for item in self._items}
        self._x_ids, self._y_ids = [], []
        self._history_tooltips = {}
        super().__init__(view, "Extract ODB History Data", 570, 585)
        self.header("Extract History Output", "Select X and Y sources to create all combinations.")
        self.history = QtTable(self.content, ("Output Variables", "Points"), height=196, multiple=True, row_height=22)
        # Compact QTableView-like presentation: white viewport, subtle grid,
        # tight row metrics, stretch name column and narrow numeric column.
        _style_odb_table(self.history)
        self.history.setColumnWidth("1", 72)
        self.history.set_rows(self._history_rows())
        self._refresh_history_tooltips()

        # X/Y selection panes share one layout row.  The old vertical stack
        # made a simple selection workflow feel like three unrelated panels;
        # placing them side-by-side mirrors a compact Qt splitter/form without
        # introducing another dock or custom widget.
        axes_layout = QGridLayout(
            2, parent=self._qt_parent(self.content), after=view.after,
            backend=dpg, height=0)
        self.own_widget(axes_layout)
        self.axes = {}
        for axis in ("x", "y"):
            column = 0 if axis == "x" else 1
            axis_panel = QVBoxLayout(parent=axes_layout.cell(0, column), spacing=4, backend=dpg)
            axis_actions = QHBoxLayout(
                parent=axis_panel, spacing=DialogMetrics.BUTTON_GAP, backend=dpg)
            self.action(
                "Add to {}".format(axis.upper()), lambda axis=axis: self._add_selected(axis),
                "secondary", parent=axis_actions.tag, width=84,
            )
            self.action(
                "Remove {}".format(axis.upper()), lambda axis=axis: self._remove_selected(axis),
                "secondary", parent=axis_actions.tag, width=84,
            )
            self.axes[axis] = QtTable(
                axis_panel.tag, (axis.upper() + " Data",), height=112, multiple=True, row_height=22)
            _style_odb_table(self.axes[axis])

        self._schedule_table_alignment()
        form = self.form_layout(label_width=118)
        saved = self._session_choices()
        saved_reverse = str(saved.get("reverse") or "As is")
        if saved_reverse not in self.REVERSE_OPTIONS:
            saved_reverse = "As is"
        self.reverse = self.form_layout_row(
            form, "Combine operation",
            lambda parent: self.combo(
                self.REVERSE_OPTIONS, parent=parent, default_value=saved_reverse,
                callback=lambda *_args: self._remember_session_choices()),
        )
        self.summary = self.status_text()
        self.ok_button = self.button_box([("Extract", self._accept, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False)])[0]
        self._restore_session_choices()
        self._refresh_axis_lists()

    def _session_choices(self):
        if not self._session_key:
            return {}
        return dict(_ODB_EXTRACT_SESSION_CHOICES.get(self._session_key) or {})

    def _restore_session_choices(self):
        saved = self._session_choices()
        available = set(self._items_by_id)
        self._x_ids[:] = [str(key) for key in saved.get("x_ids", ()) if str(key) in available]
        self._y_ids[:] = [str(key) for key in saved.get("y_ids", ()) if str(key) in available]
        reverse = str(saved.get("reverse") or "As is")
        if reverse in self.REVERSE_OPTIONS and hasattr(self, "reverse"):
            try:
                self.set_control_value(self.reverse, reverse)
            except Exception:
                pass

    def _remember_session_choices(self):
        if not self._session_key:
            return
        previous = dict(_ODB_EXTRACT_SESSION_CHOICES.get(self._session_key) or {})
        try:
            reverse = str(self.control_value(self.reverse))
        except Exception:
            reverse = str(previous.get("reverse") or "As is")
        if reverse not in self.REVERSE_OPTIONS:
            reverse = "As is"
        state = {"reverse": reverse}
        # Do not erase a valid selection merely because the asynchronous
        # catalog is still loading and the table is temporarily empty.
        if self._loading:
            state["x_ids"] = list(previous.get("x_ids") or ())
            state["y_ids"] = list(previous.get("y_ids") or ())
        else:
            state["x_ids"] = list(self._x_ids)
            state["y_ids"] = list(self._y_ids)
        _ODB_EXTRACT_SESSION_CHOICES[self._session_key] = state

    def _history_rows(self):
        # Points is a narrow fixed-width column.  Padding the native text is
        # deliberately presentation-only; row keys and source catalog values
        # remain untouched.
        return [
            (str(item.get("id")), (
                _item_label(item),
                _center_with_spaces(item.get("points", 0), 72, inset=4),
            ))
            for item in self._items
        ]

    def _center_native_header(self, table, labels, widths=None):
        try:
            total_width = float(dpg.get_item_rect_size(table.tag)[0])
        except Exception:
            total_width = 0.0
        widths = list(widths or ())
        if not widths:
            widths = [total_width / max(1, len(labels))] * len(labels)
        elif len(widths) < len(labels):
            fixed = sum(float(x) for x in widths if x is not None)
            stretch_count = sum(1 for x in widths if x is None)
            remaining = max(1.0, total_width - fixed)
            widths = [remaining / max(1, stretch_count) if x is None else float(x) for x in widths]
        for index, label in enumerate(labels):
            if index >= len(table.columns):
                continue
            column = table._column_item(table.columns[index].key)
            if column is None:
                continue
            width = widths[index] if index < len(widths) else total_width / max(1, len(labels))
            try:
                dpg.configure_item(column, label=_center_with_spaces(label, width, inset=6))
            except Exception:
                pass

    def _refresh_table_alignment(self):
        if not self.winfo_exists():
            return
        try:
            total = float(dpg.get_item_rect_size(self.history.tag)[0])
        except Exception:
            total = 0.0
        self._center_native_header(
            self.history, ("Output Variables", "Points"),
            (max(1.0, total - 72.0), 72.0),
        )
        for axis in ("x", "y"):
            self._center_native_header(self.axes[axis], (axis.upper() + " Data",))

    def _schedule_table_alignment(self):
        schedule = getattr(self.view, "after_render", None)
        if callable(schedule):
            schedule(self._refresh_table_alignment)
        else:
            self._refresh_table_alignment()

    def _refresh_history_tooltips(self):
        """Expose each full History Output name without widening the dialog."""
        for tag in tuple(self._history_tooltips.values()):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass
        self._history_tooltips.clear()
        for item in self._items:
            key = str(item.get("id"))
            cells = self.history._cell_native_items.get(key, ())
            if not cells:
                continue
            label = _item_label(item)
            if label:
                self._history_tooltips[key] = add_styled_tooltip(cells[0], label)

    def _add_selected(self, axis):
        target = self._x_ids if axis == "x" else self._y_ids
        for item in self._items:
            key = str(item.get("id"))
            if key in self.history.selected and key not in target:
                target.append(key)
        self._refresh_axis_lists()
        self._remember_session_choices()

    def _remove_selected(self, axis):
        target = self._x_ids if axis == "x" else self._y_ids
        target[:] = [key for key in target if key not in self.axes[axis].selected]
        self._refresh_axis_lists()
        self._remember_session_choices()

    def _refresh_axis_lists(self):
        for axis, ids in (("x", self._x_ids), ("y", self._y_ids)):
            self.axes[axis].set_rows([(key, ("{}{}  {}".format(axis.upper(), i, _item_label(self._items_by_id[key])),))
                                      for i, key in enumerate(ids, 1) if key in self._items_by_id])
        count = len(self._x_ids) * len(self._y_ids)
        if self._loading:
            text = "Loading History Output catalog from Abaqus..."
        elif self._catalog_message:
            text = self._catalog_message
        else:
            text = "{} History Output item(s) | {} X inputs x {} Y inputs = {} combined data set(s)".format(
                len(self._items), len(self._x_ids), len(self._y_ids), count)
        dpg.set_value(self.summary, text)
        dpg.configure_item(self.ok_button, enabled=bool(count) and not self._loading)

    def _replace_history_rows_atomic(self):
        """Publish a completed History Output catalog in one visible commit.

        ``QtTable.set_rows`` creates native rows synchronously.  When the table
        is already visible (the asynchronous catalog path), DearPyGui may paint
        intermediate rows while that loop is still materializing the catalog.
        Temporarily hiding only the native table keeps the existing dialog and
        layout alive but prevents those intermediate row states from becoming
        visible.  The fully populated table is published once at the end of the
        same UI callback.
        """
        rows = self._history_rows()
        hidden = False
        try:
            if dpg.does_item_exist(self.history.tag):
                dpg.configure_item(self.history.tag, show=False)
                hidden = True
        except Exception:
            # The table can still be populated safely if visibility control is
            # unavailable on a compatibility backend.
            hidden = False
        try:
            self.history.set_rows(rows)
            self._refresh_history_tooltips()
        finally:
            if hidden:
                try:
                    if dpg.does_item_exist(self.history.tag):
                        dpg.configure_item(self.history.tag, show=True)
                except Exception:
                    pass

    def _set_catalog(self, catalog, message=""):
        incoming = dict(catalog or {})
        incoming_key = str(
            incoming.get("sessionKey") or incoming.get("path") or
            incoming.get("odb") or self._session_key or "")
        if incoming_key:
            incoming["sessionKey"] = incoming_key
            self._session_key = incoming_key
        self.catalog = incoming
        self._loading = False
        self._catalog_message = str(message or "")
        self._items = list(self.catalog.get("historyOutputs") or [])
        self._items_by_id = {str(item.get("id")): item for item in self._items}
        self.history.selected.clear()
        self._restore_session_choices()
        self._replace_history_rows_atomic()
        self._refresh_axis_lists()
        self._schedule_table_alignment()

    def set_catalog(self, catalog, message=""):
        """Replace the asynchronously loaded History Output catalog in-place.

        This public method intentionally mirrors the floating-dialog adapter
        API so controllers can update either host implementation without
        branching on the concrete dialog class.
        """
        self._set_catalog(catalog, message)

    def set_error(self, message):
        """Show an asynchronous catalog-loading failure in this dialog."""
        self._set_catalog({}, str(message or "Unable to read ODB History Output data."))

    def handle_command(self, command, *args, **kwargs):
        if command == "catalog_ready":
            catalog = args[0] if args else {}
            message = args[1] if len(args) > 1 else ""
            self._set_catalog(catalog, message)
            return
        if command == "catalog_error":
            self._set_catalog({}, args[0] if args else "Unable to read ODB History Output data.")
            return
        return super().handle_command(command, *args, **kwargs)

    def _accept(self):
        if self._x_ids and self._y_ids:
            self._remember_session_choices()
            self.finish({"x": [dict(self._items_by_id[key]) for key in self._x_ids],
                         "y": [dict(self._items_by_id[key]) for key in self._y_ids],
                         "reverse": self.control_value(self.reverse),
                         "abaqusCommand": self.catalog.get("abaqusCommand")})

    def finish(self, value):
        if self._finished:
            return
        self._remember_session_choices()
        self._finished = True
        try:
            if value is not None and callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _window_finished = finish


class ODBXYResultDialog(QtDialog):
    REUSABLE_HOST = True

    def __init__(self, view, result):
        self.result = dict(result or {})
        self.curves = list(self.result.get("curves") or [])
        super().__init__(view, "Extracted ODB Data", 455, 510, modal=False)
        self.header("Combined History Output data", "Choose a data set to inspect or copy its XY values.")
        self._labels = ["{}: {} | {} : {}".format(i+1, curve.get("name", "XY"),
            (curve.get("x") or {}).get("output", "X"), (curve.get("y") or {}).get("output", "Y"))
            for i, curve in enumerate(self.curves)]
        self.combo = self.combo(self._labels, parent=self.content,
            default_value=self._labels[0] if self._labels else "", callback=lambda s,v: self._show_curve(v))
        self.details = self.status_text(wrap=405)
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
