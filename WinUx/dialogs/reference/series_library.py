"""Series-library selection, rename, edit, import and save behavior."""
from __future__ import annotations

import uuid

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor
from DearUIQt.widgets import QLineEdit
from DearUIQt.modelview import QListWidgetItem

from ...services.reference_charts import (
    make_formula_reference, parse_reference_text, validate_reference)


class ReferenceSeriesLibraryMixin:
    def _series_right_clicked(self, *_args):
        if self._finished:
            return
        has_selection = self._selected() is not None
        self._series_menu.setActionEnabled("rename", has_selection)
        self._series_menu.setActionEnabled("delete", has_selection)
        point_value = QCursor.screenPos()
        point = (float(point_value.x()), float(point_value.y()))
        self.view.after(1, lambda: self._series_menu.popupGlobal(point, context=None))

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
        self.set_control_enabled(self.delete_series_button, bool(names) and not self._delete_in_progress)
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
        self._reset_reduction_state()
        self._clear_preview()
        self._editing_id = item["id"]
        self.set_control_value(self.name_edit, item["name"])
        is_formula = item.get("kind") == "formula" or bool(item.get("formula"))
        if is_formula:
            self.data_table.reset()
            self._sync_xy_summary(0)
            self._set_formula_mode(
                True, item.get("formula") or "", button_label="Save Formula")
            self.set_control_value(self.status, "Formula rule")
        else:
            self._set_formula_mode(False)
            self.data_table.load_series([item])
            self._sync_xy_summary(len(item.get('points') or []))
            self.set_control_value(self.status, 'XY Data | {:,} points'.format(len(item.get('points') or [])))
        self._editor_dirty = False
        self._selection_guard = True
        try:
            self._set_selected_name(item["name"], notify=False)
        finally:
            self._selection_guard = False
        if not is_formula:
            if item.get('points'):
                self._render_preview([item])
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

    def _new_series(self):
        """Create a visible, selected draft immediately; validate on Save."""
        if not self._new_input():
            # An invalid in-progress edit prevented changing the editor.
            return
        name = str(self.control_value(self.name_edit, '') or self._next_default_name())
        draft = {'id': uuid.uuid4().hex, 'name': name, 'enabled': True,
                 'points': [], '_draft': True}
        self._series.append(draft)
        self._editing_id = draft['id']
        self._refresh_list(select_name=name)
        self.set_control_value(self.status, "New series '{}': enter XY data or choose Formula, then save.".format(name))

    def _new_input(self):
        if self._editor_dirty:
            if self._formula_mode:
                if not self._save_formula_rule(refocus=False):
                    return False
            elif self._editing_id is not None or self.data_table.has_data():
                if not self._commit_editor(refocus=False):
                    return False
        self._editing_id = None
        self.data_table.reset()
        self._sync_xy_summary(0)
        self._reset_reduction_state()
        self._set_formula_mode(False)
        self._clear_preview()
        self.set_control_value(self.name_edit, self._next_default_name())
        self._editor_dirty = False
        self._selection_guard = True
        try:
            self._set_selected_name("", notify=False)
        finally:
            self._selection_guard = False
        self.set_control_value(self.status, "XY Data mode: paste or enter X/Y values, then click Save.")
        self.view.after(1, self.data_table.focus_cell, 0, 0)
        return True

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
        self.set_control_value(self.status, "Renamed '{}' to '{}'. Click Save to persist the change.".format(
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
        if self._delete_in_progress:
            return
        item = self._selected() or self._editing_item()
        if item is None:
            return
        # Selection switches to the next series while its worksheet is being
        # repopulated. Keep this destructive transaction atomic: a duplicate
        # activation or double-click must not delete that newly selected series.
        self._delete_in_progress = True
        self._delete_generation += 1
        self.view.after(250, self._finish_delete, self._delete_generation)
        if self._rename_name is not None:
            self._cancel_inline_rename()
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
            self._set_formula_mode(False)
            self.set_control_value(self.name_edit, self._next_default_name())
        self.set_control_value(self.status, "Deleted '{}'. Click Save to persist the change.".format(removed_name))

    def _finish_delete(self, generation):
        if generation != self._delete_generation or not self.winfo_exists():
            return
        self._delete_in_progress = False
        self.set_control_enabled(self.delete_series_button, bool(self._series))

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
            saved = make_formula_reference(formula, name=name, explicit_regex=True)
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
        self._reset_reduction_state()
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
        if not self.data_table.copy_selection():
            return False
        bounds = self.data_table.selected_range
        count = bounds[2] - bounds[0] + 1 if bounds is not None else max(1, len(self.data_table.selected_rows))
        self.set_control_value(
            self.status,
            "Copied {:,} selected row{} to clipboard. Paste directly into Excel.".format(
                count, "" if count == 1 else "s"))
        return True

    def _save(self):
        if not self._formula_mode:
            # Commit the active worksheet cell before deciding whether the
            # editor is dirty; Save is now the only explicit save action.
            self.data_table._read_inputs()
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
