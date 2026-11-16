"""Formula-authoring behavior for Reference Chart."""
from __future__ import annotations

import copy
import sys

from DearUIQt.core import Qt

from ...services.reference_charts import (
    make_formula_reference, generate_reference_ur_rf, normalize_reference_formula,
    validate_reference)
from .formula_catalog import DEFAULT_FORMULA, FORMULA_INSERTIONS
from .regex_tester import RegexTesterDialog, _first_regex_pattern, _regex_test_text


def _regex_tester_type():
    """Resolve the historical Reference Chart patch point when present."""
    module = sys.modules.get("WinUx.dialogs.reference.reference_chart_form")
    candidate = getattr(module, "RegexTesterDialog", None) if module is not None else None
    return candidate or RegexTesterDialog


class ReferenceFormulaMixin:
    def _queue_formula_check(self):
        self._formula_check_generation += 1
        generation = self._formula_check_generation
        self.view.after(350, self._check_formula_feedback, generation)

    def _check_formula_feedback(self, generation):
        if (self._finished or not self._formula_mode or
                generation != self._formula_check_generation or not self.winfo_exists()):
            return
        formula = str(self.control_value(self.formula_edit, '') or '').strip()
        if not formula:
            self._formula_feedback.setText('Enter a formula using regex("pattern").')
            return
        try:
            make_formula_reference(formula, explicit_regex=True)
        except (TypeError, ValueError) as exc:
            self._formula_feedback.setText('Syntax error: {}'.format(exc)[:180])
            return
        self._formula_feedback.setText('Syntax OK. Refresh to preview with Plot data; Save to keep the rule.')

    def _filter_formula_functions(self, _sender=None, value=None, _user_data=None):
        query = str(value if value is not None else self.control_value(self.formula_search, '')).strip().casefold()
        matches = [item for item in self._formula_function_items
                   if query in (' '.join(item.data(Qt.UserRole)) + ' ' + item.text()).casefold()]
        self._formula_functions_view.clear()
        self._formula_functions_view.addItems(matches)
        if matches:
            self._formula_functions_view.setCurrentRow(0)
            self._set_formula_palette_help(matches[0].data(Qt.UserRole))
        else:
            self._formula_function_help.setText('No matching functions or operators.')

    def _insert_selected_function(self):
        item = self._formula_functions_view.currentItem()
        if item is not None:
            self._formula_palette_double_clicked(item)

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
        if getattr(self, '_preview_series', None):
            self._clear_preview('Edited: click Refresh to update preview.')

    def _mark_xy_data_dirty(self, *_args):
        self._sync_xy_summary()
        # Any manual cell/paste mutation defines a new source curve.  Discard
        # the previous reduction baseline so the next pass measures error from
        # the newly edited worksheet rather than from stale samples.
        self._reset_reduction_state()
        self._mark_dirty()

    def _name_changed(self, *_args):
        self._mark_dirty()

    def _formula_changed(self, *_args):
        current = str(self.control_value(self.formula_edit, '') or '')
        pending = self._pending_formula_insertion
        loading = (pending is not None and not pending.get('mark_dirty', True) and
                   current in (pending['previous'], pending['updated']))
        item = self._editing_item()
        unchanged = (item is not None and item.get('kind') == 'formula' and
                     current == normalize_reference_formula(item.get('formula', '')) and
                     self.control_value(self.name_edit, '') == item.get('name'))
        if loading or unchanged:
            # Buffered InputText callbacks can arrive after loading a series.
            # They are not new user edits of the loaded rule.
            self._queue_formula_check()
            return
        self._mark_dirty()
        self._queue_formula_check()

    def _toggle_formula_builder(self, *_args):
        self._formula_builder_open = not self._formula_builder_open
        self._formula_builder_widget.setVisible(self._formula_builder_open)
        try:
            self.control_wrapper(self.formula_builder_button).setText(
                "Hide U/RF helper" if self._formula_builder_open else "U/RF helper")
        except Exception:
            pass
        self._resize_formula_editor()

    def _resize_formula_editor(self):
        # Keep the formula editor compact so the function/operator palette gets
        # more vertical room. The helper panel needs a little more space when
        # expanded, so reduce the editor slightly further in that state.
        self.control_wrapper(self.formula_edit).resize(-1, 70 if self._formula_builder_open else 90)

    def _set_formula_palette_help(self, user_data):
        if not user_data:
            return
        _fn_name, syntax, help_text = user_data
        label = getattr(self, "_formula_function_help", None)
        if label is not None:
            try:
                label.setText("{}: {}".format(syntax, help_text))
            except Exception:
                pass

    def _formula_palette_clicked(self, item):
        if item is None or self._finished:
            return
        self._set_formula_palette_help(item.data(Qt.UserRole))

    def _formula_palette_double_clicked(self, item):
        if item is None or self._finished:
            return
        user_data = item.data(Qt.UserRole)
        self._set_formula_palette_help(user_data)
        self._formula_function_double_clicked(user_data=user_data)

    def _formula_function_double_clicked(self, _sender=None, _app_data=None, user_data=None):
        """Insert a useful expression while preserving an existing draft.

        DearPyGui does not expose a retained caret position.  For an empty
        editor, insert the palette's complete valid example so one double-click
        gives the user something immediately runnable.  For an existing draft,
        append only the requested prefix/operator fragment.
        """
        if not user_data:
            return
        fn_name, syntax, _help = user_data
        current = str(self.control_value(self.formula_edit, '') or '')
        previous = current
        pending = getattr(self, '_pending_formula_insertion', None)
        if (pending is not None and pending['editing_id'] == self._editing_id and
                pending['generation'] == self._formula_insert_generation and
                current in (pending['previous'], pending['updated'])):
            current = pending['updated']
            previous = pending['previous']
        fragment = syntax if not current.strip() else FORMULA_INSERTIONS.get(fn_name)
        if fragment is None:
            return
        updated = current + fragment
        wrapper_for = getattr(self, 'control_wrapper', None)
        editor = wrapper_for(self.formula_edit) if callable(wrapper_for) else None
        active_editor = editor is not None and editor.hasFocus()
        self.set_control_value(self.formula_edit, updated)
        self._set_formula_palette_help(user_data)
        self._mark_dirty()
        if hasattr(self, '_formula_feedback'):
            self._queue_formula_check()
        if active_editor and callable(getattr(self.view, 'after_render', None)):
            self._defer_formula_replacement(previous, updated)
            return
        try:
            self.view.after(1, self.focus_control, self.formula_edit)
        except Exception:
            pass

    def _defer_formula_replacement(self, previous, updated, mark_dirty=True):
        # Native InputText keeps a private buffer while active. A routed
        # palette click may not deactivate it in the same render turn.
        self._formula_insert_generation += 1
        generation = self._formula_insert_generation
        editing_id = self._editing_id
        self._pending_formula_insertion = {
            'generation': generation, 'editing_id': editing_id,
            'previous': previous, 'updated': updated, 'mark_dirty': mark_dirty}
        # Focusing another InputText releases the old private buffer; focusing
        # a button only changes navigation focus in ImGui. Series name is no
        # longer a visible textbox, so use the Formula search field as the
        # transient focus sink before returning focus to the formula editor.
        self.focus_control(self.formula_search)
        self.view.after_render(
            self._finish_formula_insertion, generation, editing_id, previous, updated, mark_dirty)

    def _finish_formula_insertion(self, generation, editing_id, previous, updated, mark_dirty=True):
        if (self._finished or not self._formula_mode or not self.winfo_exists() or
                generation != self._formula_insert_generation or self._editing_id != editing_id):
            return
        if str(self.control_value(self.formula_edit, '') or '') not in (previous, updated):
            # A newer user edit wins over the pending insertion.
            self._pending_formula_insertion = None
            return
        self.set_control_value(self.formula_edit, updated)
        self._pending_formula_insertion = None
        if mark_dirty:
            self._mark_dirty()
        self._queue_formula_check()
        self.view.after_render(self._refocus_formula_after_insert, generation, editing_id)

    def _refocus_formula_after_insert(self, generation, editing_id):
        if (not self._finished and self._formula_mode and self.winfo_exists() and
                generation == self._formula_insert_generation and self._editing_id == editing_id):
            self.focus_control(self.formula_edit)

    def _open_regex_tester(self, *_args):
        """Open a parent-owned regex workbench seeded from the current formula."""
        if self._finished:
            return False
        formula = str(self.control_value(self.formula_edit, "") or "")
        pattern = _first_regex_pattern(formula) or ".*U3.*"
        sample_text = _regex_test_text(self._history_outputs)

        current = getattr(self, "_regex_tester_dialog", None)
        if current is not None:
            try:
                if current.winfo_exists():
                    self.set_control_value(current.pattern_edit, pattern)
                    if sample_text and not str(self.control_value(current.text_edit, "") or "").strip():
                        self.set_control_value(current.text_edit, sample_text)
                    current.show()
                    current.activateWindow()
                    return True
            except Exception:
                pass

        dialog = _regex_tester_type()(
            self.view, pattern=pattern, text=sample_text, parent=self)
        self._regex_tester_dialog = self.own_dialog(dialog)
        return True

    def _validate_formula(self, *_args):
        formula = str(self.control_value(self.formula_edit, "") or "").strip()
        try:
            make_formula_reference(formula, explicit_regex=True)
        except (TypeError, ValueError) as exc:
            self.set_control_value(self.status, "Formula error: {}".format(exc))
            return False
        self.set_control_value(self.status, "Formula syntax is valid. Click Save to keep this rule.")
        try:
            self.view.after(1, self.focus_control, self.formula_edit)
        except Exception:
            pass
        return True

    def _generate_ur_rf(self):
        selected = str(self.control_value(self.generate_direction, "U3 / RF3"))
        try:
            axes = {"U1 / RF1": (1,), "U2 / RF2": (2,), "U3 / RF3": (3,),
                    "All directions": (1, 2, 3)}[selected]
        except KeyError as exc:
            self.set_control_value(self.status, "Choose U1/RF1, U2/RF2, U3/RF3 or All directions.")
            return False

        antialiasing = bool(self.control_value(self.generate_antialiasing, True))
        reverse_u = bool(self.control_value(self.generate_reverse_u, False))
        reverse_rf = bool(self.control_value(self.generate_reverse_rf, True))
        fallback_unscoped = False
        try:
            rules = generate_reference_ur_rf(
                self._history_outputs, directions=axes,
                antialiasing=antialiasing,
                reverse_u=reverse_u,
                reverse_rf=reverse_rf)
        except ValueError as exc:
            # The helper is also a formula *builder*.  An active Plot may not
            # contain the requested component/filter yet (for example U1/RF1
            # while only U3/RF3 is loaded).  In that case still generate the
            # portable regex template instead of making the Generate button
            # appear to do nothing.  Keep ambiguity/invalid-data errors strict.
            if self._history_outputs and str(exc).startswith("No same-direction U/RF "):
                try:
                    rules = generate_reference_ur_rf(
                        None, directions=axes,
                        antialiasing=antialiasing,
                        reverse_u=reverse_u,
                        reverse_rf=reverse_rf)
                    fallback_unscoped = True
                except (TypeError, ValueError) as fallback_exc:
                    self.set_control_value(self.status, str(fallback_exc))
                    return False
            else:
                self.set_control_value(self.status, str(exc))
                return False
        except TypeError as exc:
            self.set_control_value(self.status, str(exc))
            return False

        # A blank Formula draft is exactly the state in which U/RF helper is
        # normally used.  Do not try to validate/save that blank draft before
        # generation; doing so used to abort here and left the editor empty.
        current_formula = ""
        if self._formula_mode:
            current_formula = str(self.control_value(self.formula_edit, "") or "").strip()
        blank_formula_draft = self._formula_mode and not current_formula
        if self._editor_dirty and not blank_formula_draft and not (
                self._save_formula_rule(refocus=False) if self._formula_mode
                else self._commit_editor(refocus=False)):
            return False

        existing = {normalize_reference_formula(item['formula'], canonical=True): item
                    for item in self._series if item.get('formula')}
        fresh = [rule for rule in rules if normalize_reference_formula(rule['formula'], canonical=True) not in existing]
        if not fresh:
            item = existing[normalize_reference_formula(rules[0]['formula'], canonical=True)]
            self._refresh_list(select_name=item["name"])
            self._load_item(item)
            self.set_control_value(self.status, "These U/RF formulas already exist; loaded the existing formula.")
            return True
        if not self._add_formula_series(fresh):
            return False
        if fallback_unscoped:
            scope = "unscoped template; requested pair is not available in the active Plot"
        else:
            scope = "Plot step/region scoped" if self._history_outputs else "unscoped; no active Plot"
        self.set_control_value(self.status, "Generated {} rules ({}). Click Save to persist.".format(len(fresh), scope))
        return True

    def _set_formula_mode(self, enabled, formula="", button_label=None):
        superseded = self._pending_formula_insertion
        self._formula_insert_generation += 1
        self._pending_formula_insertion = None
        if hasattr(self, '_preview_message'):
            self._clear_preview()
        self._formula_mode = bool(enabled)
        self._formula_check_generation += 1
        if self._formula_mode:
            self._queue_formula_check()
        self._reference_type_guard = True
        try:
            self.set_control_value(
                self.reference_type_combo,
                "Formula" if self._formula_mode else "XY Data")
        finally:
            self._reference_type_guard = False
        if self._formula_mode:
            self._editor_header.hide()
            self.data_table.setVisible(False)
            self._formula_group_widget.show()
            self.set_control_enabled(self.name_edit, True)
            if formula is not None:
                previous = str(self.control_value(self.formula_edit, '') or '')
                if superseded is not None and previous in (superseded['previous'], superseded['updated']):
                    previous = superseded['previous']
                updated = normalize_reference_formula(formula) if formula else ''
                active_editor = self.control_wrapper(self.formula_edit).hasFocus()
                self.set_control_value(self.formula_edit, updated)
                if active_editor and previous != updated:
                    self._defer_formula_replacement(previous, updated, mark_dirty=False)
        else:
            self._editor_header.show()
            self._formula_group_widget.hide()
            self.data_table.setVisible(True)
            self.set_control_enabled(self.name_edit, True)
        self._update_size_constraints(force_resize=False)

    def _reference_type_changed(self, _sender=None, value=None, _user_data=None):
        if self._reference_type_guard or self._finished:
            return
        selected = str(value or self.control_value(self.reference_type_combo, "XY Data") or "XY Data")
        draft = self._editing_item()
        if draft is not None and draft.get('_draft') and not self.data_table.has_data():
            # A newly listed placeholder is one series, not a second hidden
            # draft when the user chooses its reference type.
            formula_mode = selected == 'Formula'
            draft['kind'] = 'formula' if formula_mode else 'xy'
            draft['formula'] = DEFAULT_FORMULA if formula_mode else ''
            self._set_formula_mode(formula_mode, draft['formula'])
            self._editor_dirty = formula_mode
            return
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
            True, DEFAULT_FORMULA, button_label="Add Formula")
        self._editor_dirty = False
        self.set_control_value(self.status, "Formula mode: define a regex rule, then click Save.")
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
            "Added {} formula series{}. Click Save to persist.".format(
                len(added), "" if len(added) == 1 else "es"))
        return True
