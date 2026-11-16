from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import math
import os
try:
    import numpy as np
except Exception:
    np = None
from DearUIQt.gui import QPainter, QCursor, QKeyboard, QPaintLayer, QTextureRegistry, QFontMetrics
from DearUIQt.core import Qt, QItemInputBinding, QGlobalInputBinding
from DearUIQt.widgets import QApplication, QCanvas, QToolButton, QFrame, QSpacer, QLabel, QToolTip, QRetainedItem, QProgressBar
from DearUIQt import ToolWindow, QtDataGridView, QtGridRow, QtListView, QtFusionPalette, QtListItem, ColorField, QPushButton, QMenu, QAction, QtConcurrent
from DearUIQt.tooltip import TOOLTIP_DELAY, TOOLTIP_WRAP_WIDTH, tooltip_theme
from DearUIQt.themes import transparent_header_cell_theme, button_theme, status_bar_theme, status_text_theme, make_theme, ThemeSpec, ThemeTarget, ThemeColor, ThemeStyle, theme_component
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout
from DearUIQt.runtime import QGuiRuntime
from WinUx.plotdigitizer.core import AxisScale, AxisAnchor, DigitizerEngine, ExtractionSettings
from WinUx.plotdigitizer.application import SmartDetectRunner, TickCalibrationRunner, normalize_workspace_state
from WinUx.plotdigitizer.core.extraction import detect_curve_colors
from WinUx.plotdigitizer.core.axis_labels import format_axis_value, parse_axis_value_input
from WinUx.ui import FileSelector, ToolWorkspace, ToolCommandRow, style_image_canvas, style_tool_surface, item_rect, CanvasCursor
from WinUx.ui.components.toolbar import ResourceTextures, toolbar_icon_theme, toolbar_fitted_icon_theme
from WinUx.preferences.plot_digitizer import PlotDigitizerPreferences
from WinUx.plotdigitizer.ui.markers import draw_marker, draw_axis_marker, marker_metrics, cursor_hits_marker
from WinUx.plotdigitizer.ui.preview import preview_geometry
from WinUx.plotdigitizer.ui.ribbon_style import DIGITIZER_RIBBON_DISPLAY, DigitizerRibbonBar
from WinUx.plotdigitizer.ui.checklist import DigitizerCheckList, rounded_checkbox_theme
from WinUx.plotdigitizer.ui.samples_dialog import SamplesDialog

class DataController:
    """Data behavior extracted from PlotDigitizerDialog; state remains owned by the dialog."""

    def __init__(self, owner):
        self.owner = owner

    def _build_data_panel(self, panel):
        with self.owner.section('Review Data', parent=panel) as group:
            self.owner.coordinate_mode = self.owner.combo(['Chart X/Y', 'Image pixels'], parent=group, width=-1, default_value='Chart X/Y', callback=self.owner._coordinate_mode_changed)
            self.owner._data_actions = {}
            for key, label, callback in (('select_all', 'Select all', self.owner._select_all_data_points), ('deselect', 'Deselect', self.owner._clear_data_selection), ('increase', 'Increase samples', self.owner._increase_samples), ('reduce', 'Reduce samples', self.owner._reduce_samples), ('simplify', 'Simplify by error', self.owner._simplify_samples), ('delete', 'Delete selected', self.owner._delete_points), ('clear', 'Clear all points', self.owner._clear_points)):
                action = QAction(label, parent=self.owner)
                action.triggered.connect(lambda _checked=False, callback=callback: callback())
                self.owner._data_actions[key] = action
            self.owner.data_coordinate_info = self.owner.note('Showing image pixels until axes are calibrated.', parent=group, wrap=240)
            self.owner.data_summary = self.owner.note('No points in this dataset.', parent=group, wrap=240)
            self.owner.result_grid = self.owner.own_widget(QtDataGridView(group, [{'key': 'n', 'label': '#', 'width': 34, 'align': 'center'}, {'key': 'x', 'label': 'X', 'stretch': 1.0}, {'key': 'y', 'label': 'Y', 'stretch': 1.0}], height=300, after=self.owner.view.after, multiple=True, sortable=False, resizable=True, horizontal_scrollbar=False))
            self.owner.data_worksheet = self.owner.result_grid.enableSpreadsheet(first_column=1, read_only=True, on_error=self.owner._set_status)
            self.owner.data_worksheet.selectionFinished.connect(self.owner._data_selection_finished)
            self.owner._add_help(self.owner.result_grid.tag, 'Select X/Y cells, drag or Shift-click to extend, Ctrl+A/C to copy to Excel. Edit point coordinates with the point editor; the results grid is read-only.')
            self.owner.result_grid.currentChanged.connect(self.owner._point_selected)
            self.owner.result_grid.selectionChanged.connect(self.owner._data_selection_changed)
            with self.owner.disclosure('Options', parent=group) as options:
                self.owner._disclosures['reduction'] = QRetainedItem(options).parentItem()
                form = self.owner.form_layout(options, label_width=100)
                self.owner.reduction_error = self.owner.form_layout_row(form, 'Max error (px)', lambda host: self.owner.spin_float(0.5, parent=host, minimum=0.0, maximum=10.0, step=0.1, decimals=2))
                self.owner._add_help(self.owner.reduction_error, 'Maximum geometric error in image pixels. Set 0 for collinear-only reduction.')
                self.owner.export_scope = self.owner.form_layout_row(form, 'Export scope', lambda host: self.owner.combo(['All datasets', 'Active dataset'], parent=host, width=-1, default_value='All datasets', callback=lambda *_: self.owner._refresh_export_controls()))
                self.owner.export_sort = self.owner.form_layout_row(form, 'Export order', lambda host: self.owner.combo(list(self.owner.EXPORT_SORT_OPTIONS), parent=host, width=-1, default_value='Original order'))
                self.owner._add_help(self.owner.export_sort, 'Sort calibrated X or Y values in ascending order within each dataset, or keep the original point order. Does not change the data table.')
            QSpacer(0, 6, parent=group)
            self.owner._data_options_layout_binding = QItemInputBinding(self.owner._disclosures['reduction'], parent=self.owner).onClick(Qt.LeftButton, lambda *_: self.owner._schedule_data_layout()).activate()
            self.owner.export_data_button = self.owner.action('Export CSV', self.owner._choose_export_csv, parent=group, width=-1)
            self.owner._add_help(self.owner.export_data_button, 'Export calibrated X/Y data as CSV using the scope and sort options above.')
            self.owner.export_excel_button = self.owner.action('Export Excel', self.owner._choose_export_excel, parent=group, width=-1)
            self.owner._add_help(self.owner.export_excel_button, 'Export X/Y data, calibration and project metadata to .xlsx using XLPP.')

    def _refresh_data_summary(self):
        if not hasattr(self.owner, 'data_summary'):
            return
        dataset = self.owner.engine.active_dataset
        count = len(dataset.extracted_pixels) + len(dataset.manual_points)
        selected = len(self.owner.result_grid.selectedKeys())
        if count:
            text = '{} | {} points | {} selected'.format(dataset.name, count, selected)
            pixels = self.owner.control_value(self.owner.coordinate_mode) == 'Image pixels' or not self.owner.engine.calibration_ready()
            text += ' | ' + ('px' if pixels else 'X/Y')
            if dataset.locked:
                text += ' | Locked'
        else:
            text = 'No points in this dataset. Use Manual or Automatic Extraction.'
        if text != getattr(self.owner, '_data_summary_text', None):
            self.owner._data_summary_text = text
            self.owner.set_control_value(self.owner.data_summary, text)
            self.owner._schedule_data_layout()
        self.owner._data_actions['select_all'].setEnabled(count > 0)
        self.owner._data_actions['deselect'].setEnabled(selected > 0 or self.owner._selected_point is not None)

    def _select_all_data_points(self):
        self.owner.data_worksheet.command('all')
        self.owner._refresh_point_actions()

    def _clear_data_selection(self):
        self.owner._clear_point_selection()
        self.owner._refresh_point_editor()
        self.owner._redraw()

    def _refresh_dataset_list(self):
        self.owner.dataset_list.setItems([QtListItem(i, '{}  |  {} pts{}'.format(ds.name, len(ds.extracted_pixels) + len(ds.manual_points), ' [Locked]' if ds.locked else ''), ds, checked=ds.visible) for i, ds in enumerate(self.owner.engine.datasets)])
        count = len(self.owner.engine.datasets)
        row_height = self.owner.dataset_list.rowHeight()
        self.owner.dataset_list.setFixedHeight(min(4, max(1, count)) * row_height + 2)
        if self.owner.dataset_list.currentKey() != self.owner.engine.active_dataset_index:
            self.owner.dataset_list.setCurrentKey(self.owner.engine.active_dataset_index, select=True)

    def _refresh_dataset_controls(self):
        if not self.owner.winfo_exists():
            return
        ds = self.owner.engine.active_dataset
        self.owner.curve_color.setColor(ds.curve_rgb)
        self.owner._sync_pick_color(ds.curve_rgb)
        unlocked = not ds.locked
        if not unlocked and self.owner._edit_enabled:
            self.owner._set_edit_enabled(False)
        has_image = self.owner.engine.image is not None
        for control in (self.owner.pick_color_button, self.owner.find_colors_button):
            self.owner.set_control_enabled(control, unlocked and has_image)
        self.owner.ribbon.set_button_enabled('pick_color', unlocked and has_image)
        self.owner.ribbon.set_button_enabled('edit', unlocked and has_image)
        self.owner._refresh_point_actions()
        can_extract = unlocked and has_image and (ds.curve_rgb is not None) and (not self.owner._smart_runner.busy)
        self.owner.set_control_enabled(self.owner.smart_button, can_extract)
        self.owner.set_control_enabled(self.owner.extract_button, can_extract)
        self.owner.ribbon.set_button_enabled('extract', can_extract)
        self.owner.curve_color.setEnabled(unlocked and has_image)
        self.owner.set_control_enabled(self.owner.palette_combo, unlocked and has_image)
        for control, field in (('tolerance', 'tolerance'), ('continuity', 'continuity'), ('smoothing', 'smoothing'), ('stride', 'stride'), ('minimum_saturation', 'minimum_saturation'), ('max_gap', 'max_gap_columns')):
            self.owner.set_control_value(getattr(self.owner, control), getattr(ds.settings, field))
            self.owner.set_control_enabled(getattr(self.owner, control), unlocked)

    def _coordinate_mode_changed(self, *_args):
        """Refresh only the coordinate presentation for View Data."""
        self.owner._refresh_grid()

    def _refresh_grid(self):
        ds = self.owner.engine.active_dataset
        rows = []
        index = 1
        calibrated = self.owner.engine.calibration_ready()
        pixels = self.owner.control_value(self.owner.coordinate_mode) == 'Image pixels' or not calibrated
        self.owner.set_control_visible(self.owner.data_coordinate_info, not calibrated)
        for i, (px, py) in enumerate(ds.extracted_pixels):
            x, y = (px, py) if pixels else ds.extracted_data[i] if i < len(ds.extracted_data) else (None, None)
            rows.append(QtGridRow('auto:{}'.format(i), (index, self.owner._fmt(x) if pixels else self.owner._fmt_axis(x, 'x'), self.owner._fmt(y) if pixels else self.owner._fmt_axis(y, 'y'))))
            index += 1
        for i, p in enumerate(ds.manual_points):
            x, y = (p.px, p.py) if pixels else (p.x, p.y)
            rows.append(QtGridRow('manual:{}'.format(i), (index, self.owner._fmt(x) if pixels else self.owner._fmt_axis(x, 'x'), self.owner._fmt(y) if pixels else self.owner._fmt_axis(y, 'y'))))
            index += 1
        self.owner.result_grid.setRows(rows)
        self.owner._refresh_point_editor()

    def _refresh_anchor_values(self):
        cal = self.owner.engine.calibration
        self.owner._manual_bounds_axes.difference_update(self.owner.engine.auto_tick_verified_axes)
        self.owner._manual_bounds_axes.intersection_update((axis for axis in ('x', 'y') if all((getattr(cal, axis + suffix) is not None for suffix in ('1', '2')))))
        pending = {axis for axis in ('x', 'y') if axis not in self.owner.engine.auto_tick_verified_axes and (not getattr(cal, 'points_' + axis)) and all((getattr(cal, axis + suffix) is not None for suffix in ('1', '2')))}
        newly_pending = pending - self.owner._manual_bounds_axes
        self.owner._manual_bounds_axes.update(pending)
        self.owner._control_wrappers[self.owner.snap_to_axes].setChecked(cal.snap_to_axes)
        self.owner.set_control_value(self.owner.scale_x, cal.scale_x.value)
        self.owner.set_control_value(self.owner.scale_y, cal.scale_y.value)
        for key in ('x1', 'x2', 'y1', 'y2'):
            anchor = getattr(cal, key)
            editor = self.owner.anchor_value[key]
            self.owner.set_control_enabled(editor, anchor is not None)
            if key[0] in newly_pending:
                self.owner.set_control_value(editor, '')
            if key[0] not in self.owner._manual_bounds_axes:
                verified = cal.box_rect is None or key[0] in self.owner.engine.auto_tick_verified_axes or bool(getattr(cal, 'points_' + key[0]))
                self.owner.set_control_value(editor, self.owner._fmt_axis(anchor.value, key[0]) if anchor is not None and verified else '')
        self.owner._refresh_calibration_points()
        self.owner.set_control_value(self.owner.roi_info, 'Area: {}'.format(self.owner.engine.plot_rect or 'full image / calibrated bounds'))

    @staticmethod
    def _fmt(value):
        if value is None:
            return ''
        try:
            return '{:.10g}'.format(float(value))
        except Exception:
            return str(value)

    def _fmt_axis(self, value, axis_or_scale):
        if isinstance(axis_or_scale, AxisScale):
            scale = axis_or_scale
        else:
            scale = getattr(self.owner.engine.calibration, 'scale_' + str(axis_or_scale).lower())
        return format_axis_value(value, scale)

    def _dataset_selected(self, index):
        target = self.owner.dataset_list.itemData(index)
        current = self.owner._dataset_index_for_object(target)
        if current is not None:
            self.owner.engine.set_active_dataset(current)

    def _dataset_index_for_object(self, target):
        return next((index for index, dataset in enumerate(self.owner.engine.datasets) if dataset is target), None)

    def _dataset_visibility_changed(self, key, visible):
        index = self.owner._dataset_index_for_object(self.owner.dataset_list.itemData(key))
        if index is None:
            self.owner._refresh_dataset_list()
            return
        self.owner.engine.update_dataset(visible=bool(visible), dataset_index=index)

    def _dataset_context_open(self, key, position):
        target = self.owner.dataset_list.itemData(key)
        index = self.owner._dataset_index_for_object(target)
        if index is None:
            return
        self.owner.engine.set_active_dataset(index)
        self.owner._refresh_dataset_list()
        action = 'unlock' if target.locked else 'lock'
        actions = [{'label': 'Unlock' if target.locked else 'Lock', 'action': action}]
        self.owner.dataset_menu.setActions(actions)
        self.owner.dataset_menu.popupGlobal(context=target)

    def _dataset_context_action(self, action, target):
        index = self.owner._dataset_index_for_object(target)
        if index is not None and action in ('lock', 'unlock'):
            self.owner.engine.update_dataset(locked=action == 'lock', dataset_index=index)

    def _add_dataset(self):
        self.owner.engine.add_dataset()

    def _delete_dataset(self):
        try:
            self.owner.engine.remove_dataset(self.owner.engine.active_dataset_index)
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _settings(self):
        return ExtractionSettings(tolerance=int(self.owner.control_value(self.owner.tolerance)), continuity=int(self.owner.control_value(self.owner.continuity)), smoothing=int(self.owner.control_value(self.owner.smoothing)), stride=int(self.owner.control_value(self.owner.stride)), minimum_saturation=int(self.owner.control_value(self.owner.minimum_saturation)), max_gap_columns=int(self.owner.control_value(self.owner.max_gap)))

    def _scale_changed(self, *_args):
        try:
            self.owner.engine.set_axis_scale(self.owner.control_value(self.owner.scale_x), self.owner.control_value(self.owner.scale_y))
        except ValueError as exc:
            self.owner._set_status(str(exc))
            self.owner._refresh_anchor_values()

    def _detect_area(self):
        if not self.owner.engine.image:
            return self.owner._set_status('Open an image first.')
        ok = self.owner.engine.detect_plot_area()
        self.owner._set_status('Plot area detected.' if ok else 'Could not detect plot area.')

    def _auto_color(self):
        if not self.owner.engine.image:
            return self.owner._set_status('Open an image first.')
        self.owner._palette = detect_curve_colors(self.owner.engine.image, self.owner.engine.plot_roi(), int(self.owner.control_value(self.owner.minimum_saturation)))
        labels = ['#{:02X}{:02X}{:02X}'.format(*rgb) for rgb in self.owner._palette]
        self.owner.set_control_items(self.owner.palette_combo, labels or ['No colored curves found'])
        self.owner.set_control_visible(self.owner.palette_combo, len(labels) > 1)
        self.owner.set_control_value(self.owner.palette_combo, labels[0] if labels else 'No colored curves found')
        if self.owner._palette:
            try:
                self.owner._sample_pixel = None
                self.owner.engine.set_curve_color(self.owner._palette[0])
            except ValueError as exc:
                return self.owner._set_status(str(exc))
        self.owner._set_status('Found {} colors.'.format(len(self.owner._palette)) if self.owner._palette else 'No colored strokes found. Use Pick Color for a black or gray curve.')

    def _palette_selected(self, _sender, value, *_args):
        self.owner._color_changed(value)

    def _color_changed(self, value):
        try:
            text = str(value).strip().lstrip('#')
            if len(text) != 6:
                raise ValueError('Enter a curve color as #RRGGBB.')
            self.owner._sample_pixel = None
            self.owner.engine.set_curve_color(tuple((int(text[i:i + 2], 16) for i in (0, 2, 4))))
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _calibrate_area(self):
        try:
            values = []
            for key in ('x1', 'x2', 'y1', 'y2'):
                scale = getattr(self.owner.engine.calibration, 'scale_' + key[0])
                values.append(parse_axis_value_input(self.owner.control_value(self.owner.anchor_value[key]), scale))
            self.owner.engine.calibrate_plot_rect(*values)
            self.owner._set_status('Axes calibrated.')
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _undo(self):
        label = self.owner.engine.undo_text if self.owner.engine.can_undo else ''
        if self.owner.engine.can_undo:
            self.owner._cancel_history_jobs()
        if self.owner.engine.undo():
            self.owner._cancel_pick()
            self.owner._set_status('Undo: {}.'.format(label))

    def _refresh_history_commands(self):
        for key, command in getattr(self.owner, '_history_actions', {}).items():
            if not command._deleted:
                command.setEnabled(self.owner.engine.can_undo if key == 'undo' else self.owner.engine.can_redo)

    def _refresh_history_buttons(self, key, enabled):
        for button in (key, 'data_' + key):
            self.owner.ribbon.set_button_enabled(button, enabled)

    def _trigger_history_command(self, key):
        if not self.owner.winfo_exists():
            return False
        self.owner._refresh_history_commands()
        return self.owner._history_actions[key].trigger()

    def _redo(self):
        label = self.owner.engine.redo_text if self.owner.engine.can_redo else ''
        if self.owner.engine.can_redo:
            self.owner._cancel_history_jobs()
        if self.owner.engine.redo():
            self.owner._cancel_pick()
            self.owner._set_status('Redo: {}.'.format(label))

    def _cancel_history_jobs(self):
        for key, runner in (('ticks', self.owner._tick_calibration_runner), ('extract', self.owner._smart_runner)):
            if runner.busy:
                runner.cancel()
                self.owner._finish_progress(key, False)
        self.owner._region_alignment_preview = None
        self.owner._refresh_dataset_controls()

    def _extract_curve(self):
        if not self.owner.engine.image:
            return self.owner._set_status('Open an image first.')
        self.owner._show_tool('extract')
        if self.owner.engine.active_dataset.curve_rgb is None:
            return self.owner._set_status('Pick Color before extracting points.')
        self.owner._start_extraction(auto_detect=False)

    def _extraction_status(self, ok, dataset_index=None):
        if not ok:
            return self.owner._set_status('No curve points found.', details='Check the sampled color and extraction tolerance in Settings.')
        ds = self.owner.engine.active_dataset if dataset_index is None else self.owner.engine.datasets[dataset_index]
        if not self.owner.engine.calibration_ready():
            self.owner._set_status('Extracted {} points; axes not calibrated.'.format(len(ds.extracted_pixels)))
        else:
            self.owner._set_status('Extracted {} points.'.format(len(ds.extracted_data)))

    def _smart_detect(self):
        self.owner._start_extraction(auto_detect=True)

    def _start_extraction(self, *, auto_detect):
        if not self.owner.engine.image:
            return self.owner._set_status('Open an image first.')
        if self.owner.engine.active_dataset.locked:
            return self.owner._set_status('Unlock this dataset before extracting.')
        if not auto_detect and self.owner.engine.active_dataset.curve_rgb is None:
            return self.owner._set_status('Pick Color before extracting points.')
        if self.owner._smart_runner.busy:
            return
        settings = self.owner._settings()
        dataset_index = self.owner.engine.active_dataset_index
        self.owner.set_control_enabled(self.owner.smart_button, False)
        self.owner.set_control_enabled(self.owner.extract_button, False)
        self.owner.ribbon.set_button_enabled('extract', False)
        self.owner._set_status('Extracting points...')
        self.owner._begin_progress('extract', 'Extracting curve in the background...')
        try:
            started = self.owner._smart_runner.submit(settings, dataset_index, self.owner._smart_finished, auto_detect=auto_detect)
        except Exception as exc:
            started = False
            self.owner._set_status('Extraction could not start: {}'.format(exc))
        if not started:
            self.owner._finish_progress('extract', False)
            self.owner._refresh_dataset_controls()
        self.owner._refresh_workflow()

    def _smart_finished(self, result, settings, dataset_index, error):
        if not self.owner.winfo_exists():
            return
        self.owner._finish_progress('extract', not error and result is not None and (not result.error))
        self.owner._refresh_dataset_controls()
        self.owner._refresh_workflow()
        if error:
            return self.owner._set_status('Extraction stopped: {}'.format(error))
        if result is None or result.error:
            return self.owner._set_status('Extraction failed: {}'.format(result.error if result else 'Unknown error'))
        try:
            if self.owner.engine.apply_smart_detect_result(result, settings, dataset_index=dataset_index):
                self.owner._clear_point_selection()
                # Extract is an explicit request to create visible markers.  A
                # persisted display preference from an earlier session must not
                # make a successful extraction look as if it returned nothing.
                # Re-enable automatic markers, keep the Settings checkbox in
                # sync and repaint immediately; the deferred engine refresh is
                # still retained for the data grid/workflow controls.
                if not self.owner._plot_preferences.get('show_automatic_points', True):
                    updated = dict(self.owner._plot_preferences)
                    updated['show_automatic_points'] = True
                    self.owner._plot_preferences = updated
                    tag = self.owner._preference_controls.get('show_automatic_points')
                    if tag is not None:
                        self.owner._preference_refreshing = True
                        try:
                            self.owner._control_wrappers[tag].setChecked(True)
                        finally:
                            self.owner._preference_refreshing = False
                    try:
                        self.owner._plot_preference_store.save(updated)
                    except OSError:
                        # Display correctness in the current session is more
                        # important than persistence; the normal settings path
                        # will report save errors when edited explicitly.
                        pass
                self.owner._redraw()
                self.owner._extraction_status(True, dataset_index)
            else:
                self.owner._set_status('No usable curve found. Pick the stroke color and select its plot area.')
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _set_edit_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled and (self.owner.engine.active_dataset.locked or self.owner.engine.image is None):
            enabled = False
        self.owner._edit_enabled = enabled
        self.owner.ribbon.set_button_checked('edit', enabled)
        if not enabled:
            self.owner._reset_point_gesture()
            self.owner._drag_target = None
            self.owner._drag_preview = None
            self.owner._hover_point = None
        self.owner._refresh_point_actions()
        self.owner._paint_pointer()

    def _edit_mode_toggled(self, enabled):
        if enabled and self.owner.engine.active_dataset.locked:
            self.owner._set_edit_enabled(False)
            return self.owner._set_status('Unlock this dataset before editing its points.')
        if enabled and self.owner.engine.image is None:
            self.owner._set_edit_enabled(False)
            return self.owner._set_status('Open an image first.')
        if enabled:
            if self.owner._pick_mode is not None:
                self.owner._cancel_pick()
            self.owner._show_tool('extract')
            self.owner._set_edit_enabled(True)
            self.owner._set_status('Edit enabled.', quiet=True)
        else:
            self.owner._set_edit_enabled(False)
            self.owner._set_status('Edit disabled.', quiet=True)
        self.owner._redraw()

    def _toggle_edit_mode(self):
        self.owner._edit_mode_toggled(not self.owner._edit_enabled)

    def _reset_point_gesture(self):
        self.owner._point_press = self.owner._rubberband_end = None
        self.owner._rubberband_active = False
        self.owner._rubberband_base = set()

    def _select_canvas_points(self, keys):
        """Update selection without focusing the hidden Data-page table."""
        self.owner.result_grid.selected = set(keys)
        current = next(iter(keys)) if len(keys) == 1 else None
        self.owner.result_grid.current = self.owner.result_grid.anchor = current
        self.owner._selected_point = self.owner._key_point(current)
        self.owner.data_worksheet.reset_selection()
        if current is not None:
            row = self.owner._point_keys().index(self.owner._selected_point)
            self.owner.data_worksheet.select_range((row, 0), (row, 1), focus=False)
        self.owner._focus_canvas_keyboard()
        self.owner._refresh_point_editor()
        self.owner._redraw()

    def _finish_point_gesture(self, point):
        start, active, base = (self.owner._point_press, self.owner._rubberband_active, self.owner._rubberband_base)
        if start is None:
            return
        scale = max(0.001, self.owner._fit_scale * self.owner._zoom)
        active = active or max((abs(point[i] - start[i]) for i in (0, 1))) * scale >= 4
        self.owner._reset_point_gesture()
        if not self.owner._edit_enabled or self.owner.engine.active_dataset.locked:
            return self.owner._redraw()
        if active:
            left, right = sorted((start[0], point[0]))
            top, bottom = sorted((start[1], point[1]))
            keys = set(base)
            ds = self.owner.engine.active_dataset
            if ds.visible:
                for source, points in (('auto', ds.extracted_pixels), ('manual', [(p.px, p.py) for p in ds.manual_points])):
                    if self.owner._marker_visible(source):
                        keys.update(('{}:{}'.format(source, index) for index, (x, y) in enumerate(points) if left <= x <= right and top <= y <= bottom))
            self.owner._select_canvas_points(keys)
            self.owner._set_status('{} points selected.'.format(len(keys)), quiet=True)
        else:
            try:
                self.owner.engine.add_manual_point(*start)
                index = len(self.owner.engine.active_dataset.manual_points) - 1
                self.owner._refresh_grid()
                self.owner._select_canvas_points({'manual:{}'.format(index)})
                self.owner._set_status('Point added.', quiet=True)
            except ValueError as exc:
                self.owner._set_status(str(exc))

    def _clear_point_selection(self):
        self.owner._selected_point = None
        worksheet = getattr(self.owner, 'data_worksheet', None)
        if worksheet is not None:
            worksheet.reset_selection()
        if hasattr(self.owner, 'result_grid'):
            self.owner.result_grid.current = None
            self.owner.result_grid.anchor = None
            self.owner.result_grid.clearSelection()

    @staticmethod
    def _key_point(key):
        if not key:
            return None
        source, index = str(key).split(':', 1)
        return (source, int(index))

    def _point_selected(self, key):
        """Track the grid current row without changing the active workflow page.

        QtDataGridView can re-emit ``currentChanged`` while its rows are being
        rebound (for example when the Chart X/Y coordinate combobox refreshes
        the presentation).  Treating that signal as navigation made innocuous
        data-view interactions jump from Review Data to Extract Curve.  Grid
        selection is presentation state only; explicit canvas/edit commands
        are responsible for workflow navigation.
        """
        self.owner._selected_point = self.owner._key_point(key)
        if self.owner.data_worksheet.isDragging():
            return
        if self.owner._selected_point is not None and self.owner._active_tool == 'data':
            self.owner.result_grid.setFocus()
        self.owner._refresh_point_editor()
        self.owner._redraw()

    def _data_selection_changed(self, *_args):
        if not self.owner.data_worksheet.isDragging():
            self.owner._refresh_point_editor()

    def _data_selection_finished(self, *_args):
        self.owner._refresh_point_editor()
        self.owner._redraw()

    def _point_keys(self):
        dataset = self.owner.engine.active_dataset
        return [('auto', index) for index in range(len(dataset.extracted_pixels))] + [('manual', index) for index in range(len(dataset.manual_points))]

    def _navigate_point(self, step):
        keys = self.owner._point_keys()
        if not keys or step not in (-1, 1):
            return False
        if self.owner._selected_point in keys:
            position = keys.index(self.owner._selected_point) + step
            if not 0 <= position < len(keys):
                return False
        else:
            position = 0 if step == 1 else len(keys) - 1
        if self.owner._pick_mode is not None or self.owner._calibration_draft is not None:
            self.owner._cancel_pick()
        key = keys[position]
        if self.owner.engine.image is not None:
            px, py = self.owner.engine.point_pixels(*key)
            x, y = self.owner._image_to_canvas(px, py)
            _, (width, height) = self.owner._canvas_rect()
            if not (0 <= x < width and 0 <= y < height):
                scale = self.owner._fit_scale * self.owner._zoom
                self.owner._pan = [width / 2 - px * scale, height / 2 - py * scale]
                self.owner._auto_fit = False
        text_key = '{}:{}'.format(*key)
        if not any((row_key == text_key for row_key, _values in self.owner.result_grid.rows)):
            self.owner._refresh_grid()
        self.owner.result_grid.setCurrentKey(text_key, select=True)
        row = next((index for index, (row_key, _values) in enumerate(self.owner.result_grid.rows) if row_key == text_key))
        self.owner.data_worksheet.select_range((row, 0), (row, 1), focus=False)
        if self.owner._selected_point != key:
            self.owner._point_selected(text_key)
        return True

    def _refresh_point_editor(self):
        if not hasattr(self.owner, 'point_info'):
            return
        if self.owner.data_worksheet.isDragging():
            return
        self.owner._schedule_data_layout()
        self.owner._refresh_point_actions()
        selected = self.owner._selected_point
        keys = self.owner._point_keys()
        show = bool(keys) and (self.owner._active_tool == 'extract' or (self.owner._active_tool == 'data' and selected is not None and (len(self.owner.result_grid.selectedKeys()) <= 1)))
        self.owner.set_control_visible(self.owner.point_editor_container, show)
        if selected is None:
            self.owner.set_control_visible(self.owner.point_fields, False)
            count = len(self.owner.result_grid.selectedKeys())
            self.owner.set_control_value(self.owner.point_info, '{} points selected'.format(count) if count > 1 else 'Select a point')
            self.owner.set_control_enabled(self.owner.previous_point_button, bool(keys))
            self.owner.set_control_enabled(self.owner.next_point_button, bool(keys))
            self.owner._control_wrappers[self.owner.point_x].setText('')
            self.owner._control_wrappers[self.owner.point_y].setText('')
            return
        try:
            px, py = self.owner.engine.point_pixels(*selected)
        except (IndexError, ValueError):
            self.owner._selected_point = None
            return self.owner._refresh_point_editor()
        self.owner.set_control_visible(self.owner.point_fields, True)
        in_pixels = self.owner.control_value(self.owner.coordinate_mode) == 'Image pixels' or not self.owner.engine.calibration_ready()
        x, y = (px, py) if in_pixels else self.owner.engine.pixel_to_data(px, py)
        editable = not self.owner.engine.active_dataset.locked
        identity = hash((selected, in_pixels, x, y, editable))
        for field, value, label in ((self.owner.point_x, x, 'x'), (self.owner.point_y, y, 'y')):
            QRetainedItem(field).configure(use_internal_label=False, label='##{}_point_{}_{}'.format(self.owner.tag, label, identity))
            formatted = self.owner._fmt(value) if in_pixels else self.owner._fmt_axis(value, label)
            self.owner._control_wrappers[field].setText(formatted)
            if self.owner.control_value(field) != formatted:
                self.owner.set_control_value(field, formatted)
            self.owner.set_control_enabled(field, editable)
        position = keys.index(selected)
        self.owner.set_control_value(self.owner.point_info, '{} {}/{} | {}'.format('Auto' if selected[0] == 'auto' else 'Manual', position + 1, len(keys), 'px' if in_pixels else 'X/Y'))
        self.owner.set_control_enabled(self.owner.previous_point_button, position > 0)
        self.owner.set_control_enabled(self.owner.next_point_button, position < len(keys) - 1)

    def _apply_point(self):
        if self.owner._selected_point is None:
            return self.owner._set_status('Select a point first.')
        try:
            in_pixels = self.owner.control_value(self.owner.coordinate_mode) == 'Image pixels' or not self.owner.engine.calibration_ready()
            if in_pixels:
                x, y = (float(self.owner.control_value(self.owner.point_x)), float(self.owner.control_value(self.owner.point_y)))
            else:
                x = parse_axis_value_input(self.owner.control_value(self.owner.point_x), self.owner.engine.calibration.scale_x)
                y = parse_axis_value_input(self.owner.control_value(self.owner.point_y), self.owner.engine.calibration.scale_y)
            if in_pixels:
                self.owner.engine.move_point(*self.owner._selected_point, x, y)
            else:
                self.owner.engine.set_point_values(*self.owner._selected_point, x, y)
            self.owner._set_status('Point updated.', quiet=True)
        except (ValueError, IndexError) as exc:
            self.owner._set_status(str(exc))

    def _delete_selected_canvas_points(self):
        if not self.owner._edit_enabled:
            return self.owner._set_status('Select points in Edit mode first.')
        self.owner._delete_points()

    def _delete_points(self):
        points = [self.owner._key_point(key) for key in self.owner.result_grid.selectedKeys()]
        if not points and self.owner._selected_point is not None:
            points = [self.owner._selected_point]
        if not points:
            return self.owner._set_status('Select points first.')
        try:
            self.owner._reset_point_gesture()
            self.owner._drag_target = self.owner._drag_preview = None
            self.owner.engine.remove_points(points)
            self.owner._clear_point_selection()
            self.owner._refresh_point_actions()
            self.owner._set_status('Deleted {} points.'.format(len(points)))
        except (ValueError, IndexError) as exc:
            self.owner._set_status(str(exc))

    def _clear_points(self):
        try:
            self.owner.engine.clear_points()
            self.owner._clear_point_selection()
            self.owner._set_status('Dataset cleared.')
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _request_clean(self, mode):
        if mode not in ('project', 'markers'):
            raise ValueError('Unknown clean operation.')
        if getattr(self.owner, '_closed', False):
            return
        if getattr(self.owner, '_clean_confirmation_pending', False):
            dialog = getattr(self.owner, '_clean_confirmation_dialog', None)
            if dialog is not None:
                dialog.lift()
            return
        self.owner._clean_confirmation_pending = True
        self.owner._clean_confirmation_dialog = None
        title = 'New Project' if mode == 'project' else 'Clear All Markers'
        message = 'Remove the image, all datasets, axis calibration and plot area from this project?\n\nUnsaved changes will be lost. This cannot be undone. Saved files are not deleted.' if mode == 'project' else 'Remove all data points (including locked datasets), axis calibration and plot area?\n\nThe image and dataset settings will be kept. Ctrl+Z restores the markers.'

        def finished(confirmed):
            self.owner._clean_confirmation_pending = False
            self.owner._clean_confirmation_dialog = None
            if not confirmed or getattr(self.owner, '_closed', False):
                return
            self.owner._image_load_generation += 1
            self.owner._project_load_generation += 1
            future = self.owner._image_load_future
            if future is not None:
                future.cancel()
            self.owner._cancel_pick()
            self.owner._display_axis_ticks = None
            self.owner._selected_calibration_point = None
            if mode == 'project':
                self.owner._project_path = None
                self.owner.engine.clean_project()
                if self.owner._texture_tag is not None:
                    self.owner._texture_tag.delete()
                    self.owner._texture_tag = None
            else:
                self.owner.engine.clean_markers()
            self.owner._refresh_all()
            self.owner._set_status('Project cleared.' if mode == 'project' else 'Markers cleared.')
        try:
            options = dict(primary_text=title, secondary_text='Cancel', intent='warning', parent=self.owner)
            confirm = getattr(self.owner.view, 'confirm_action_async', None)
            if callable(confirm):
                dialog = confirm(title, message, finished, **options)
            else:
                from WinUx.dialogs.blocking_form import BlockingDialog
                dialog = BlockingDialog(self.owner.view, title, message, 'confirm', on_result=finished, **options)
                dialog.lift()
            if self.owner._clean_confirmation_pending:
                self.owner._clean_confirmation_dialog = dialog
        except Exception:
            self.owner._clean_confirmation_pending = False
            self.owner._clean_confirmation_dialog = None
            raise

    def _open_sample_count_dialog(self, mode):
        return self.owner._open_samples_dialog(mode)

    def _open_samples_dialog(self, mode='count'):
        if self.owner._smart_runner.busy:
            return self.owner._set_status('Wait for extraction to finish before changing samples.')
        ds = self.owner.engine.active_dataset
        if ds.locked:
            return self.owner._set_status('Unlock this dataset before changing its samples.')
        current = len(ds.extracted_pixels) + len(ds.manual_points)
        if current < 2:
            return self.owner._set_status('Add at least 2 points before changing samples.')
        existing = getattr(self.owner, '_sample_count_dialog', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return existing
        revision = self.owner.engine.revision

        def completed(settings):
            self.owner._sample_count_dialog = None
            if settings is None or not self.owner.winfo_exists():
                return
            if self.owner.engine.active_dataset is not ds or self.owner.engine.revision != revision:
                return self.owner._set_status('Dataset changed. Reopen Resample to use the latest points.')
            if settings['mode'] == 'simplify':
                error = settings['max_error']
                self.owner._control_wrappers[self.owner.reduction_error].setValue(error)
                self.owner._apply_sample_simplification(error)
            else:
                target = settings['target']
                self.owner._apply_sample_count('increase' if target >= current else 'reduce', current, target)
        dialog = self.owner.own_dialog(SamplesDialog(self.owner.view, current, mode=mode, max_error=float(self.owner.control_value(self.owner.reduction_error)), on_result=completed, parent=self.owner))
        self.owner._sample_count_dialog = dialog
        dialog.lift()
        return dialog

    def _apply_sample_count(self, mode, before, target):
        try:
            if mode == 'increase':
                added = self.owner.engine.increase_samples(target_count=target)
                if added:
                    self.owner._cancel_pick()
                    self.owner._clear_point_selection()
                    self.owner._refresh_point_editor()
                    self.owner._set_status('Samples increased: {} -> {}.'.format(before, before + added))
                else:
                    self.owner._set_status('Sample count stayed at {}.'.format(before))
                return
            removed = self.owner.engine.reduce_sample_count(target_count=target)
            after = before - removed
            if removed:
                self.owner._cancel_pick()
                self.owner._clear_point_selection()
                self.owner._refresh_point_editor()
                if after == target:
                    self.owner._set_status('Samples reduced: {} -> {}.'.format(before, after))
                else:
                    self.owner._set_status('Samples reduced: {} -> {} (target {}).'.format(before, after, target))
            else:
                self.owner._set_status('Sample count stayed at {}.'.format(before))
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _increase_samples(self):
        return self.owner._open_sample_count_dialog('increase')

    def _reduce_samples(self):
        return self.owner._open_sample_count_dialog('reduce')

    def _simplify_samples(self):
        return self.owner._open_samples_dialog('simplify')

    def _apply_sample_simplification(self, max_error):
        if self.owner._smart_runner.busy:
            return self.owner._set_status('Wait for extraction to finish before simplifying samples.')
        ds = self.owner.engine.active_dataset
        before = len(ds.extracted_pixels) + len(ds.manual_points)
        try:
            removed = self.owner.engine.reduce_samples(max_error)
            if removed:
                self.owner._cancel_pick()
                self.owner._clear_point_selection()
                self.owner._refresh_point_editor()
                self.owner._set_status('Samples simplified: {} -> {}.'.format(before, before - removed))
            else:
                self.owner._set_status('No redundant samples found at this error tolerance.')
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _smooth_curve(self):
        if self.owner._smart_runner.busy:
            return self.owner._set_status('Wait for extraction to finish before smoothing the curve.')
        ds = self.owner.engine.active_dataset
        count = len(ds.extracted_pixels) + len(ds.manual_points)
        if count < 3:
            return self.owner._set_status('Add at least 3 points before smoothing the curve.')
        try:
            moved = self.owner.engine.smooth_curve()
            if moved:
                self.owner._cancel_pick()
                self.owner._clear_point_selection()
                self.owner._refresh_point_editor()
                self.owner._set_status('Curve smoothed ({} points).'.format(count))
            else:
                self.owner._set_status('Curve points are already evenly distributed along the current path.')
        except ValueError as exc:
            self.owner._set_status(str(exc))
