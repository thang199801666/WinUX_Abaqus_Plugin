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

class ProjectController:
    """Project behavior extracted from PlotDigitizerDialog; state remains owned by the dialog."""

    def __init__(self, owner):
        self.owner = owner

    def _file_picker(self, *, directory=False, save=False, extensions=(), callback=None, default_filename=''):
        if self.owner._file_dialog is not None:
            try:
                self.owner._file_dialog.close()
            except Exception:
                pass

        def selected(path):
            self.owner._file_directory = str(Path(path).parent)
            if callable(callback):
                callback(path)
        self.owner._file_dialog = FileSelector(view=self.owner.view, parent=self.owner, accepted=selected, cancelled=lambda: self.owner._set_status('Ready.'), extensions=extensions, directory=directory, save=save, default_filename=default_filename, initial=self.owner._file_directory or (str(Path(self.owner.engine.image_path).parent) if self.owner.engine.image_path else ''))
        return self.owner._file_dialog.open()

    def _choose_open_image(self):
        self.owner._file_picker(extensions=('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'), callback=self.owner._open_image)

    def _open_image(self, path):
        self.owner._image_load_generation += 1
        generation = self.owner._image_load_generation
        previous = self.owner._image_load_future
        if previous is not None and (not previous.isFinished()):
            previous.cancel()
        self.owner._begin_progress('image', 'Opening image...')

        def loaded(result):
            if generation != self.owner._image_load_generation:
                return
            image, resolved = result
            try:
                self.owner.engine.apply_image(image, resolved)
                self.owner._auto_fit = self.owner._plot_preferences['fit_images_on_open']
                self.owner._pick_mode = None
                self.owner._set_edit_enabled(False)
                self.owner._sample_pixel = None
                for key in self.owner.anchor_value:
                    self.owner.set_control_value(self.owner.anchor_value[key], '')
                    self.owner.set_control_enabled(self.owner.anchor_value[key], False)
                self.owner._load_texture(self.owner.engine.image)
                self.owner.view.after(1, self.owner._fit_view if self.owner._auto_fit else self.owner._one_to_one)
                self.owner._finish_progress('image')
                self.owner._set_status('')
            except Exception as exc:
                self.owner._finish_progress('image', False)
                self.owner._set_status('Could not open image: {}'.format(exc))

        def failed(exc):
            if generation == self.owner._image_load_generation:
                self.owner._finish_progress('image', False)
                self.owner._set_status('Could not open image: {}'.format(exc))
        try:
            self.owner._image_load_future = self.owner.runAsync(self.owner.engine.read_image, path, on_result=loaded, on_error=failed)
        except Exception as exc:
            failed(exc)

    def _choose_load_project(self):
        self.owner._file_picker(extensions=('.pdg', '.json'), callback=self.owner._load_project)

    def _load_project(self, path):
        try:
            state = self.owner.engine.load_project(path, view_validator=normalize_workspace_state)
            self.owner._project_path = str(Path(path).resolve())
            generation = self.owner._project_load_generation
            self.owner._auto_fit = state.get('auto_fit', True)
            self.owner._pick_mode = None
            self.owner._set_edit_enabled(False)
            self.owner._sample_pixel = None
            if self.owner.engine.image is not None:
                self.owner._load_texture(self.owner.engine.image)
            else:
                if self.owner._texture_tag is not None and hasattr(self.owner._texture_tag, 'delete'):
                    self.owner._texture_tag.delete()
                self.owner._texture_tag = None
            self.owner._file_directory = str(Path(path).resolve().parent)
            for key, editor in self.owner.anchor_value.items():
                self.owner._control_wrappers[editor].setText('1' if key.endswith('2') else '0')
            native_context = getattr(self.owner.view, 'is_standalone_ui_host', False) or getattr(self.owner, '_floating_kind', None) == 'plotdigitizer'
            if native_context and state.get('viewport_size'):
                width, height = state['viewport_size']
                application = QApplication.instance()
                if application is not None:
                    application.primaryScreen().resizeWindow(max(1100, int(width)), max(720, int(height)))
                else:
                    QGuiRuntime().configureViewport(width=max(1100, int(width)), height=max(720, int(height)))
            self.owner.view.after(1, self.owner._restore_project_view, state, generation, self.owner._project_frame() + 2)
            self.owner._set_status('Project loaded.')
        except Exception as exc:
            self.owner._set_status('Could not load project: {}'.format(exc))

    def _choose_save_project(self):
        if self.owner._project_path:
            return self.owner._save_project(self.owner._project_path)
        return self.owner._choose_save_project_as()

    def _choose_save_project_as(self):
        self.owner._file_picker(save=True, extensions=('.pdg',), callback=self.owner._save_project, default_filename=Path(self.owner._project_path).name if self.owner._project_path else 'plot_digitizer.pdg')

    def _save_project(self, path):
        try:
            path = str(path)
            if Path(path).suffix.casefold() not in ('.pdg', '.json'):
                path += '.pdg'
            self.owner.engine.save_project(path, view_state=self.owner._capture_project_view())
            self.owner._project_path = str(Path(path).resolve())
            self.owner._file_directory = str(Path(self.owner._project_path).parent)
            self.owner._set_status('Project saved.')
        except Exception as exc:
            self.owner._set_status('Could not save project: {}'.format(exc))

    def _capture_project_view(self):
        _, size = self.owner._canvas_rect()
        application = QApplication.instance()
        if application is not None:
            geometry = application.primaryScreen().windowGeometry()
            viewport_size = [geometry.width(), geometry.height()]
        else:
            viewport = QGuiRuntime().viewportSize()
            viewport_size = [max(1, viewport.width()), max(1, viewport.height())]
        state = {'version': 1, 'tool': self.owner._active_tool or 'axes', 'calibration_method': self.owner._calibration_method, 'ribbon_tab': self.owner.ribbon.active_tab() or 'home', 'ribbon_minimized': self.owner.ribbon.is_minimized(), 'coordinate_mode': self.owner.control_value(self.owner.coordinate_mode), 'export_scope': self.owner.control_value(self.owner.export_scope), 'export_sort': self.owner.EXPORT_SORT_OPTIONS[self.owner.control_value(self.owner.export_sort)], 'reduction_error': float(self.owner.control_value(self.owner.reduction_error)), 'auto_fit': self.owner._auto_fit, 'scale': self.owner._fit_scale * self.owner._zoom, 'zoom': self.owner._zoom, 'pan': list(self.owner._pan), 'canvas_size': list(size), 'viewport_size': viewport_size, 'selected_point': self.owner._selected_point, 'selected_rows': list(self.owner.result_grid.selectedKeys()), 'grid_current': self.owner.result_grid.currentKey(), 'edit_enabled': self.owner._edit_enabled, 'anchor_text': {key: str(self.owner.control_value(editor)) for key, editor in self.owner.anchor_value.items()}, 'dataset_name_text': self.owner.engine.active_dataset.name, 'point_x_text': str(self.owner.control_value(self.owner.point_x)), 'point_y_text': str(self.owner.control_value(self.owner.point_y)), 'sample_pixel': self.owner._sample_pixel, 'cursor_pixel': self.owner._cursor_pixel, 'palette': [list(color) for color in self.owner._palette], 'palette_selection': self.owner.control_value(self.owner.palette_combo), 'pick_mode': self.owner._pick_mode, 'calibration_sequence': list(self.owner._calibration_sequence), 'disclosures': {key: bool(self.owner.control_value(item)) for key, item in self.owner._disclosures.items()}, 'dataset_scroll': QRetainedItem(self.owner.dataset_panel).verticalScrollValue(), 'settings_scroll': QRetainedItem(self.owner.settings_panel).verticalScrollValue()}
        return normalize_workspace_state(state, self.owner.engine)

    def _project_frame(self):
        application = QApplication.instance()
        return application.frameCount() if application is not None else self.owner._renderer_backend().get_frame_count()

    def _restore_project_view(self, state, generation, after_frame):
        if not self.owner.winfo_exists() or generation != self.owner._project_load_generation:
            return
        if self.owner._project_frame() < after_frame:
            self.owner.view.after(1, self.owner._restore_project_view, state, generation, after_frame)
            return
        self.owner._refresh_all()
        if not state:
            self.owner._set_calibration_method('smart' if self.owner.engine.calibration.box_rect is not None else 'manual', cancel_pending=False)
            self.owner._fit_view()
            return
        self.owner._set_calibration_method(state['calibration_method'], cancel_pending=False)
        self.owner.set_control_value(self.owner.coordinate_mode, state['coordinate_mode'])
        self.owner.set_control_value(self.owner.export_scope, state['export_scope'])
        self.owner.set_control_value(self.owner.export_sort, next((label for label, value in self.owner.EXPORT_SORT_OPTIONS.items() if value == state['export_sort'])))
        self.owner._control_wrappers[self.owner.reduction_error].setValue(state['reduction_error'])
        self.owner._refresh_grid()
        self.owner._set_edit_enabled(state['edit_enabled'])
        self.owner._show_tool('axes' if state['tool'] == 'settings' else state['tool'])
        self.owner._selected_point = tuple(state['selected_point']) if state['selected_point'] else None
        self.owner.result_grid.selected = {'{}:{}'.format(*key) for key in state['selected_rows']}
        self.owner.result_grid.current = '{}:{}'.format(*state['grid_current']) if state['grid_current'] else None
        self.owner._refresh_point_editor()
        self.owner.ribbon.set_active_tab(state['ribbon_tab'])
        self.owner.ribbon.set_minimized(state['ribbon_minimized'])
        self.owner._sample_pixel, self.owner._cursor_pixel = (state['sample_pixel'], state['cursor_pixel'])
        self.owner._palette = [tuple((round(channel) for channel in color)) for color in state['palette']]
        labels = ['#{:02X}{:02X}{:02X}'.format(*color) for color in self.owner._palette]
        self.owner.set_control_items(self.owner.palette_combo, labels or ['Find image colors...'])
        self.owner.set_control_visible(self.owner.palette_combo, len(labels) > 1)
        if state['palette_selection']:
            self.owner.set_control_value(self.owner.palette_combo, state['palette_selection'])
        for key, opened in state['disclosures'].items():
            self.owner.set_control_value(self.owner._disclosures[key], opened)
        self.owner._pick_mode = state['pick_mode']
        self.owner._calibration_sequence = []
        self.owner.set_control_visible(self.owner.calibration_hint, self.owner._pick_mode in ('x1', 'x2', 'y1', 'y2'))
        if self.owner._pick_mode in ('x1', 'x2', 'y1', 'y2'):
            self.owner.set_control_value(self.owner.calibration_hint, 'Click {} on a known axis tick. Esc cancels.'.format(self.owner._pick_mode.upper()))
        for key, text in state['anchor_text'].items():
            editor = self.owner.anchor_value[key]
            anchor = getattr(self.owner.engine.calibration, key)
            restored = text if anchor is not None else ''
            self.owner._control_wrappers[editor].setText(restored)
            self.owner.set_control_value(editor, restored)
            self.owner.set_control_enabled(editor, anchor is not None)
        for field, key in ((self.owner.point_x, 'point_x_text'), (self.owner.point_y, 'point_y_text')):
            if state[key] is not None:
                self.owner._control_wrappers[field].setText(state[key])
                self.owner.set_control_value(field, state[key])
        self.owner.view.after(1, self.owner._restore_project_camera, state, generation, self.owner._project_frame() + 2)
        self.owner._refresh_export_controls()

    def _restore_project_camera(self, state, generation, after_frame):
        if not self.owner.winfo_exists() or generation != self.owner._project_load_generation:
            return
        if self.owner._project_frame() < after_frame:
            self.owner.view.after(1, self.owner._restore_project_camera, state, generation, after_frame)
            return
        if state['auto_fit']:
            self.owner._fit_view()
        else:
            _, (width, height) = self.owner._canvas_rect()
            self.owner._auto_fit = False
            self.owner._zoom = state['zoom']
            self.owner._fit_scale = state['scale'] / state['zoom']
            self.owner._pan = [state['pan'][0] + (width - state['canvas_size'][0]) / 2, state['pan'][1] + (height - state['canvas_size'][1]) / 2]
            self.owner._redraw()
        if self.owner.dataset_panel != self.owner.settings_panel:
            QRetainedItem(self.owner.dataset_panel).setVerticalScrollValue(state['dataset_scroll'])
        QRetainedItem(self.owner.settings_panel).setVerticalScrollValue(state['settings_scroll'])

    def _export_selection(self):
        dataset_index = (self.owner.engine.active_dataset_index
                         if self.owner.control_value(self.owner.export_scope) == 'Active dataset' else None)
        order = self.owner.EXPORT_SORT_OPTIONS[self.owner.control_value(self.owner.export_sort)]
        return dataset_index, None if order == 'original' else order

    def _choose_export_csv(self):
        self.owner._show_tool('data')
        self.owner._file_picker(save=True, extensions=('.csv',), callback=self.owner._export_csv, default_filename='digitized_data.csv')

    def _export_csv(self, path):
        try:
            if not str(path).lower().endswith('.csv'):
                path += '.csv'
            dataset_index, sort_by = self._export_selection()
            self.owner.engine.export_csv(path, dataset_index, sort_by=sort_by)
            self.owner._set_status('CSV exported.')
        except Exception as exc:
            self.owner._set_status('Could not export CSV: {}'.format(exc))

    def _choose_export_excel(self):
        self.owner._show_tool('data')
        self.owner._file_picker(save=True, extensions=('.xlsx',), callback=self.owner._export_excel,
                                default_filename='digitized_data.xlsx')

    def _export_excel(self, path):
        try:
            from WinUx.services.excel_export import export_plot_digitizer_xlsx
            dataset_index, sort_by = self._export_selection()
            export_plot_digitizer_xlsx(self.owner.engine, path, dataset_index, sort_by=sort_by)
            self.owner._set_status('Excel exported.')
        except Exception as exc:
            self.owner._set_status('Could not export Excel: {}'.format(exc))
