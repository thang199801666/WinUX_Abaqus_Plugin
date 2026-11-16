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
from DearUIQt import ToolWindow, QtDataGridView, QtGridRow, QtListView, QtFusionPalette, QtListItem, ColorField, QPushButton, QMenu, QAction, QtConcurrent, QEditTransaction
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

class CalibrationController:
    """Calibration behavior extracted from PlotDigitizerDialog; state remains owned by the dialog."""

    def __init__(self, owner):
        self.owner = owner

    def _edit_transaction(self):
        transaction = getattr(self.owner, "_edit_transaction", None)
        if transaction is None:
            transaction = QEditTransaction(parent=self.owner)
            self.owner._edit_transaction = transaction
        return transaction

    def _build_axes_panel(self, parent):
        with self.owner.section('Calibration', parent=parent) as panel:
            self.owner.snap_to_axes = self.owner.checkbox('Snap to Axes', checked=True, parent=panel)
            self.owner._control_wrappers[self.owner.snap_to_axes].setThemeProvider(lambda focused=False, disabled=False: rounded_checkbox_theme(self.owner._control_wrappers[self.owner.snap_to_axes].backend, focused=focused, compact=True))
            self.owner._control_wrappers[self.owner.snap_to_axes].toggled.connect(self.owner._axis_snapping_changed)
            self.owner._add_help(self.owner.snap_to_axes, 'Snap selected plot areas to detected axis lines. Turn off to keep the exact drawn rectangle.')
            QSpacer(0, 6, parent=panel)
            self.owner.calibration_hint = self.owner.note('', parent=panel, wrap=240)
            self.owner.set_control_visible(self.owner.calibration_hint, False)
            form = self.owner.form_layout(panel, label_width=46)
            self.owner.calibration_axis = self.owner.form_layout_row(form, 'Axis', lambda host: self.owner.combo(['X', 'Y'], parent=host, default_value='X', callback=lambda *_: self.owner._calibration_axis_changed()))
            QSpacer(0, 6, parent=panel)
            tick_commands = self.owner.own_widget(ToolCommandRow(panel, after=self.owner.view.after))
            self.owner.add_axis_point_button = self.owner.action('Add Tick', self.owner._begin_place_axis_point, parent=tick_commands.cell(0, 0), width=-1, height=26)
            self.owner.auto_detect_ticks_button = self.owner.action('Read Ticks', self.owner._reread_calibration_ticks, parent=tick_commands.cell(0, 1), width=-1, height=26)
            self.owner._add_help(self.owner.add_axis_point_button, 'Place a new tick on the image, drag it into position, then enter Value and click Set Value. Esc discards the draft.')
            self.owner._add_help(self.owner.auto_detect_ticks_button, 'Read tick values automatically in the selected plot area, or select a plot area first.')
            QSpacer(0, 6, parent=panel)
            self.owner.calibration_grid = self.owner.own_widget(QtDataGridView(panel, [{'key': 'n', 'label': 'Tick', 'width': 44}, {'key': 'pixel', 'label': 'Pixel', 'stretch': 1.0}, {'key': 'value', 'label': 'Value', 'stretch': 1.0}], height=150, after=self.owner.view.after, multiple=False, sortable=False, resizable=True, horizontal_scrollbar=False))
            self.owner.calibration_grid.currentChanged.connect(self.owner._calibration_point_selected)
            self.owner._calibration_table_help = self.owner._add_help(self.owner.calibration_grid.tag, 'Select a tick to edit it. Use Select Plot on the ribbon to select the chart and read axes; Add Tick places a draggable manual tick; enter its Value and click Set Value. Manual Calibration provides two-point bounds.')
            self.owner._selected_calibration_point = None
            self.owner._calibration_editor = self.owner.own_widget(QVBoxLayout(parent=panel, spacing=6))
            self.owner.calibration_selected_info = self.owner.note('Selected tick', parent=self.owner._calibration_editor.tag)
            values = self.owner.form_layout(self.owner._calibration_editor.tag, label_width=46)
            self.owner.calibration_point_value = self.owner.form_layout_row(values, 'Value', lambda host: self.owner.line_edit('0', parent=host, width=-1, on_enter=True, callback=lambda *_: self.owner._update_calibration_point_value()))
            commands = self.owner.own_widget(ToolCommandRow(self.owner._calibration_editor, after=self.owner.view.after))
            self.owner.update_calibration_button = self.owner.action('Set Value', self.owner._update_calibration_point_value, parent=commands.cell(0, 0), width=-1)
            self.owner.repick_calibration_button = self.owner.action('Pick Position', self.owner._repick_calibration_point, parent=commands.cell(0, 1), width=-1)
            self.owner.remove_calibration_button = self.owner.action('Delete Tick', self.owner._remove_calibration_point, parent=self.owner._calibration_editor, width=-1, height=24)
            self.owner._calibration_editor.hide()
            QSpacer(0, 8, parent=panel)
            scales = self.owner.own_widget(ToolCommandRow(panel, gap=6, after=self.owner.view.after))
            for column, axis in enumerate(('x', 'y')):
                scale_form = self.owner.form_layout(scales.cell(0, column).tag, label_width=14)
                control = self.owner.form_layout_row(scale_form, axis.upper(), lambda host: self.owner.combo([s.value for s in AxisScale], parent=host, default_value=AxisScale.LINEAR.value, callback=self.owner._scale_changed))
                setattr(self.owner, 'scale_' + axis, control)
                self.owner._add_help(control, '{} axis scale'.format(axis.upper()))
            self.owner.anchor_value = {}
            self.owner.anchor_pick_buttons = {}
            QSpacer(0, 8, parent=panel)
            with self.owner.disclosure('Manual Calibration', parent=panel) as bounds:
                self.owner._disclosures['axes'] = QRetainedItem(bounds).parentItem()
                QSpacer(0, 6, parent=bounds)
                new_value = self.owner.form_layout(bounds, label_width=60)
                self.owner.new_calibration_value = self.owner.form_layout_row(new_value, 'New value', lambda host: self.owner.line_edit('0', parent=host, width=-1, on_enter=True, callback=lambda *_: self.owner._begin_manual_calibration_point()))
                QSpacer(0, 6, parent=bounds)
                self.owner.add_calibration_button = self.owner.action('Pick tick on image', self.owner._begin_manual_calibration_point, parent=bounds, width=-1, height=28, role='primary')
                QSpacer(0, 8, parent=bounds)
                x_form = self.owner.form_layout(bounds, label_width=26)
                for key, label in (('x1', 'X1'), ('x2', 'X2')):
                    self.owner._anchor_row(x_form, key, label)
                QSpacer(0, 6, parent=bounds)
                y_form = self.owner.form_layout(bounds, label_width=26)
                for key, label in (('y1', 'Y1'), ('y2', 'Y2')):
                    self.owner._anchor_row(y_form, key, label)
                QSpacer(0, 8, parent=bounds)
                self.owner.apply_calibration_button = self.owner._icon_action('Apply Axis Values', 'apply_changes', self.owner._apply_calibration_values, parent=bounds, width=-1)
                self.owner._add_help(self.owner.apply_calibration_button, 'Applying these bounds replaces the multi-point fit with two points per axis.')
                QSpacer(0, 6, parent=bounds)
                self.owner.calibrate_area_button = self.owner._icon_action('Use Plot Edges', 'plot_area', self.owner._calibrate_area, parent=bounds, width=-1)
                self.owner._add_help(self.owner.calibrate_area_button, 'Map all four entered values to the edges of the selected plot area, replacing the tick fit.')
                QSpacer(0, 6, parent=bounds)
                self.owner.reset_axes_button = self.owner._icon_action('Reset Axes', 'reset', self.owner.engine.reset_calibration, parent=bounds, width=-1)
            self.owner._set_calibration_method(self.owner._calibration_method, cancel_pending=False)

    def _axis_snapping_changed(self, enabled):
        enabled = bool(enabled)
        if enabled == self.owner.engine.calibration.snap_to_axes:
            return
        was_busy = self.owner._tick_calibration_runner.busy
        if was_busy:
            self.owner._tick_calibration_runner.cancel()
            self.owner._region_alignment_preview = None
            self.owner._finish_progress('ticks', False)
        self.owner.engine.set_axis_snapping(enabled)
        if was_busy:
            self.owner._start_tick_calibration(self.owner.engine.plot_rect)

    def _set_calibration_method(self, method, *, cancel_pending=True):
        if method not in ('manual', 'smart'):
            raise ValueError('Unknown calibration method.')
        changed = method != self.owner._calibration_method
        if changed and cancel_pending and (self.owner._pick_mode is not None or self.owner._calibration_draft is not None):
            self.owner._cancel_pick()
        if method == 'manual' and self.owner._tick_calibration_runner.busy:
            self.owner._tick_calibration_runner.cancel()
            self.owner._region_alignment_preview = None
            self.owner._finish_progress('ticks', False)
            self.owner._set_status('Calibration cancelled.', details='Manual calibration selected; existing ticks were kept.')
            self.owner._redraw()
        self.owner._calibration_method = method
        self.owner._refresh_calibration_actions()

    def _refresh_calibration_actions(self):
        if not hasattr(self.owner, 'add_calibration_button'):
            return
        has_image = self.owner.engine.image is not None
        busy = self.owner._tick_calibration_runner.busy
        self.owner.set_control_enabled(self.owner.add_calibration_button, has_image and (not busy))
        self.owner.set_control_enabled(self.owner.new_calibration_value, has_image and (not busy))
        self.owner.set_control_enabled(self.owner.add_axis_point_button, has_image)
        self.owner.set_control_enabled(self.owner.auto_detect_ticks_button, has_image and (not busy))
        self.owner.ribbon.set_button_enabled('read_axes', has_image and (not busy))
        selected = self.owner._selected_calibration_point is not None
        self.owner._calibration_editor.setVisible(selected)
        for control in (self.owner.update_calibration_button, self.owner.repick_calibration_button, self.owner.remove_calibration_button):
            self.owner.set_control_enabled(control, selected and (not busy))
        if selected:
            axis, index = self.owner._selected_calibration_point
            self.owner.set_control_value(self.owner.calibration_selected_info, 'New {} tick: enter Value, Set Value'.format(axis.upper()) if index == 'draft' else 'Selected tick: {}{}'.format(axis.upper(), index + 1))

    def _begin_manual_calibration_point(self):
        self.owner._begin_add_calibration_point(self.owner.control_value(self.owner.new_calibration_value))

    def _reread_calibration_ticks(self):
        if self.owner.engine.image is None:
            return self.owner._set_status('Open an image first.')
        self.owner._show_tool('axes')
        self.owner._set_calibration_method('smart')
        if self.owner.engine.plot_rect is None:
            return self.owner._begin_pick('area')
        self.owner._start_tick_calibration(self.owner.engine.plot_rect)

    def _build_auto_panel(self, parent):
        self.owner.pick_color_button = self.owner.action('Pick Color', lambda: self.owner._begin_pick('curve'), parent=parent, width=-1, height=28)
        self.owner._pick_color_button_help = self.owner._add_help(self.owner.pick_color_button, 'Click here, then click a curve stroke on the image to sample its color. Esc cancels.')
        self.owner._control_wrappers[self.owner.pick_color_button].setThemeProvider(self.owner._pick_color_button_theme)
        QSpacer(0, 6, parent=parent)
        self.owner.extract_button = self.owner.action('Extract', self.owner._extract_curve, role='primary', parent=parent, width=-1, height=28)
        self.owner._add_help(self.owner.extract_button, 'Extract the sampled curve. Manual and automatic points are kept in the same dataset. Settings controls extraction options.')
        self.owner.smart_button = self.owner.extract_button

    def _sync_pick_color(self, rgb):
        color = tuple(rgb[:3]) if rgb is not None else None
        if color != self.owner._pick_color_rgb:
            previous = self.owner._pick_color_themes
            self.owner._pick_color_rgb = color
            self.owner._pick_color_themes = {}
            self.owner._control_wrappers[self.owner.pick_color_button].setThemeProvider(self.owner._pick_color_button_theme)
            for theme in previous.values():
                theme.delete()
        label = '#{:02X}{:02X}{:02X}'.format(*rgb[:3]) if rgb is not None else 'No color selected'
        self.owner.set_control_value(self.owner._pick_color_button_help, 'Pick Color: {}. Click this button, then click a curve stroke on the image. Esc cancels.'.format(label))

    def _pick_color_button_theme(self, *, focused=False, disabled=False):
        button = self.owner._control_wrappers[self.owner.pick_color_button]
        color = self.owner._pick_color_rgb
        if color is None or disabled:
            return button_theme(backend=button.backend, focused=focused, disabled=disabled)
        if focused not in self.owner._pick_color_themes:
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in (channel / 255 for channel in color)]
            luminance = sum((v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722))))
            dark_text = (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05)
            text = (0, 0, 0, 255) if dark_text else (255, 255, 255, 255)
            target = 255 if dark_text else 0

            def shade(amount):
                return tuple((round(c + (target - c) * amount) for c in color)) + (255,)
            self.owner._pick_color_themes[focused] = ThemeSpec((theme_component(ThemeTarget.PUSH_BUTTON, colors={ThemeColor.BUTTON: (*color, 255), ThemeColor.BUTTON_HOVERED: shade(0.12), ThemeColor.BUTTON_ACTIVE: shade(0.22), ThemeColor.TEXT: text, ThemeColor.BORDER: QtFusionPalette.FOCUS if focused else QtFusionPalette.BORDER}, styles={ThemeStyle.FRAME_BORDER_SIZE: 1, ThemeStyle.FRAME_ROUNDING: 3, ThemeStyle.FRAME_PADDING: (8, 3), ThemeStyle.BUTTON_TEXT_ALIGN: (0.5, 0.5)}),)).createObject(parent=self.owner)
        return self.owner._pick_color_themes[focused]

    def _build_auto_settings_panel(self, parent, *, ui=None):
        """Keep advanced controls available without crowding the workflow page."""
        ui = ui or self.owner
        with ui.section('Automatic extraction settings', parent=parent) as panel:
            self.owner.curve_color = ui.own_widget(ColorField(panel, after=self.owner.view.after))
            ui.enter_editors.add(self.owner.curve_color.editor.tag)
            self.owner.curve_color.changed.connect(self.owner._color_changed)
            self.owner.palette_combo = ui.combo(['Find image colors...'], parent=panel, default_value='Find image colors...', callback=self.owner._palette_selected)
            ui.set_control_visible(self.owner.palette_combo, False)
            tolerance_form = ui.form_layout(panel, label_width=100)
            self.owner.tolerance = ui.form_layout_row(tolerance_form, 'Tolerance', lambda host: ui.spin_int(55, parent=host, minimum=1, maximum=255, step=1, width=-1, callback=lambda _sender, value, *_: self.owner._setting_changed('tolerance', value)))
            QSpacer(0, 6, parent=panel)
            self.owner.find_colors_button = ui.action('Find Colors', self.owner._auto_color, parent=panel, width=-1)
            with ui.disclosure('Advanced', parent=panel) as advanced:
                self.owner._disclosures['advanced'] = QRetainedItem(advanced).parentItem()
                self.owner._build_extraction_options(advanced, ui=ui)

    def _build_point_editor(self, parent):
        point_editor_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        self.owner.point_editor_container = point_editor_layout.tag
        with self.owner.section('Selected point', parent=self.owner.point_editor_container) as panel:
            self.owner.point_info = self.owner.status_text('', parent=panel)
            QSpacer(0, 6, parent=panel)
            point_fields_layout = QVBoxLayout(parent=panel, spacing=0)
            self.owner.point_fields = point_fields_layout.tag
            coordinate_row = self.owner.own_widget(ToolCommandRow(self.owner.point_fields, after=self.owner.view.after))
            x_form = self.owner.form_layout(coordinate_row.cell(0, 0).tag, label_width=14)
            y_form = self.owner.form_layout(coordinate_row.cell(0, 1).tag, label_width=14)
            self.owner.point_x = self.owner.form_layout_row(x_form, 'X', lambda host: self.owner.line_edit('', parent=host, on_enter=True, callback=lambda *_: self.owner._apply_point()))
            self.owner.point_y = self.owner.form_layout_row(y_form, 'Y', lambda host: self.owner.line_edit('', parent=host, on_enter=True, callback=lambda *_: self.owner._apply_point()))
            QSpacer(0, 6, parent=panel)
            self.owner.point_navigation = self.owner.own_widget(ToolCommandRow(panel, columns=2, after=self.owner.view.after))
            self.owner.previous_point_button = self.owner.action('Previous', lambda: self.owner._navigate_point(-1), parent=self.owner.point_navigation.cell(0, 0), width=-1)
            self.owner.next_point_button = self.owner.action('Next', lambda: self.owner._navigate_point(1), parent=self.owner.point_navigation.cell(0, 1), width=-1)
            self.owner._add_help(self.owner.point_x, 'Edit X, then press Enter to update the point.')
            self.owner._add_help(self.owner.point_y, 'Edit Y, then press Enter to update the point.')
            self.owner._add_help(self.owner.previous_point_button, 'Select the previous point on the image and in the table (P).')
            self.owner._add_help(self.owner.next_point_button, 'Select the next point on the image and in the table (N).')

    def _show_tool(self, tool, *, sync_ribbon=False):
        tool = {'manual': 'extract', 'automatic': 'extract'}.get(tool, tool)
        if tool == 'settings':
            self.owner._open_settings()
            return
        if tool not in self.owner._tool_pages:
            return
        if sync_ribbon:
            self.owner.ribbon.set_active_tab('data' if tool == 'data' else 'home')
        if tool == self.owner._active_tool:
            return
        if self.owner._pick_mode is not None or self.owner._calibration_draft is not None:
            self.owner._cancel_pick()
        self.owner._active_tool = tool
        if tool != 'axes':
            self.owner._anchor_drag_target = None
            self.owner._anchor_drag_preview = None
            self.owner._hover_anchor = None
        for name, page in self.owner._tool_pages.items():
            self.owner.set_control_visible(page, name == tool)
        self.owner.active_table = self.owner.result_grid if tool == 'data' else None
        QRetainedItem(self.owner.settings_panel).setVerticalScrollValue(0)
        if self.owner.tool_list.currentKey() != tool:
            self.owner.tool_list.setCurrentKey(tool, select=True)
        self.owner._refresh_point_editor()
        self.owner._refresh_workflow_completion()

    def _workflow_check_clicked(self, key, _checked):
        # Checkbox/completion state is independent from workflow navigation.
        # Explicit DigitizerCheckList.userActivated drives page changes; this
        # signal only refreshes completion presentation.
        self.owner._refresh_workflow_completion()

    def _refresh_workflow_completion(self):
        dataset = self.owner.engine.active_dataset
        has_points = bool(dataset.extracted_pixels or dataset.manual_points)
        if self.owner._active_tool == 'data' and has_points:
            self.owner._reviewed_datasets.add(id(dataset))
        completed = (self.owner.engine.calibration_ready(), has_points, has_points and id(dataset) in self.owner._reviewed_datasets)
        self.owner.tool_list.setItems([QtListItem(key, text, checked=checked) for key, text, checked in zip(('axes', 'extract', 'data'), ('Calibrate Axes', 'Extract Curve', 'Review Data'), completed)])

    def _apply_calibration_values(self):
        try:
            values = {}
            for key, item in self.owner.anchor_value.items():
                if self.owner._manual_bounds_axes and key[0] not in self.owner._manual_bounds_axes:
                    continue
                if not str(self.owner.control_value(item)).strip():
                    raise ValueError('Enter a value for {}.'.format(key.upper()))
                scale = getattr(self.owner.engine.calibration, 'scale_' + key[0])
                values[key] = parse_axis_value_input(self.owner.control_value(item), scale)
            if self.owner._manual_bounds_axes:
                self.owner.engine.set_axis_bounds(values)
                self.owner._manual_bounds_axes.clear()
            else:
                self.owner.engine.set_anchor_values(values)
            self.owner.set_control_visible(self.owner.calibration_hint, False)
            self.owner._refresh_anchor_values()
            self.owner._set_status('Axes calibrated.')
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _build_extraction_options(self, panel, *, ui=None):
        ui = ui or self.owner
        settings_form = ui.form_layout(panel, label_width=100)
        for key, label, value, minimum, maximum in (('continuity', 'Continuity (px)', 28, 1, 250), ('smoothing', 'Smoothing', 3, 0, 30), ('stride', 'Sample stride', 1, 1, 50), ('minimum_saturation', 'Min saturation', 70, 0, 255), ('max_gap', 'Max gap', 25, 0, 500)):
            control = ui.form_layout_row(settings_form, label, lambda host, v=value, lo=minimum, hi=maximum, k=key: ui.spin_int(v, parent=host, minimum=lo, maximum=hi, step=1, width=-1, callback=lambda _sender, value, *_: self.owner._setting_changed(k, value)))
            setattr(self.owner, key, control)
        row = ui.own_widget(ToolCommandRow(panel, after=self.owner.view.after))
        self.owner.detect_area_button = ui.action('Detect Area', self.owner._detect_area, parent=row.cell(0, 0), width=-1)
        self.owner.reset_area_button = ui.action('Reset Area', lambda: self.owner.engine.set_plot_rect(None), parent=row.cell(0, 1), width=-1)
        self.owner.roi_info = ui.status_text('', parent=panel)

    def _calibration_axis_changed(self):
        if self.owner._pick_mode in ('calibration_x', 'calibration_y') or self.owner._calibration_draft is not None:
            self.owner._cancel_pick()
        self.owner._selected_calibration_point = None
        self.owner._refresh_calibration_points()

    def _calibration_point_selected(self, key, *_):
        previous = self.owner._selected_calibration_point
        self.owner._selected_calibration_point = None
        if key:
            axis, index = str(key).split(':')
            if index == 'draft':
                if self.owner._calibration_draft is not None and self.owner._calibration_draft['axis'] == axis:
                    self.owner._selected_calibration_point = (axis, 'draft')
                    if previous != self.owner._selected_calibration_point:
                        self.owner.set_control_value(self.owner.calibration_point_value, '')
                    self.owner._refresh_calibration_actions()
                return
            index = int(index)
            points = self.owner.engine.calibration_points(axis)
            if axis.upper() == self.owner.control_value(self.owner.calibration_axis) and 0 <= index < len(points):
                self.owner._selected_calibration_point = (axis, index)
                if self.owner._anchor_drag_target is None:
                    self.owner.calibration_grid.setFocus()
                self.owner.set_control_value(self.owner.calibration_point_value, self.owner._fmt_axis(points[index].value, axis))
        self.owner._refresh_calibration_actions()

    def _refresh_calibration_points(self):
        if not hasattr(self.owner, 'calibration_grid'):
            return
        axis = self.owner.control_value(self.owner.calibration_axis).lower()
        points = self.owner.engine.calibration_points(axis)
        through_ticks = getattr(self.owner.engine.calibration, 'mapping_' + axis) == 'ticks'
        fit = None if through_ticks else self.owner.engine.calibration._fit(axis)
        logarithmic = getattr(self.owner.engine.calibration, 'scale_' + axis) in (AxisScale.LOG10, AxisScale.LN)
        errors = [fit[0] * (p.px if axis == 'x' else p.py) + fit[1] - (math.log(p.value) if logarithmic else p.value) for p in points] if fit else []
        boxed = self.owner.engine.calibration.box_rect is not None
        rows = [QtGridRow(
            '{}:{}'.format(axis, i),
            (self.owner._calibration_point_display_key(axis, i),
             self.owner._fmt(p.px if axis == 'x' else p.py),
             self.owner._fmt_axis(p.value, axis)),
        ) for i, p in enumerate(points)]
        draft = self.owner._calibration_draft
        if draft is not None and draft['axis'] == axis:
            rows.append(QtGridRow(axis + ':draft', (axis.upper() + ' new', self.owner._fmt(draft['px'] if axis == 'x' else draft['py']), 'Enter value')))
        self.owner.calibration_grid.setRows(rows)
        selected = self.owner._selected_calibration_point
        if selected is not None and (selected[0] != axis or (selected[1] == 'draft' and draft is None) or (selected[1] != 'draft' and selected[1] >= len(points))):
            self.owner._selected_calibration_point = None
        self.owner._refresh_calibration_actions()
        if through_ticks:
            info = '{}: {} ticks | Piecewise mapping'.format(axis.upper(), len(points))
        elif fit is None:
            info = '{}: two-point calibration.'.format(axis.upper()) if len(points) >= 2 else '{}: {} tick(s) | Need at least 2'.format(axis.upper(), len(points))
        else:
            rmse = math.sqrt(sum((e * e for e in errors)) / len(errors))
            info = '{}: {} points | RMSE: {}{}'.format(axis.upper(), len(points), self.owner._fmt(rmse), ' (ln units)' if logarithmic else '')
        self.owner.set_control_value(self.owner._calibration_table_help, '{}\nSelect a tick to edit. Use Select Plot on the ribbon for automatic calibration; Add Tick places a draggable manual tick; enter Value and click Set Value.'.format(info))


    def _calibration_point_display_key(self, axis, index):
        """Return the same user-facing tick key used by the canvas overlay.

        Grid row keys intentionally stay tied to storage indices so editing and
        selection remain stable.  The visible ``XtN``/``YtN`` label, however,
        must follow the canvas numbering (boxed Y ticks are numbered upward
        from the origin rather than by detector/storage order).
        """
        axis = str(axis).lower()
        boxed = self.owner.engine.calibration.box_rect is not None
        key = '{}{}{}'.format(axis, 't' if boxed else '', int(index) + 1)
        return self.owner._calibration_marker_label_key(key)

    def _begin_place_axis_point(self):
        if self.owner.engine.image is None:
            return self.owner._set_status('Open an image first.')
        if self.owner._calibration_draft is not None:
            self.owner._cancel_pick()
        axis = self.owner.control_value(self.owner.calibration_axis).lower()
        self.owner._begin_pick('calibration_' + axis)
        self.owner._calibration_pick = (axis, None, None)
        self.owner._set_status('Place a new {} tick. Esc cancels.'.format(axis.upper()), details='Click the image, drag the new marker to its tick, then enter Value and click Set Value.')

    def _place_calibration_draft(self, axis, px, py):
        box = self.owner.engine.calibration.box_rect
        if box is not None:
            px, py = (px, box[3]) if axis == 'x' else (box[0], py)
        self.owner._calibration_draft = dict(axis=axis, px=px, py=py)
        self.owner._selected_calibration_point = (axis, 'draft')
        self.owner._refresh_calibration_points()
        self.owner.calibration_grid.setCurrentKey(axis + ':draft', select=True, focus=False)

    def _begin_add_calibration_point(self, value_text=None):
        if self.owner.engine.image is None:
            return self.owner._set_status('Open an image first.')
        try:
            axis = self.owner.control_value(self.owner.calibration_axis).lower()
            scale = getattr(self.owner.engine.calibration, 'scale_' + axis)
            value = parse_axis_value_input(self.owner.control_value(self.owner.calibration_point_value) if value_text is None else value_text, scale)
            if scale in (AxisScale.LOG10, AxisScale.LN) and value <= 0:
                raise ValueError('Logarithmic tick values must be > 0.')
            self.owner._begin_pick('calibration_' + axis)
            self.owner._calibration_pick = (axis, None, value)
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _update_calibration_point_value(self):
        selected = self.owner._selected_calibration_point
        if selected is None:
            return self.owner._set_status('Select a calibration tick first.')
        try:
            axis, _index = selected
            scale = getattr(self.owner.engine.calibration, 'scale_' + axis)
            value = parse_axis_value_input(self.owner.control_value(self.owner.calibration_point_value), scale)
            if selected[1] == 'draft':
                draft = self.owner._calibration_draft
                self.owner.engine.add_calibration_point(axis, draft['px'], draft['py'], value)
                index = len(self.owner.engine.calibration_points(axis)) - 1
                self.owner._calibration_draft = None
                self.owner._selected_calibration_point = (axis, index)
                self.owner._refresh_calibration_points()
                self.owner.calibration_grid.setCurrentKey('{}:{}'.format(axis, index), select=True)
                self.owner._set_status('{} tick added.'.format(axis.upper()))
                self.owner._redraw()
                return
            self.owner.engine.update_calibration_point(*selected, value=value)
            self.owner._set_status('Tick updated.')
        except (ValueError, IndexError) as exc:
            self.owner._set_status(str(exc))

    def _repick_calibration_point(self):
        selected = self.owner._selected_calibration_point
        if selected is None:
            return
        axis, index = selected
        if index == 'draft':
            self.owner._begin_pick('calibration_' + axis)
            self.owner._calibration_pick = (axis, 'draft', None)
            return
        point = self.owner.engine.calibration_points(axis)[index]
        self.owner._begin_pick('calibration_' + axis)
        self.owner._calibration_pick = (axis, index, point.value)

    def _remove_calibration_point(self):
        selected = self.owner._selected_calibration_point
        if selected is None:
            return
        if selected[1] == 'draft':
            self.owner._cancel_pick()
            return
        try:
            self.owner._selected_calibration_point = None
            self.owner.calibration_grid.current = self.owner.calibration_grid.anchor = None
            self.owner.calibration_grid.clearSelection()
            self.owner._anchor_drag_target = self.owner._anchor_drag_preview = self.owner._hover_anchor = None
            self.owner.engine.remove_calibration_point(*selected)
            self.owner._set_status('Tick removed.', details='At least two points per axis are required.')
        except (ValueError, IndexError) as exc:
            self.owner._set_status(str(exc))

    def _anchor_row(self, table, key, label):

        def build(host):
            row_layout = self.owner.own_widget(ToolCommandRow(host, column_widths=(None, 26), gap=6, after=self.owner.view.after))
            self.owner.anchor_value[key] = self.owner.line_edit('', parent=row_layout.cell(0, 0).tag, width=-1, on_enter=True, callback=lambda _sender, value, *_: self.owner._anchor_value_changed(key, value))
            self.owner.set_control_enabled(self.owner.anchor_value[key], False)
            self.owner.anchor_pick_buttons[key] = self.owner._icon_only_action('pick_anchor', lambda: self.owner._begin_pick(key), parent=row_layout.cell(0, 1), tooltip='Pick {} anchor'.format(label), button_size=26, framed=True)
        self.owner.form_layout_row(table, label, build)

    def _anchor_value_changed(self, key, value):
        if key[0] in self.owner._manual_bounds_axes:
            self.owner._set_status('Enter both {} values, then Apply Axis Values.'.format(key[0].upper()))
            return
        anchor = getattr(self.owner.engine.calibration, key)
        if anchor is None:
            return
        try:
            scale = getattr(self.owner.engine.calibration, 'scale_' + key[0])
            parsed = parse_axis_value_input(value, scale)
            self.owner.engine.set_anchor(key, anchor.px, anchor.py, parsed)
        except ValueError as exc:
            self.owner._set_status(str(exc))

    def _anchor_pick_value(self, key):
        """Return a safe temporary value for a newly picked axis anchor.

        Axis-value editors stay disabled until their pixel anchor exists, so a
        first click needs a valid seed value. Existing anchors retain their
        edited value. New linear anchors use 0/1 where possible; logarithmic
        anchors use positive 1/10 seeds. If the paired anchor already owns the
        preferred seed, choose a distinct value so partial calibration remains
        valid.
        """
        calibration = self.owner.engine.calibration
        existing = getattr(calibration, key)
        if existing is not None:
            return existing.value
        axis = key[0]
        scale = calibration.scale_x if axis == 'x' else calibration.scale_y
        linear_like = scale in (AxisScale.LINEAR, AxisScale.DATETIME)
        preferred = (1.0 if key.endswith('2') else 0.0) if linear_like else 10.0 if key.endswith('2') else 1.0
        other_key = axis + ('1' if key.endswith('2') else '2')
        other = getattr(calibration, other_key)
        if other is None or other.value != preferred:
            return preferred
        if linear_like:
            return other.value + (1.0 if key.endswith('2') else -1.0)
        return other.value * (10.0 if key.endswith('2') else 0.1)

    def _calibration_markers(self):
        boxed = self.owner.engine.calibration.box_rect is not None
        for axis in ('x', 'y'):
            points = getattr(self.owner.engine.calibration, 'points_' + axis)
            if boxed:
                corners = [getattr(self.owner.engine.calibration, axis + suffix) for suffix in ('1', '2')]
                for suffix, point in zip(('1', '2'), corners):
                    if point is not None:
                        yield (axis + suffix, point)
                for index, point in enumerate(points):
                    if any((c is not None and abs(c.px - point.px) < 1e-09 and (abs(c.py - point.py) < 1e-09) and (abs(c.value - point.value) < 1e-09) for c in corners)):
                        continue
                    yield ('{}t{}'.format(axis, index + 1), point)
                continue
            if points:
                for index, point in enumerate(points):
                    yield ('{}{}'.format(axis, index + 1), point)
            else:
                for key in (axis + '1', axis + '2'):
                    point = getattr(self.owner.engine.calibration, key)
                    if point is not None:
                        yield (key, point)
        draft = getattr(self.owner, '_calibration_draft', None)
        if draft is not None:
            yield (draft['axis'] + 'draft', AxisAnchor(draft['px'], draft['py'], 0))

    def _calibration_marker(self, key):
        if key.endswith('draft'):
            draft = self.owner._calibration_draft
            return None if draft is None else AxisAnchor(draft['px'], draft['py'], 0)
        if self.owner.engine.calibration.box_rect is not None and 't' not in key:
            return getattr(self.owner.engine.calibration, key, None)
        points = getattr(self.owner.engine.calibration, 'points_' + key[0])
        if points:
            index = int(key[2:] if key[1:2] == 't' else key[1:]) - 1
            return points[index] if 0 <= index < len(points) else None
        return getattr(self.owner.engine.calibration, key, None)

    def _calibration_point_index(self, key):
        if key.endswith('draft'):
            return 'draft'
        points = getattr(self.owner.engine.calibration, 'points_' + key[0])
        if key[1:2] == 't':
            return int(key[2:]) - 1
        if self.owner.engine.calibration.box_rect is None:
            return int(key[1:]) - 1 if points else None
        corner = getattr(self.owner.engine.calibration, key, None)
        return next((i for i, point in enumerate(points) if corner is not None and abs(point.px - corner.px) < 1e-09 and (abs(point.py - corner.py) < 1e-09) and (abs(point.value - corner.value) < 1e-09)), None)

    def _calibration_marker_label_key(self, key):
        """Return the user-facing marker name shown next to a calibration handle.

        For boxed Y-axis calibration, measured Y ticks should be numbered from
        the origin upward so the first interior tick above ``Y1`` reads
        ``Yt2``.  Internally the stored point order can differ (for example
        top-to-bottom after auto-detect), so compute the displayed ordinal from
        the actual marker position instead of reusing the raw storage index.
        """
        if key.endswith('draft'):
            return key[0].upper() + ' new'
        if key.startswith('yt') and self.owner.engine.calibration.box_rect is not None:
            point = self.owner._calibration_marker(key)
            points = list(getattr(self.owner.engine.calibration, 'points_y') or [])
            if point is not None and points:
                corners = [getattr(self.owner.engine.calibration, suffix) for suffix in ('y1', 'y2')]
                interior = [candidate for candidate in points if not any((c is not None and abs(c.px - candidate.px) < 1e-09 and (abs(c.py - candidate.py) < 1e-09) and (abs(c.value - candidate.value) < 1e-09) for c in corners))]
                if interior:
                    ordered = sorted(interior, key=lambda candidate: (-candidate.py, candidate.px, candidate.value))
                    for rank, candidate in enumerate(ordered, start=2):
                        if abs(candidate.px - point.px) < 1e-09 and abs(candidate.py - point.py) < 1e-09 and (abs(candidate.value - point.value) < 1e-09):
                            return f'Yt{rank}'
        return key[0].upper() + key[1:]

    def _nearest_anchor(self, px, py):
        """Return the nearest calibration anchor under the pointer in Calibration/Axes mode."""
        if self.owner._active_tool != 'axes' or self.owner._pick_mode is not None:
            return None
        scale = max(0.001, self.owner._fit_scale * self.owner._zoom)
        hit_radius = 10.0 / scale
        best_key, best_distance = (None, None)
        preferred_axis = self.owner.control_value(self.owner.calibration_axis).lower() if hasattr(self.owner, 'calibration_axis') else 'x'
        for key, anchor in self.owner._calibration_markers():
            distance = (anchor.px - px) ** 2 + (anchor.py - py) ** 2
            if distance <= hit_radius ** 2 and (best_distance is None or distance < best_distance or (distance == best_distance and key[0] == preferred_axis and (best_key[0] != preferred_axis))):
                best_key, best_distance = (key, distance)
        return best_key

    def _anchor_display_pixel(self, key):
        """Return the pixel used to draw an anchor, including an in-progress drag preview."""
        if self.owner._anchor_drag_target == key and self.owner._anchor_drag_preview is not None:
            return self.owner._anchor_drag_preview
        anchor = self.owner._calibration_marker(key)
        return None if anchor is None else (anchor.px, anchor.py)

    def _mouse_left(self, *_args):
        if not self.owner._mouse_in_canvas() or self.owner.engine.image is None:
            return
        mouse = QCursor.pos().toTuple()
        p = self.owner._canvas_to_image(mouse)
        if p is None:
            return
        if not (0 <= p[0] < self.owner.engine.image.width and 0 <= p[1] < self.owner.engine.image.height):
            return
        px, py = p
        self.owner._focus_canvas_keyboard()
        mode = self.owner._pick_mode
        if mode is None and self.owner._active_tool == 'axes':
            anchor_key = self.owner._nearest_anchor(px, py)
            if anchor_key is not None:
                anchor = self.owner._calibration_marker(anchor_key)
                self.owner._anchor_drag_target = anchor_key
                self.owner._anchor_drag_preview = (anchor.px, anchor.py)
                point_index = self.owner._calibration_point_index(anchor_key)
                if not str(anchor_key).endswith("draft"):
                    self._edit_transaction().begin(
                        "Move anchor",
                        context={"kind": "anchor", "key": anchor_key, "point_index": point_index,
                                 "start": (anchor.px, anchor.py)},
                        value=(anchor.px, anchor.py),
                        capture=self.owner.engine.capture_edit_snapshot,
                        restore=self.owner.engine.restore_edit_snapshot,
                    )
                self.owner._hover_anchor = anchor_key
                self.owner._hover_point = None
                if point_index is not None:
                    self.owner.set_control_value(self.owner.calibration_axis, anchor_key[0].upper())
                    self.owner._refresh_calibration_points()
                    self.owner.calibration_grid.setCurrentKey('{}:{}'.format(anchor_key[0], point_index), select=True, focus=False)
                self.owner._set_status('Moving {} anchor.'.format(anchor_key.upper()), quiet=True)
                self.owner._redraw()
                return
        if mode in ('calibration_x', 'calibration_y'):
            try:
                axis, index, value = self.owner._calibration_pick
                if value is None:
                    self.owner.set_control_value(self.owner.calibration_point_value, '')
                    self.owner._place_calibration_draft(axis, px, py)
                    self.owner._pick_mode = self.owner._calibration_pick = None
                    self.owner.set_control_visible(self.owner.calibration_hint, False)
                    self.owner._set_status('Drag the new {} tick, then enter Value and click Set Value. Esc cancels.'.format(axis.upper()))
                    self.owner._redraw()
                    return
                if index is None:
                    self.owner.engine.add_calibration_point(axis, px, py, value)
                    index = len(self.owner.engine.calibration_points(axis)) - 1
                else:
                    self.owner.engine.update_calibration_point(axis, index, px=px, py=py)
                self.owner._pick_mode = None
                self.owner._calibration_pick = None
                self.owner.set_control_visible(self.owner.calibration_hint, False)
                self.owner._refresh_calibration_points()
                self.owner.calibration_grid.setCurrentKey('{}:{}'.format(axis, index), select=True)
                self.owner._set_status('{} tick added.'.format(axis.upper()))
                self.owner._redraw()
            except (ValueError, IndexError) as exc:
                self.owner._set_status(str(exc))
        elif mode in ('x1', 'x2', 'y1', 'y2'):
            try:
                self.owner.engine.set_anchor(mode, px, py, self.owner._anchor_pick_value(mode))
                self.owner._pick_mode = None
                self.owner._calibration_sequence = []
                self.owner.set_control_visible(self.owner.calibration_hint, False)
                self.owner._set_status('{} anchor set.'.format(mode.upper()))
            except ValueError as exc:
                self.owner._set_status(str(exc))
        elif mode == 'curve':
            try:
                rgb = self.owner.engine.sample_curve_color(px, py)
                self.owner._sample_pixel = None
                self.owner._pick_mode = None
                self.owner._set_status('Color picked: #{:02X}{:02X}{:02X}.'.format(*rgb))
                self.owner._redraw()
            except ValueError as exc:
                self.owner._set_status(str(exc))
        elif mode == 'area':
            self.owner._region_press = (px, py)
            self.owner._drag_start = self.owner._region_first_corner or (px, py)
            self.owner._drag_preview = (px, py)
            self.owner._paint_pointer()
        elif mode in (None, 'edit'):
            if not self.owner._edit_enabled or self.owner.engine.active_dataset.locked:
                return
            selected = self.owner._nearest_point(px, py)
            if selected is None:
                self.owner._point_press = self.owner._rubberband_end = (px, py)
                self.owner._rubberband_active = False
                modifiers = QKeyboard.modifiers(backend=self.owner._renderer_backend())
                self.owner._rubberband_base = set(self.owner.result_grid.selectedKeys()) if modifiers & (Qt.ControlModifier | Qt.ShiftModifier) else set()
            else:
                self.owner._select_canvas_points({'{}:{}'.format(*selected)})
                if not self.owner.engine.active_dataset.locked:
                    self.owner._drag_target = selected
                    self.owner._drag_preview = self.owner.engine.point_pixels(*selected)
                    self._edit_transaction().begin(
                        "Move point",
                        context={"kind": "point", "target": tuple(selected), "start": tuple(self.owner._drag_preview)},
                        value=tuple(self.owner._drag_preview),
                        capture=self.owner.engine.capture_edit_snapshot,
                        restore=self.owner.engine.restore_edit_snapshot,
                    )
                self.owner._refresh_point_editor()
                self.owner._redraw()

    def _nearest_point(self, px, py):
        ds = self.owner.engine.active_dataset
        if not ds.visible:
            return None
        scale = max(0.001, self.owner._fit_scale * self.owner._zoom)
        closest, best = (None, None)
        for source, points in (('auto', ds.extracted_pixels), ('manual', [(p.px, p.py) for p in ds.manual_points])):
            if source == 'auto' and (not self.owner._plot_preferences['show_automatic_points']):
                continue
            if source == 'manual' and (not self.owner._plot_preferences['show_manual_points']):
                continue
            hit_radius = self.owner._marker_metrics(scale, source).hit_radius / scale
            radius2 = hit_radius ** 2
            for index, (x, y) in enumerate(points):
                distance = (x - px) ** 2 + (y - py) ** 2
                if distance <= radius2 and (best is None or distance <= best):
                    closest, best = ((source, index), distance)
        return closest

    def _mouse_left_up(self, *_args):
        if self.owner._drag_start is None and self.owner._drag_target is None and (self.owner._anchor_drag_target is None) and (self.owner._point_press is None):
            return
        if self.owner._pick_mode == 'area' and self.owner._region_press is None:
            return
        point = self.owner._canvas_to_image(QCursor.pos().toTuple())
        if point is None or self.owner.engine.image is None:
            return self.owner._cancel_pick()
        px = max(0, min(self.owner.engine.image.width - 1, point[0]))
        py = max(0, min(self.owner.engine.image.height - 1, point[1]))
        if self.owner._pick_mode == 'area' and self.owner._drag_start is not None:
            scale = max(0.001, self.owner._fit_scale * self.owner._zoom)
            moved = max((abs(value - origin) for value, origin in zip((px, py), self.owner._region_press))) * scale
            first_click = self.owner._region_first_corner is None and moved < 4
            too_small = abs(round(px) - round(self.owner._drag_start[0])) < 2 or abs(round(py) - round(self.owner._drag_start[1])) < 2
            if first_click or too_small:
                self.owner._region_first_corner = self.owner._drag_start
                self.owner._region_press = None
                self.owner._drag_preview = (px, py)
                message = 'First corner set. Click the opposite corner. Esc cancels.' if first_click else 'Choose an opposite corner to make a region at least 3 by 3 pixels. Esc cancels.'
                self.owner._set_status('Pick opposite corner.' if first_click else 'Region too small.', details=message)
                if hasattr(self.owner, 'calibration_hint'):
                    self.owner.set_control_value(self.owner.calibration_hint, message)
                self.owner._paint_pointer()
                return
        if self.owner._point_press is not None:
            return self.owner._finish_point_gesture((px, py))
        try:
            if self.owner._anchor_drag_target is not None:
                key = self.owner._anchor_drag_target
                preview = self.owner._anchor_drag_preview or (px, py)
                px = max(0, min(self.owner.engine.image.width - 1, preview[0]))
                py = max(0, min(self.owner.engine.image.height - 1, preview[1]))
                anchor = self.owner._calibration_marker(key)
                if key.endswith('draft'):
                    self.owner._place_calibration_draft(key[0], px, py)
                    self.owner._set_status('New {} tick positioned. Enter Value and click Set Value.'.format(key[0].upper()))
                else:
                    transaction = self._edit_transaction()
                    context = transaction.context() if transaction.isActive() else {}
                    start = tuple(context.get("start", (anchor.px, anchor.py)))
                    moved = abs(px - start[0]) > 1e-09 or abs(py - start[1]) > 1e-09
                    if moved and transaction.isActive():
                        before = transaction.snapshot()
                        merge_key = ("anchor", str(key)) if context.get("point_index") is None else None
                        def commit_anchor(_value):
                            return self.owner.engine.commit_live_edit(
                                "Move anchor", before, event="calibration_changed",
                                merge_id=1002 if merge_key is not None else -1,
                                merge_key=merge_key, merge_window=0.65 if merge_key is not None else 0.0)
                        transaction.commit(value=(px, py), apply=commit_anchor)
                        self.owner._set_status('{} anchor moved.'.format(key.upper()), quiet=True)
                    elif transaction.isActive():
                        transaction.commit(value=(px, py))
                        self.owner._set_status('{} anchor selected.'.format(key.upper()), quiet=True)
                    else:
                        # Compatibility fallback for callers that bypass the gesture transaction.
                        point_index = self.owner._calibration_point_index(key)
                        if point_index is not None:
                            self.owner.engine.update_calibration_point(key[0], point_index, px=px, py=py)
                        else:
                            self.owner.engine.set_anchor(key, px, py, anchor.value)
            elif self.owner._drag_start is not None:
                rect = (*self.owner._drag_start, px, py)
                self.owner.engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
                self.owner._display_axis_ticks = None
                self.owner._pick_mode = None
                self.owner._calibration_sequence = []
                self.owner._show_tool('axes')
                if hasattr(self.owner, 'calibration_hint'):
                    self.owner.set_control_visible(self.owner.calibration_hint, False)
                self.owner._start_tick_calibration(self.owner.engine.plot_rect, merge_region_history=True)
            elif self.owner._drag_target is not None:
                if self.owner._drag_preview is not None:
                    px = max(0, min(self.owner.engine.image.width - 1, self.owner._drag_preview[0]))
                    py = max(0, min(self.owner.engine.image.height - 1, self.owner._drag_preview[1]))
                transaction = self._edit_transaction()
                context = transaction.context() if transaction.isActive() else {}
                start = tuple(context.get("start", self.owner.engine.point_pixels(*self.owner._drag_target)))
                if abs(px - start[0]) > 1e-09 or abs(py - start[1]) > 1e-09:
                    target = tuple(self.owner._drag_target)
                    if transaction.isActive():
                        before = transaction.snapshot()
                        def commit_point(_value):
                            return self.owner.engine.commit_live_edit(
                                "Move point", before, event="data_changed", merge_id=1001,
                                merge_key=("point", int(self.owner.engine.active_dataset_index), str(target[0]), int(target[1])),
                                merge_window=0.65)
                        transaction.commit(value=(px, py), apply=commit_point)
                    else:
                        self.owner.engine.move_point(*target, px, py)
                    self.owner._set_status('Point moved.', quiet=True)
                else:
                    if transaction.isActive():
                        transaction.commit(value=(px, py))
                    self.owner._set_status('Point selected.', quiet=True)
        except (ValueError, IndexError) as exc:
            self.owner._set_status(str(exc))
        finally:
            self.owner._drag_start = self.owner._drag_preview = self.owner._drag_target = None
            self.owner._region_first_corner = self.owner._region_press = None
            self.owner._anchor_drag_target = self.owner._anchor_drag_preview = None
            self.owner._redraw()

    def _start_tick_calibration(self, rect, *, merge_region_history=False):
        if rect is None or self.owner.engine.image is None:
            return
        self.owner._manual_bounds_axes.clear()
        self.owner._set_calibration_method('smart', cancel_pending=False)

        # ``Read Ticks`` is a fresh auto-detection pass.  Do not let a scale
        # or verified-axis state produced by an earlier failed/partial pass
        # survive into the new job.  The detector itself is deliberately
        # seeded Linear/Linear and will promote a genuinely logarithmic or
        # datetime axis again from raster evidence.  Resetting the engine state
        # as well is important: the background runner snapshots calibration
        # state for stale-result rejection, and the UI otherwise keeps showing
        # the previous Log10 selection/green tick overlay while a clean core
        # detector is already returning Linear results.
        if (self.owner.engine.calibration.scale_x != AxisScale.LINEAR or
                self.owner.engine.calibration.scale_y != AxisScale.LINEAR):
            try:
                self.owner.engine.set_axis_scale(AxisScale.LINEAR, AxisScale.LINEAR)
            except ValueError:
                # Linear accepts every finite calibration value, but keep the
                # auto-read path robust if a malformed legacy project managed
                # to retain an invalid anchor.  Detection below is image-only.
                self.owner.engine.calibration.scale_x = AxisScale.LINEAR
                self.owner.engine.calibration.scale_y = AxisScale.LINEAR
        self.owner.engine.auto_tick_verified_axes.clear()
        self.owner._display_axis_ticks = None

        self.owner._selected_calibration_point = None
        self.owner.calibration_grid.current = self.owner.calibration_grid.anchor = None
        self.owner.calibration_grid.clearSelection()
        self.owner._region_alignment_preview = None
        snap = self.owner.engine.calibration.snap_to_axes
        self.owner._begin_progress('ticks', 'Aligning region to horizontal and vertical axes...' if snap else 'Reading tick labels in the selected rectangle...')
        try:
            region_revision = self.owner.engine.revision if merge_region_history else None
            finished = self.owner._tick_calibration_finished
            if region_revision is not None:
                finished = lambda detection, area, error: self.owner._tick_calibration_finished(detection, area, error, region_revision=region_revision)
            started = self.owner._tick_calibration_runner.submit(rect, finished, on_progress=self.owner._tick_calibration_progress, on_region=self.owner._region_aligned, align_axes=snap)
        except Exception as exc:
            self.owner._finish_progress('ticks', False)
            self.owner._set_status('Tick detection could not start: {}'.format(exc))
            self.owner._offer_manual_axis_bounds()
            return
        if not started:
            self.owner._finish_progress('ticks', False)
            self.owner._set_status('Region selected; enter calibration ticks.')
            self.owner._offer_manual_axis_bounds()
        self.owner._refresh_calibration_actions()

    def _region_aligned(self, rect):
        if not self.owner.winfo_exists() or not self.owner.engine.calibration.snap_to_axes or 'ticks' not in self.owner._progress_jobs or (self.owner._pick_mode == 'area'):
            return
        self.owner._region_alignment_preview = tuple(rect)
        self.owner._redraw()

    def _tick_calibration_finished(self, detection, rect, error, *, region_revision=None):
        if not self.owner.winfo_exists():
            return
        self.owner._region_alignment_preview = None
        if self.owner.engine.plot_rect is None or tuple(self.owner.engine.plot_rect) != tuple(rect):
            self.owner._finish_progress('ticks', False)
            return
        if error:
            self.owner._redraw()
            self.owner._finish_progress('ticks', False)
            if 'discarded' not in str(error).lower():
                self.owner._set_status('Calibration stopped.', details=str(error))
                if 'cancel' not in str(error).lower():
                    self.owner._offer_manual_axis_bounds()
            else:
                self.owner._set_status('Calibration cancelled.', details='Plot area or calibration changed.')
            return
        if detection is None:
            self.owner._finish_progress('ticks', False)
            self.owner._redraw()
            self.owner._offer_manual_axis_bounds()
            return
        try:
            applied = self.owner.engine.apply_tick_calibration_detection(detection, expected_rect=rect)
            if applied and region_revision is not None:
                self.owner.engine.merge_region_tick_history(region_revision)
        except (ValueError, IndexError) as exc:
            self.owner._finish_progress('ticks', False)
            self.owner._set_status('Calibration could not be applied.', details=str(exc))
            self.owner._redraw()
            return
        self.owner._finish_progress('ticks', applied)
        if applied:
            self.owner._display_axis_ticks = detection
        details, missing, unread = ([], [], 0)
        for reading in (detection.x, detection.y):
            axis = reading.axis.upper()
            measured = [tick for tick in reading.ticks if tick.bbox != (0, 0, 0, 0)]
            count = len(reading.unread_positions)
            unread += count
            if reading.ready:
                details.append('{}: {} | {} measured ticks | {} unread'.format(axis, reading.scale.value, len(measured), count))
            else:
                missing.append(axis)
                details.append('{}: not recognized. Initial anchors are placeholders, not measured values.'.format(axis))
            if measured:
                values = [tick.value for tick in measured]
                details.append('{} range: {} .. {}'.format(axis, self.owner._fmt_axis(min(values), reading.scale), self.owner._fmt_axis(max(values), reading.scale)))
        if detection.aligned_rect is not None and tuple(detection.aligned_rect) != tuple(rect):
            details.append('Region aligned to detected axes.')
        if not applied or len(missing) == 2:
            summary = 'Axes not recognized.'
        elif missing:
            summary = 'Calibration incomplete: {} not recognized.'.format(', '.join(missing))
        elif unread:
            summary = 'Axes calibrated; {} unread ticks.'.format(unread)
        else:
            summary = 'Axes calibrated.'
        if missing or unread:
            details.append('Review the Calibration table and enter missing tick values manually.')
        self.owner._set_status(summary, details='\n'.join(details))
        self.owner._refresh_all()
        if missing:
            self.owner._offer_manual_axis_bounds([axis.lower() for axis in missing])

    def _offer_manual_axis_bounds(self, axes=('x', 'y')):
        """Expose blank endpoint editors without confirming internal Box seeds."""
        if self.owner.engine.plot_rect is None:
            return
        axes = {axis for axis in axes if axis not in self.owner.engine.auto_tick_verified_axes}
        if not axes:
            return
        if any((getattr(self.owner.engine.calibration, axis + suffix) is None for axis in axes for suffix in ('1', '2'))):
            self.owner.engine.prepare_manual_axis_bounds(axes)
        newly_missing = axes - self.owner._manual_bounds_axes
        self.owner._manual_bounds_axes.update(axes)
        self.owner._show_tool('axes')
        self.owner.set_control_value(self.owner._disclosures['axes'], True)
        self.owner._refresh_anchor_values()
        for key, editor in self.owner.anchor_value.items():
            if key[0] in newly_missing:
                self.owner.set_control_value(editor, '')
        self.owner.set_control_value(self.owner.calibration_hint, 'Axis detection incomplete. Enter {} endpoint values below, then Apply Axis Values. Detected axes are kept.'.format('/'.join((axis.upper() for axis in sorted(axes)))))
        self.owner.set_control_visible(self.owner.calibration_hint, True)
        QRetainedItem(self.owner.settings_panel).setVerticalScrollValue(10000)
        self.owner.view.after(60, self.owner._reveal_manual_axis_bounds, tuple(self.owner.engine.plot_rect))

    def _reveal_manual_axis_bounds(self, rect):
        if self.owner.winfo_exists() and self.owner._manual_bounds_axes and (self.owner.engine.plot_rect is not None) and (tuple(self.owner.engine.plot_rect) == rect) and (self.owner._active_tool == 'axes') and self.owner.control_value(self.owner._disclosures['axes']):
            QRetainedItem(self.owner.settings_panel).setVerticalScrollValue(10000)

    def _paint_detected_axis_ticks(self, painter):
        """Show all accepted major ticks, not only the four box anchors.

        Coordinates are source-image pixel coordinates; they must be converted
        via the same pan/zoom transform as the calibration anchors.
        """
        detection = getattr(self.owner, '_display_axis_ticks', None)
        rect = self.owner.engine.plot_rect
        if detection is None or rect is None:
            return
        left, top, right, bottom = rect
        for axis, reading, ink in (('x', detection.x, (0, 120, 215, 255)), ('y', detection.y, (30, 150, 80, 255))):
            if not reading.ready:
                continue
            if len(reading.ticks) >= 3 and (not getattr(self.owner.engine.calibration, 'points_' + axis)):
                continue
            current = getattr(self.owner.engine.calibration, 'points_' + axis)
            expected = {(t.position, t.value) for t in reading.ticks if t.bbox != (0, 0, 0, 0)}
            if current and {(p.px if axis == 'x' else p.py, p.value) for p in current} != expected:
                continue
            for tick in reading.ticks[:40]:
                if tick.bbox != (0, 0, 0, 0) and getattr(self.owner.engine.calibration, 'points_' + axis):
                    continue
                inferred = tick.bbox == (0, 0, 0, 0)
                display_value = tick.text if reading.scale == AxisScale.DATETIME and (not inferred) and tick.text else self.owner._fmt_axis(tick.value, reading.scale)
                label = ('~' if inferred else '') + display_value
                if axis == 'x':
                    if not left - 2 <= tick.position <= right + 2:
                        continue
                    x, y = self.owner._image_to_canvas(tick.position, bottom)
                    painter.drawLine((x, y), (x, y + 5), color=ink)
                    painter.drawText((x + 3, y + 10), label, color=ink, size=12)
                else:
                    if not top - 2 <= tick.position <= bottom + 2:
                        continue
                    x, y = self.owner._image_to_canvas(left, tick.position)
                    painter.drawLine((x - 5, y), (x, y), color=ink)
                    painter.drawText((x + 9, y - 10), label, color=ink, size=12)
