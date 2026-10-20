"""Manage persistent comparison curves in an isolated DPG dialog."""
from __future__ import annotations

import copy

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.core import Qt, QGlobalInputBinding
from DearUIQt.gui import QClipboard, QCursor
from DearUIQt.widgets import QLineEdit, QFrame, QLabel, QSpacer
from DearUIQt.layouts import QGridLayout
from DearUIQt.modelview import QListWidget, QListWidgetItem
from ..services.reference_charts import (
    make_formula_reference, parse_reference_text, validate_reference)
from ..ui.components.reference_data_table import ReferenceDataTable
from DearUIQt.widgets import QMenu
from ..ui.components.toolbar import ResourceTextures




def _draft_reference_series(series):
    """Create an editable library draft without cloning large XY arrays.

    Reference points are validated immutable-by-convention while a dialog
    session is open. The editor uses a sparse copy-on-write worksheet, so only
    the series metadata needs a private copy here.
    """
    result = []
    for raw in list(series or []):
        if not isinstance(raw, dict):
            result.append(copy.deepcopy(raw))
            continue
        item = dict(raw)
        # Preserve the exact points object so begin_session + worksheet binding
        # remain O(number of series + visible rows), not O(total points).
        item["points"] = raw.get("points") or []
        result.append(item)
    return result


def _reference_series_signature(series):
    """Cheap identity signature that never compares every XY point."""
    signature = []
    for item in list(series or []):
        if not isinstance(item, dict):
            signature.append((id(item),))
            continue
        points = item.get("points") or []
        signature.append((
            str(item.get("id") or ""),
            str(item.get("name") or ""),
            bool(item.get("enabled", True)),
            str(item.get("kind") or ""),
            str(item.get("formula") or ""),
            len(points),
            id(points),
        ))
    return tuple(signature)

FORMULA_FUNCTIONS = [
    ("combine", "combine(regex_x, regex_y)", "Use the first matched history value as X and the second as Y."),
    ("add", "add(regex_a, regex_b)", "Add matched Y values sample-by-sample."),
    ("subtract", "subtract(regex_a, regex_b)", "Subtract B from A."),
    ("multiply", "multiply(regex_a, regex_b)", "Multiply matched Y values."),
    ("divide", "divide(regex_a, regex_b)", "Divide A by B."),
    ("average", "average(regex_a, regex_b, ...)", "Arithmetic mean of matched values."),
    ("magnitude", "magnitude(regex_a, regex_b, ...)", "sqrt(a^2 + b^2 + ...)."),
    ("abs", "abs(regex)", "Absolute value."),
    ("negate", "negate(regex)", "Change sign."),
    ("sqrt", "sqrt(regex)", "Square root."),
    ("square", "square(regex)", "Square the value."),
    ("scale", "scale(regex, factor)", "Multiply a series by a scalar factor."),
    ("offset", "offset(regex, value)", "Add a scalar offset to a series."),
]




class ReferenceFormulaDialog(QtDialog):
    """Create a persistent regex/formula rule independent of current Plot data."""

    def __init__(self, view, history_outputs, on_add):
        self.history_outputs = []  # compatibility; formula creation is catalog-independent
        self.on_add = on_add
        self._finished = False
        super().__init__(view, "Add Reference by Formula", 700, 250)
        self.preferred_size = (700, 250)

        QLabel("Formula", parent=self.contentWidget())
        self.formula_edit = self.line_edit(
            "combine(.*U1, .*RF1)", parent=self.content, width=-1)
        self.note(
            "Regex selectors are saved as a rule and resolved automatically against each Plot. Functions: "
            "combine, add, subtract, multiply, divide, average, magnitude, "
            "abs, negate, sqrt, square, scale, offset.",
            parent=self.content, wrap=650)
        self.status = self.status_text(
            "No active History Output is required. The rule is resolved at Plot runtime.",
            parent=self.content)
        self.button_box([
            ("Add", self._add, "primary", True),
            ("Cancel", self.destroy, "secondary", False),
        ], status_item=self.status)

    def _add(self):
        formula = str(self.control_value(self.formula_edit, "") or "").strip()
        try:
            series = [make_formula_reference(formula)]
        except (TypeError, ValueError) as exc:
            self.set_control_value(self.status, str(exc))
            return False
        if callable(self.on_add):
            self.on_add(series, formula)
        self.destroy()
        return True


class ReferenceChartDialog(QtDialog):
    """Reference-series library with two explicit authoring workflows.

    XY Data stores pasted/manual points. Formula stores a persistent regex rule
    resolved against each Plot's History Output catalog at runtime.
    """

    REUSABLE_HOST = True

    def __init__(self, view, series, on_result, history_outputs=None):
        self.on_result = on_result
        self._finished = False
        self._series = _draft_reference_series(series)
        self._source_signature = _reference_series_signature(series)
        self._source_revision = None
        self._editing_id = None
        self._editor_dirty = False
        self._selection_guard = False
        self._selected_name = ""
        self._series_selectables = {}
        self._rename_name = None
        self._rename_editor = None
        self._rename_editor_control = None
        self._rename_outside_armed = False
        self._history_outputs = list(history_outputs or [])
        self._formula_dialog = None
        self._formula_mode = False
        self._reference_type_guard = False

        super().__init__(view, "Reference Chart", 700, 610)
        self.preferred_size = (700, 610)
        # Keep the compact X/Y editor at a stable width and let the reference
        # library consume every remaining horizontal pixel.  This makes the
        # series list grow naturally when the dialog is resized instead of
        # wasting space to the right of the narrow worksheet.
        self._workspace_grid = self.own_widget(QGridLayout(
            2, column_widths=(None, 382), parent=self.contentWidget(),
            after=self.view.after, height=-1, vertical_dividers=True))

        self._library_panel_widget = self.own_widget(QFrame(
            parent=self._workspace_grid.cell(0, 0), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.library_panel = self._library_panel_widget.tag
        QLabel("Reference series", parent=self._library_panel_widget)
        self._saved_list_view = self.own_widget(QListWidget(
            parent=self._library_panel_widget, width=-1, height=-1,
            context_menu_requests=True))
        self.saved_list = self._saved_list_view.tag
        self._saved_list_view.itemClicked.connect(
            self._series_list_clicked, receiver=self)
        self._saved_list_view.contextMenuRequested.connect(
            self._series_list_context_menu, receiver=self)

        self._series_menu = QMenu([
            {"id": "rename", "label": "Rename", "action": "rename",
             "icon": ResourceTextures.get("Rename")},
            {"id": "delete", "label": "Delete", "action": "delete",
             "icon": ResourceTextures.get("Delete")},
        ], after=self.view.after, min_width=146,
           parent_window=self.tag, parent=self)
        self._series_menu.triggered.connect(self._series_context_action)
        self._rename_input_binding = QGlobalInputBinding(parent=self)
        self._rename_input_binding.onMouseClick(Qt.LeftButton, self._rename_outside_click)
        self._rename_input_binding.activate()

        self._editor_panel_widget = self.own_widget(QFrame(
            parent=self._workspace_grid.cell(0, 1), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.editor_panel = self._editor_panel_widget.tag
        # Header rows must keep their natural/fixed height.  A DearPyGui
        # table with height=-1 consumes all remaining vertical space, which
        # pushed the series-name row and the X/Y worksheet completely below
        # the visible editor pane when this dialog moved in-process.  Match
        # Qt layout semantics here: compact controls get a bounded row and the
        # worksheet is the only vertical-expanding child.
        self._type_grid = self.own_widget(QGridLayout(
            2, column_widths=(96, None), parent=self._editor_panel_widget,
            after=self.view.after, height=32))
        QLabel("Reference type", parent=self._type_grid.cell(0, 0))
        self.reference_type_combo = self.combo(
            ("XY Data", "Formula"), parent=self._type_grid.cell(0, 1).tag,
            default_value="XY Data", width=-1,
            callback=self._reference_type_changed)
        QSpacer(0, 2, parent=self._editor_panel_widget)

        self._name_grid = self.own_widget(QGridLayout(
            3, column_widths=(82, None, 104), parent=self._editor_panel_widget,
            after=self.view.after, height=32))
        QLabel("Series name", parent=self._name_grid.cell(0, 0))
        name_host = self._name_grid.cell(0, 1)
        self.name_edit = self.line_edit(
            self._next_default_name(), parent=name_host.tag, width=-1,
            callback=self._name_changed)
        save_host = self._name_grid.cell(0, 2)
        self.save_series_button = self.action(
            "Save XY", self._save_series, role="primary",
            parent=save_host.tag, width=98)
        self.add_button = self.save_series_button

        self._formula_group_widget = self.own_widget(QFrame(
            parent=self._editor_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True,
            show=False))
        self.formula_group = self._formula_group_widget.tag
        QLabel("Formula", parent=self._formula_group_widget)
        self.formula_edit = self.plain_text_edit(
            "combine(.*U1, .*RF1)",
            parent=self.formula_group, width=-1, height=92,
            callback=self._formula_changed)
        self.note(
            "Regex selectors are resolved automatically against the History Output catalog.",
            parent=self.formula_group, wrap=350)
        QLabel("Functions  (double-click to insert)", parent=self._formula_group_widget)
        self._formula_functions_view = self.own_widget(QListWidget(
            parent=self._formula_group_widget, after=self.view.after,
            width=-1, height=220))
        self.formula_functions = self._formula_functions_view.tag
        self._formula_function_items = []
        for fn_name, fn_syntax, fn_help in FORMULA_FUNCTIONS:
            item = QListWidgetItem(fn_syntax)
            item.setData(Qt.UserRole, (fn_name, fn_syntax, fn_help))
            self._formula_function_items.append(item)
        # Populate the function palette in one native batch rather than
        # rebuilding it once per function during dialog startup.
        self._formula_functions_view.addItems(self._formula_function_items)
        self._formula_functions_view.itemDoubleClicked.connect(
            lambda item: self._formula_function_double_clicked(
                user_data=item.data(Qt.UserRole)), receiver=self)

        self.data_table = ReferenceDataTable(
            self._editor_panel_widget, self.view.after, self._input_error,
            height=-1, menu_parent=self.tag,
            on_import=self._import_clipboard,
            on_change=self._mark_dirty)
        self._clipboard = QClipboard()

        self.status = self.status_text("", parent=self.content)
        self.button_box([
            ("Save & Close", self._save, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ], left_actions=[
            ("Copy Selected", self._copy_table, "secondary", False),
        ], status_item=self.status)
        self._refresh_list(select_first=True)
        if self._series:
            self._load_item(self._series[0])
        else:
            self._new_input()
        self.view.after(1, self._sync_pane_geometry)
        # Native rows are populated only after the dialog has had a chance to
        # present. The hook merely ensures the deferred pass is running; it does
        # not synchronously walk the dataset.
        self.view.after(1, self.data_table.refresh_visible_page)
        self.view.after(1, self.data_table.focus_cell, 0, 0)

    def layout_dialog(self):
        if getattr(self, "_finished", False):
            return
        try:
            self.view.after(1, self._sync_pane_geometry)
        except Exception:
            pass

    def _sync_pane_geometry(self):
        if self._finished or not self.winfo_exists():
            return
        try:
            self._library_panel_widget.resize(-1, -1)
            self._editor_panel_widget.resize(-1, -1)
            self.data_table.resize(-1, -1)
            self._saved_list_view.resize(-1, -1)
        except Exception:
            pass

    def _next_default_name(self):
        used = {str(item.get("name") or "").strip().casefold() for item in self._series}
        index = 1
        while True:
            name = "Reference {}".format(index)
            if name.casefold() not in used:
                return name
            index += 1

    def _unique_import_name(self, preferred):
        base = str(preferred or "Reference").strip() or "Reference"
        used = {str(item.get("name") or "").strip().casefold() for item in self._series}
        if base.casefold() not in used:
            return base
        index = 2
        while "{} ({})".format(base, index).casefold() in used:
            index += 1
        return "{} ({})".format(base, index)

    def _input_error(self, message):
        if self.winfo_exists():
            self.set_control_value(self.status, message)

    def _mark_dirty(self, *_args):
        self._editor_dirty = True

    def _name_changed(self, *_args):
        self._mark_dirty()

    def _formula_changed(self, *_args):
        self._mark_dirty()

    def _formula_function_double_clicked(self, _sender=None, _app_data=None, user_data=None):
        """Insert a function template into the formula editor, Abaqus-style."""
        if not user_data:
            return
        _fn_name, syntax, _help = user_data
        syntax = str(syntax or "").strip()
        if not syntax:
            return
        current = str(self.control_value(self.formula_edit, "") or "")
        default = "combine(.*U1, .*RF1)"
        # Dear PyGui does not expose the text caret position for InputText.
        # Match Abaqus' quick-insert workflow as closely as possible: replace
        # an empty/default expression, otherwise append at the end.
        if not current.strip() or current.strip() == default:
            updated = syntax
        else:
            separator = "" if current.endswith((" ", "\n", "(", ",")) else "\n"
            updated = current + separator + syntax
        self.set_control_value(self.formula_edit, updated)
        self._mark_dirty()
        try:
            self.view.after(1, self.focus_control, self.formula_edit)
        except Exception:
            pass

    def _set_formula_mode(self, enabled, formula="", button_label=None):
        self._formula_mode = bool(enabled)
        self._reference_type_guard = True
        try:
            self.set_control_value(
                self.reference_type_combo,
                "Formula" if self._formula_mode else "XY Data")
        finally:
            self._reference_type_guard = False
        if self._formula_mode:
            self.data_table.setVisible(False)
            self._formula_group_widget.show()
            self.set_control_enabled(self.name_edit, True)
            self.set_control_enabled(self.save_series_button, True)
            self.set_control_value(self.save_series_button, button_label or "Save Formula")
            if formula is not None:
                self.set_control_value(self.formula_edit, str(formula or ""))
        else:
            self._formula_group_widget.hide()
            self.data_table.setVisible(True)
            self.set_control_enabled(self.name_edit, True)
            self.set_control_enabled(self.save_series_button, True)
            self.set_control_value(self.save_series_button, "Save XY")

    def _reference_type_changed(self, _sender=None, value=None, _user_data=None):
        if self._reference_type_guard or self._finished:
            return
        selected = str(value or self.control_value(self.reference_type_combo, "XY Data") or "XY Data")
        if selected == "Formula":
            if not self._open_formula_dialog():
                self._reference_type_guard = True
                try:
                    self.set_control_value(
                        self.reference_type_combo,
                        "Formula" if self._formula_mode else "XY Data")
                finally:
                    self._reference_type_guard = False
        else:
            self._new_input()

    def _series_right_clicked(self, *_args):
        if self._finished:
            return
        has_selection = self._selected() is not None
        self._series_menu.setActionEnabled("rename", has_selection)
        self._series_menu.setActionEnabled("delete", has_selection)
        point_value = QCursor.pos()
        point = (float(point_value.x()), float(point_value.y()))
        self.view.after(1, lambda: self._series_menu.popup(point, context=None))

    def _series_row_right_clicked(self, _sender=None, _value=None, name=None):
        if name:
            self._set_selected_name(str(name), notify=False)
        self._series_right_clicked()

    def _series_context_action(self, action, _context=None):
        action = str(action or "")
        if action == "rename":
            self._begin_inline_rename()
        elif action == "delete":
            self._remove_selected()

    def _open_formula_dialog(self):
        """Switch the right editor into persistent regex/formula mode.

        Reference Chart itself already runs inside the floating dialog host, so
        opening another modal QtDialog from here is unreliable.  Formula editing
        is therefore inline in the existing right-hand editor.
        """
        if self._finished:
            return False
        if self._editor_dirty:
            if self._formula_mode:
                if not self._save_formula_rule(refocus=False):
                    return False
            elif self._editing_id is not None or self.data_table.has_data():
                if not self._commit_editor(refocus=False):
                    return False

        self._editing_id = None
        self._selection_guard = True
        try:
            self._set_selected_name("", notify=False)
        finally:
            self._selection_guard = False
        self.set_control_value(self.name_edit, self._unique_import_name("Formula"))
        self._set_formula_mode(
            True, "combine(.*U1, .*RF1)", button_label="Add Formula")
        self._editor_dirty = False
        self.set_control_value(self.status, "Formula mode: define a regex rule, then Save Formula.")
        try:
            self.view.after(1, self.focus_control, self.formula_edit)
        except Exception:
            pass
        return True

    def _add_formula_series(self, series, formula=""):
        """Append validated formula results to the draft reference library."""
        try:
            incoming = [validate_reference(item) for item in list(series or [])]
        except (TypeError, ValueError, OverflowError) as exc:
            self.set_control_value(self.status, str(exc))
            return False
        if not incoming:
            self.set_control_value(self.status, "Formula produced no reference series.")
            return False

        added = []
        for item in incoming:
            item = copy.deepcopy(item)
            item["name"] = self._unique_import_name(item.get("name") or "Formula")
            # Revalidate after changing the name so all persisted fields remain
            # normalized and a fresh/valid id is retained.
            item = validate_reference(item)
            self._series.append(item)
            added.append(item)

        first = added[0]
        self._refresh_list(select_name=first["name"], select_first=True)
        self._load_item(first)
        self.set_control_value(
            self.status,
            "Added {} formula series{}. Save & Close to persist.".format(
                len(added), "" if len(added) == 1 else "es"))
        return True

    def _set_selected_name(self, name, notify=False):
        name = str(name or "")
        self._selected_name = name
        item = getattr(self, "_series_items", {}).get(name)
        self._selection_guard = True
        try:
            self._saved_list_view.setCurrentItem(item)
        finally:
            self._selection_guard = False
        if notify and name:
            self._selection_changed(value=name)

    def _series_list_clicked(self, item):
        if self._selection_guard or item is None:
            return
        name = str(item.data(Qt.UserRole) or item.text())
        self._selected_name = name
        self._selection_changed(value=name)

    def _series_list_context_menu(self, key, _point=None):
        item = self._saved_list_view.itemForKey(key)
        if item is not None:
            self._set_selected_name(
                str(item.data(Qt.UserRole) or item.text()), notify=False)
        self._series_right_clicked()

    def _series_row_selected(self, _sender=None, value=None, name=None):
        # Compatibility adapter for historical callbacks/tests.
        if self._selection_guard or not value:
            return
        self._selected_name = str(name or "")
        self._set_selected_name(self._selected_name, notify=False)
        self._selection_changed(value=self._selected_name)

    def _refresh_list(self, select_name=None, select_first=False):
        names = [item["name"] for item in self._series]
        selected = select_name if select_name in names else self._selected_name
        if selected not in names:
            selected = names[0] if names and select_first else ""

        self._saved_list_view.clear()
        self._series_selectables.clear()
        self._series_items = {}
        self._rename_editor = None
        self._rename_editor_control = None
        rename_item = None
        refreshed_items = []
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            refreshed_items.append(item)
            self._series_items[name] = item
            if name == self._rename_name:
                rename_item = item
        # Series edits/imports can refresh hundreds of rows at once; create
        # retained selectables in one pass while preserving their stable item
        # and inline-rename ownership semantics.
        self._saved_list_view.addItems(refreshed_items)

        # Native aliases are retained for compatibility with diagnostics/tests,
        # but the QListWidget owns selection and pointer routing.
        self._series_selectables = {
            name: self._saved_list_view.items.get(item.key)
            for name, item in self._series_items.items()
            if self._saved_list_view.items.get(item.key) is not None
        }

        if rename_item is not None:
            name = rename_item.text()
            self._rename_editor_control = QLineEdit(
                name, parent=self.saved_list, width=-1,
                auto_select_all=True, on_enter=True,
                callback=lambda _s, value, _u=None: self._commit_inline_rename(value))
            self._rename_editor = self._rename_editor_control.tag
            self._saved_list_view.setItemWidget(rename_item, self._rename_editor_control)
            self.enter_editors.add(self._rename_editor)
            self.view.after(1, self._focus_inline_rename)

        self._selected_name = selected
        self._selection_guard = True
        try:
            self._saved_list_view.setCurrentItem(self._series_items.get(selected))
        finally:
            self._selection_guard = False

    def _selected(self):
        name = self._selected_name
        return next((item for item in self._series if item["name"] == name), None)

    def _editing_item(self):
        if self._editing_id is None:
            return None
        return next((item for item in self._series if item["id"] == self._editing_id), None)

    def _load_item(self, item):
        if item is None:
            return
        self._editing_id = item["id"]
        self.set_control_value(self.name_edit, item["name"])
        is_formula = item.get("kind") == "formula" or bool(item.get("formula"))
        if is_formula:
            self.data_table.reset()
            self._set_formula_mode(
                True, item.get("formula") or "", button_label="Save Formula")
            self.set_control_value(self.status, "Formula rule")
        else:
            self._set_formula_mode(False)
            self.data_table.load_series([item])
        self._editor_dirty = False
        self._selection_guard = True
        try:
            self._set_selected_name(item["name"], notify=False)
        finally:
            self._selection_guard = False
        if not is_formula:
            self.view.after(1, self.data_table.focus_cell, 0, 0)

    def _selection_changed(self, _sender=None, value=None, _user_data=None):
        if self._selection_guard:
            return
        target = next((item for item in self._series if item["name"] == value), None)
        if target is None or target["id"] == self._editing_id:
            return
        # Do not silently discard a valid in-progress edit when navigating.
        if self._editor_dirty:
            committed = (self._save_formula_rule(refocus=False)
                         if self._formula_mode else
                         self._commit_editor(refocus=False))
            if not committed:
                current = self._editing_item()
                self._selection_guard = True
                try:
                    self._set_selected_name(current["name"] if current else "", notify=False)
                finally:
                    self._selection_guard = False
                return
            target = next((item for item in self._series if item["id"] == target["id"]), target)
        self._load_item(target)

    def _new_input(self):
        if self._editor_dirty:
            if self._formula_mode:
                if not self._save_formula_rule(refocus=False):
                    return
            elif self._editing_id is not None or self.data_table.has_data():
                if not self._commit_editor(refocus=False):
                    return
        self._editing_id = None
        self.data_table.reset()
        self._set_formula_mode(False)
        self.set_control_value(self.name_edit, self._next_default_name())
        self._editor_dirty = False
        self._selection_guard = True
        try:
            self._set_selected_name("", notify=False)
        finally:
            self._selection_guard = False
        self.set_control_value(self.status, "XY Data mode: paste or enter X/Y values, then Save XY.")
        self.view.after(1, self.data_table.focus_cell, 0, 0)

    def _edit_selected(self):
        """Compatibility entry point; selection now opens a series directly."""
        item = self._selected()
        if item is not None:
            self._load_item(item)

    def _begin_inline_rename(self):
        item = self._selected() or self._editing_item()
        if item is None:
            self.set_control_value(self.status, "Select a saved series to rename.")
            return False
        self._series_menu.hide()
        self._rename_name = item["name"]
        self._selected_name = item["name"]
        self._rename_outside_armed = False
        self._refresh_list(select_name=item["name"])
        self.view.after(80, self._arm_inline_rename_outside_click)
        return True

    def _focus_inline_rename(self):
        editor = self._rename_editor_control
        if editor is None or getattr(editor, "_deleted", False):
            return
        try:
            editor.setFocus()
        except Exception:
            pass

    def _arm_inline_rename_outside_click(self):
        if self._rename_name is not None:
            self._rename_outside_armed = True

    def _rename_outside_click(self, *_args):
        if self._rename_name is None or not self._rename_outside_armed:
            return
        editor = self._rename_editor_control
        if editor is not None and not getattr(editor, "_deleted", False):
            try:
                if editor.underMouse():
                    return
            except Exception:
                pass
            self.view.after(1, self._commit_inline_rename, editor.text())

    def _commit_inline_rename(self, value=None):
        old_name = self._rename_name
        if old_name is None:
            return False
        item = next((row for row in self._series if row["name"] == old_name), None)
        if item is None:
            self._cancel_inline_rename()
            return False

        if value is None and self._rename_editor_control is not None:
            try:
                value = self._rename_editor_control.text()
            except Exception:
                value = ""
        new_name = str(value or "").strip()
        if not new_name:
            self.set_control_value(self.status, "Series name cannot be empty.")
            self.view.after(1, self._focus_inline_rename)
            return False
        duplicate = next((row for row in self._series
                          if row["id"] != item["id"]
                          and str(row.get("name") or "").casefold() == new_name.casefold()), None)
        if duplicate is not None:
            self.set_control_value(self.status, "A reference with that name already exists.")
            self.view.after(1, self._focus_inline_rename)
            return False

        item["name"] = new_name
        if self._editing_id == item["id"]:
            self.set_control_value(self.name_edit, new_name)
        self.enter_editors.discard(self._rename_editor)
        self._rename_name = None
        self._rename_editor = None
        self._rename_editor_control = None
        self._rename_outside_armed = False
        self._selected_name = new_name
        self._refresh_list(select_name=new_name)
        self.set_control_value(self.status, "Renamed '{}' to '{}'. Save & Close to persist the change.".format(
            old_name, new_name))
        return True

    def _cancel_inline_rename(self):
        if self._rename_name is None:
            return False
        old_name = self._rename_name
        self.enter_editors.discard(self._rename_editor)
        self._rename_name = None
        self._rename_editor = None
        self._rename_editor_control = None
        self._rename_outside_armed = False
        self._selected_name = old_name
        self._refresh_list(select_name=old_name)
        return True

    def _rename_selected(self):
        """Compatibility alias: Rename now edits the selected row in-place."""
        return self._begin_inline_rename()

    def reject(self):
        # Explorer behaviour: Escape cancels inline rename before it can close
        # the entire Reference Chart dialog.
        if self._rename_name is not None:
            self._cancel_inline_rename()
            return
        super().reject()

    def _remove_selected(self):
        item = self._selected() or self._editing_item()
        if item is None:
            return
        removed_name = item["name"]
        self._series = [row for row in self._series if row["id"] != item["id"]]
        self._editing_id = None
        self._editor_dirty = False
        self._refresh_list(select_first=True)
        next_item = self._selected()
        if next_item is not None:
            self._load_item(next_item)
        else:
            self.data_table.reset()
            self.set_control_value(self.name_edit, self._next_default_name())
        self.set_control_value(self.status, "Deleted '{}'. Save & Close to persist the change.".format(removed_name))

    def _commit_editor(self, refocus=True):
        try:
            name = str(self.control_value(self.name_edit, "") or "").strip()
            added = self.data_table.to_series(name)
            current = [item for item in self._series if item["id"] != self._editing_id]
            if self._editing_id is not None:
                original = next(item for item in self._series if item["id"] == self._editing_id)
                added[0].update(id=original["id"], enabled=original["enabled"])
            names = [item["name"].casefold() for item in current + added]
            if len(names) != len(set(names)):
                raise ValueError("A reference with that name already exists. Choose a different name.")
            saved = added[0]
            # Preserve library order when updating; append only for a new series.
            if self._editing_id is None:
                self._series.append(saved)
            else:
                self._series = [saved if item["id"] == self._editing_id else item
                                for item in self._series]
            self._editing_id = saved["id"]
            self._editor_dirty = False
            self._refresh_list(select_name=saved["name"])
            self.set_control_value(self.status, "Series '{}' is ready to save.".format(saved["name"]))
        except (TypeError, ValueError, StopIteration) as exc:
            self.set_control_value(self.status, str(exc))
            return False
        if refocus:
            self.view.after(1, self.data_table.focus_cell, 0, 0)
        return True

    def _save_formula_rule(self, refocus=True):
        try:
            name = str(self.control_value(self.name_edit, "") or "").strip()
            formula = str(self.control_value(self.formula_edit, "") or "").strip()
            if not name:
                raise ValueError("Enter a series name.")
            saved = make_formula_reference(formula, name=name)
            current = [item for item in self._series if item["id"] != self._editing_id]
            if any(str(item.get("name") or "").casefold() == name.casefold()
                   for item in current):
                raise ValueError("A reference with that name already exists. Choose a different name.")
            if self._editing_id is not None:
                original = next((item for item in self._series
                                 if item["id"] == self._editing_id), None)
                if original is not None:
                    saved["id"] = original["id"]
                    saved["enabled"] = original.get("enabled", True)
                    self._series = [saved if item["id"] == self._editing_id else item
                                    for item in self._series]
                else:
                    self._series.append(saved)
            else:
                self._series.append(saved)
            self._editing_id = saved["id"]
            self._editor_dirty = False
            self._refresh_list(select_name=saved["name"], select_first=True)
            self._load_item(saved)
            self.set_control_value(self.status, "Formula '{}' is ready to save.".format(saved["name"]))
        except (TypeError, ValueError, StopIteration) as exc:
            self.set_control_value(self.status, str(exc))
            return False
        if refocus:
            try:
                self.view.after(1, self.focus_control, self.formula_edit)
            except Exception:
                pass
        return True

    def _save_series(self, *_args):
        if self._formula_mode:
            return self._save_formula_rule(refocus=True)
        return self._commit_editor(refocus=True)

    def _add_input(self, *_args, **_kwargs):
        """Legacy add action: commit one series, then prepare a fresh editor."""
        if not self._commit_editor(refocus=False):
            return False
        self._editing_id = None
        self.data_table.reset()
        self.set_control_value(self.name_edit, self._next_default_name())
        self._editor_dirty = False
        self._selection_guard = True
        try:
            self._set_selected_name("", notify=False)
        finally:
            self._selection_guard = False
        self.view.after(1, self.data_table.focus_cell, 0, 0)
        return True

    def _import_clipboard(self):
        if self._editor_dirty and (self._editing_id is not None or self.data_table.has_data()):
            if not self._commit_editor(refocus=False):
                return False
        text = self._clipboard.text()
        try:
            imported = parse_reference_text(text, self._next_default_name())
        except (TypeError, ValueError) as exc:
            self.set_control_value(self.status, str(exc))
            return False

        imported_ids = []
        for raw in imported:
            item = validate_reference(raw)
            item["name"] = self._unique_import_name(item["name"])
            item = validate_reference(item)
            self._series.append(item)
            imported_ids.append(item["id"])

        first = next((item for item in self._series if item["id"] == imported_ids[0]), None)
        self._refresh_list(select_name=first["name"] if first else None, select_first=True)
        if first is not None:
            self._load_item(first)
        self.set_control_value(
            self.status,
            "Imported {} series{} from clipboard.".format(
                len(imported_ids), "" if len(imported_ids) == 1 else "es"))
        return True

    def _copy_table(self):
        if self._formula_mode:
            self.set_control_value(
                self.status,
                "Copy Selected is available only in XY Data mode.")
            return False
        if not self.data_table.copy_selected_rows():
            return False
        count = len(self.data_table.selected_rows)
        self.set_control_value(
            self.status,
            "Copied {:,} selected row{} to clipboard. Paste directly into Excel.".format(
                count, "" if count == 1 else "s"))
        return True

    def _save(self):
        if self._formula_mode and self._editor_dirty:
            if not self._save_formula_rule(refocus=False):
                return
        elif self._editor_dirty or (self._editing_id is None and self.data_table.has_data()):
            if not self._commit_editor(refocus=False):
                return
        try:
            series = [validate_reference(item) for item in self._series]
        except ValueError as exc:
            self.set_control_value(self.status, str(exc))
            return
        self.finish(series)

    def finish(self, result):
        if self._finished:
            return
        self._finished = True
        try:
            self.on_result(result)
        finally:
            self.destroy()

    def _close_from_escape(self):
        self.finish(None)

    def invoke_default(self):
        if self._formula_mode:
            wrapper = self.control_wrapper(self.formula_edit)
            try:
                if wrapper is not None and wrapper.hasFocus():
                    return
            except Exception:
                pass
        if not self.data_table.owns_keyboard():
            super().invoke_default()

    def destroy(self):
        table = getattr(self, "data_table", None)
        if table is not None:
            if getattr(self, "_defer_visual_destroy", False):
                table.suspend()
            else:
                table.delete()
        super().destroy()

    def _finalize_visual_destroy(self, *_args, **_kwargs):
        table = getattr(self, "data_table", None)
        if table is not None:
            table.delete()
        super()._finalize_visual_destroy()
