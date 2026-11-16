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
from DearUIQt.gui.palette import color_scheme
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
from WinUx.plotdigitizer.ui.retained_canvas import RetainedCanvasLayer

class CanvasController:
    """Canvas behavior extracted from PlotDigitizerDialog; state remains owned by the dialog."""

    def __init__(self, owner):
        self.owner = owner
        self._last_hover_sample = None
        self._scene_layer = None
        self._scene_pan = None
        self._view_redraw_pending = False
        self._view_redraw_callback = None

    def _build_canvas_panel(self, parent):
        self.owner._canvas_frame_widget = self.owner.own_widget(QFrame(parent=parent, width=self.owner.CANVAS_MIN_WIDTH, height=440, frame_shape=QFrame.StyledPanel, no_scrollbar=True, no_scroll_with_mouse=True))
        self.owner.canvas_frame = self.owner._canvas_frame_widget.tag
        style_image_canvas(self.owner.canvas_frame)
        self.owner._canvas_widget = QCanvas(parent=self.owner._canvas_frame_widget, width=self.owner.CANVAS_MIN_WIDTH - 2, height=438)
        self.owner.canvas = self.owner._canvas_widget.tag
        self.owner._build_canvas_view_tools()
        self.owner._canvas_resize_binding = QItemInputBinding(parent, parent=self.owner).onResize(lambda *_: self.owner.view.after(0, self.owner._layout_canvas)).activate()
        self.owner._canvas_visible_binding = QItemInputBinding(self.owner._canvas_widget, parent=self.owner).onVisible(lambda *_: self.owner._canvas_pointer_tick()).activate()
        self.owner._texture_registry = QTextureRegistry(parent=self.owner, visible=False)

    def _build_canvas_view_tools(self):
        self.owner._canvas_view_toolbar = self.owner.own_widget(QFrame(parent=self.owner._canvas_frame_widget, width=self.owner.CANVAS_VIEW_TOOLS_WIDTH, height=self.owner.CANVAS_VIEW_TOOLS_HEIGHT, pos=(8, 6), frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.owner._canvas_view_toolbar.setTheme(make_theme(theme_component(ThemeTarget.CHILD_WINDOW, colors={ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0), ThemeColor.BORDER: (0, 0, 0, 0), ThemeColor.BORDER_SHADOW: (0, 0, 0, 0)}, styles={ThemeStyle.WINDOW_PADDING: (2, 2), ThemeStyle.ITEM_SPACING: (4, 0), ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0})))
        self.owner._canvas_view_themes = self._canvas_view_theme_map()
        row = self.owner.own_widget(QHBoxLayout(parent=self.owner._canvas_view_toolbar, spacing=4))
        self.owner._canvas_view_buttons = {}
        self.owner._canvas_view_tool_states = {}
        for key, icon, tooltip, callback in (('fit', 'fit_view', 'Fit Image: fit the whole chart to the canvas', self.owner._fit_view), ('one_to_one', 'one_to_one', 'Actual Size: one image pixel per screen pixel (1:1)', self.owner._one_to_one), ('zoom_out', 'zoom_out', 'Zoom Out', lambda: self.owner._zoom_at(1 / 1.15)), ('zoom_in', 'zoom_in', 'Zoom In', lambda: self.owner._zoom_at(1.15))):
            button = self.owner._icon_only_action(icon, callback, parent=row, tooltip=tooltip, button_size=28, icon_size=24)
            self.owner.control_wrapper(button).backend.configure_item(button, uv_min=(0.125, 0.125), uv_max=(0.875, 0.875))
            self.owner.control_wrapper(button).setTheme(self.owner._canvas_view_themes['idle'])
            self.owner._canvas_view_buttons[key] = button
            self.owner._canvas_view_tool_states[key] = 'idle'
            self.owner.set_control_enabled(button, False)

    def _canvas_view_theme_map(self):
        p = QtFusionPalette
        scheme = color_scheme().strip().lower()
        result = {}
        for state, alpha in (('idle', 0), ('hover', 95), ('pressed', 170)):
            components = []
            for enabled in (True, False):
                base = p.HIGHLIGHT if enabled else p.TEXT_DISABLED
                face = tuple(base[:3]) + (alpha,)
                for target in (ThemeTarget.PUSH_BUTTON, ThemeTarget.IMAGE_BUTTON):
                    components.append(theme_component(
                        target,
                        colors={
                            ThemeColor.BUTTON: face,
                            ThemeColor.BUTTON_HOVERED: face,
                            ThemeColor.BUTTON_ACTIVE: face,
                            ThemeColor.BORDER: (0, 0, 0, 0),
                        },
                        styles={
                            ThemeStyle.FRAME_BORDER_SIZE: 0,
                            ThemeStyle.FRAME_ROUNDING: 3,
                            ThemeStyle.FRAME_PADDING: (2, 2),
                            ThemeStyle.ALPHA: 1.0 if enabled else 0.6,
                        },
                        enabled_state=enabled,
                    ))
            result[state] = make_theme(
                *components,
                backend=self.owner._renderer_backend(),
                tag='winux.plotdigitizer.canvas.view.{}.{}'.format(scheme, state),
                cache=True,
            )
        return result

    def refresh_theme(self):
        """Rebind retained canvas overlay controls after Light/Dark changes."""
        toolbar = getattr(self.owner, '_canvas_view_toolbar', None)
        if toolbar is None or getattr(toolbar, '_deleted', False):
            return False
        toolbar.setTheme(make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={
                ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0),
                ThemeColor.BORDER: (0, 0, 0, 0),
                ThemeColor.BORDER_SHADOW: (0, 0, 0, 0),
            },
            styles={
                ThemeStyle.WINDOW_PADDING: (2, 2),
                ThemeStyle.ITEM_SPACING: (4, 0),
                ThemeStyle.CHILD_BORDER_SIZE: 0,
                ThemeStyle.CHILD_ROUNDING: 0,
            },
        )))
        self.owner._canvas_view_themes = self._canvas_view_theme_map()
        for key, tag in getattr(self.owner, '_canvas_view_buttons', {}).items():
            try:
                state = self.owner._canvas_view_tool_states.get(key, 'idle')
                self.owner.control_wrapper(tag).setTheme(
                    self.owner._canvas_view_themes.get(state, self.owner._canvas_view_themes['idle']))
            except Exception:
                pass
        return True

    def _update_canvas_view_tool_states(self):
        point = QCursor.pos()
        down = bool(QCursor.buttons(backend=self.owner._renderer_backend()) & Qt.LeftButton)
        visible = self.owner._canvas_view_toolbar.isVisible()
        inside_toolbar = visible and self.owner._canvas_view_toolbar.globalGeometry().contains(point)
        for key, tag in self.owner._canvas_view_buttons.items():
            button = self.owner.control_wrapper(tag)
            hovered = inside_toolbar and button.globalGeometry().contains(point)
            pressed = hovered and (button._pointer_pressed or down)
            state = 'pressed' if pressed else 'hover' if hovered else 'idle'
            if self.owner._canvas_view_tool_states[key] != state:
                self.owner._canvas_view_tool_states[key] = state
                button.setTheme(self.owner._canvas_view_themes[state])

    def _canvas_view_tools_under_mouse(self):
        toolbar = getattr(self.owner, '_canvas_view_toolbar', None)
        return bool(toolbar is not None and toolbar.isVisible() and toolbar.globalGeometry().contains(QCursor.pos()))

    def _toggle_action(self, label, callback, *, parent, width=-1):
        """Create a WinUx-styled checkable push button and retain its wrapper."""
        widget = self.owner.own_widget(QPushButton(label, width=int(width), parent=parent, after=self.owner.view.after, checkable=True))
        widget.toggled.connect(callback)
        self.owner._control_wrappers[widget.tag] = widget
        self.owner._remember_focusable(widget.tag)
        return widget.tag

    def _install_mouse_handlers(self):
        binding = QGlobalInputBinding(backend=self.owner._renderer_backend(), parent=self.owner)
        native_delete = QGlobalInputBinding.nativeKeyFor(Qt.Key_Delete, self.owner._renderer_backend())
        if native_delete is not None:
            self.owner.shortcuts[native_delete, False] = lambda: self.owner._edit_key(None, key=Qt.Key_Delete)
        binding.onMouseClick(Qt.LeftButton, self.owner._mouse_left)
        binding.onMouseRelease(Qt.LeftButton, self.owner._mouse_left_up)
        binding.onMouseClick(Qt.MiddleButton, self.owner._mouse_middle_down)
        binding.onMouseRelease(Qt.MiddleButton, self.owner._mouse_middle_up)
        binding.onMouseMove(self.owner._mouse_move)
        binding.onMouseWheel(self.owner._mouse_wheel)
        for key in (Qt.Key_Z, Qt.Key_Y, Qt.Key_Delete, Qt.Key_A, Qt.Key_S, Qt.Key_N, Qt.Key_P, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            binding.onKeyPress(key, self.owner._edit_key, user_data=key)
        self.owner._input_binding = binding.activate()
        self.owner._handler_registry = None

    def _native_delete_snapshot(self):
        """Read a physical Delete edge with strict native window ownership."""
        if os.name != 'nt':
            return None
        try:
            import ctypes
            user32 = ctypes.windll.user32
            down = bool(user32.GetAsyncKeyState(46) & 32768)
            if not down:
                return (False, Qt.NoModifier, False)
            modifiers = Qt.NoModifier
            for key, flag in ((16, Qt.ShiftModifier), (17, Qt.ControlModifier), (18, Qt.AltModifier), (91, Qt.MetaModifier), (92, Qt.MetaModifier)):
                if user32.GetAsyncKeyState(key) & 32768:
                    modifiers |= flag
            native = getattr(self.owner, '_native_window_backend', None)
            resolver = getattr(self.owner.view, '_find_main_viewport_hwnd', None)
            hwnd = int(native.winId(self.owner.tag) or 0) if native is not None else 0
            if not hwnd:
                hwnd = int(resolver() or 0) if callable(resolver) else 0
            from WinUx.ui.native.dialog_focus import foreground_hwnd, window_state
            owned = bool(hwnd and foreground_hwnd() == hwnd and all(window_state(hwnd)))
            return (down, modifiers, owned)
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def _poll_delete_key(self):
        if getattr(self.owner, '_closed', False) or getattr(self.owner, '_visible_state', True) is False:
            return
        state = self.owner._native_delete_snapshot()
        native_press = False
        if state is not None:
            down, modifiers, owned = state
            previous = getattr(self.owner, '_delete_key_down', False)
            self.owner._delete_key_down = down
            if not down:
                self.owner._delete_key_consumed = False
            if not owned:
                return
            native_press = down and (not previous)
        else:
            modifiers = QKeyboard.modifiers(backend=self.owner._renderer_backend())
        calibration = self.owner._active_tool == 'axes' and getattr(self.owner, '_selected_calibration_point', None) is not None
        data = (self.owner._edit_enabled or self.owner._active_tool == 'data') and (self.owner._selected_point is not None or self.owner.result_grid.selectedKeys())
        pressed = native_press if state is not None else QKeyboard.isKeyPressed(Qt.Key_Delete, backend=self.owner._renderer_backend())
        if (calibration or data) and pressed:
            self.owner._edit_key(None, key=Qt.Key_Delete, modifiers=modifiers)

    def _edit_key(self, _sender, _app_data=None, key=None, *, modifiers=None):
        if key is None:
            key = QGlobalInputBinding.qtKeyForNative(_app_data, self.owner._renderer_backend())
        if modifiers is None:
            modifiers = QKeyboard.modifiers(backend=self.owner._renderer_backend())
        if modifiers & (Qt.AltModifier | Qt.MetaModifier):
            return
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if ctrl and key == Qt.Key_S:
            if self.owner._accepts_edit_shortcut(allow_editor=True):
                (self.owner._choose_save_project_as if shift else self.owner._choose_save_project)()
                return True
            return
        if not self.owner._accepts_edit_shortcut():
            return
        if not ctrl and key == Qt.Key_Delete:
            if getattr(self.owner, '_pick_mode', None) is not None:
                return
            state = self.owner._native_delete_snapshot()
            if state is not None and state[0]:
                if not state[2]:
                    return
                if getattr(self.owner, '_delete_key_consumed', False):
                    return True
            if self.owner._active_tool == 'axes':
                if getattr(self.owner, '_selected_calibration_point', None) is None:
                    return
                self.owner._remove_calibration_point()
                self.owner._redraw()
            elif self.owner._edit_enabled and (self.owner._selected_point is not None or self.owner.result_grid.selectedKeys()) or (self.owner._active_tool == 'data' and self.owner.result_grid.hasFocus()):
                self.owner._delete_points()
            else:
                return
            if state is not None and state[0]:
                self.owner._delete_key_consumed = True
            return True
        worksheet = getattr(self.owner, 'data_worksheet', None)
        if worksheet is not None and worksheet.owns_keyboard() and (key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)):
            return
        if not ctrl and key in (Qt.Key_N, Qt.Key_P) and (self.owner._active_tool in ('extract', 'data')):
            self.owner._navigate_point(1 if key == Qt.Key_N else -1)
            return
        if ctrl and key == Qt.Key_Z:
            self.owner._trigger_history_command('redo' if shift else 'undo')
            return True
        elif ctrl and (not shift) and (key == Qt.Key_Y):
            self.owner._trigger_history_command('redo')
            return True
        elif not ctrl and key == Qt.Key_Escape and getattr(self.owner, '_edit_transaction', None) is not None and self.owner._edit_transaction.isActive():
            self.owner._cancel_pick()
            self.owner._set_status('Edit canceled.', quiet=True)
            return True
        elif not ctrl and key == Qt.Key_Escape and self.owner._edit_enabled and (self.owner._selected_point is not None or self.owner.result_grid.selectedKeys()):
            self.owner._clear_point_selection()
            self.owner._refresh_point_editor()
            self.owner._redraw()
            self.owner._set_status('Selection cleared.', quiet=True)
            return True
        elif not ctrl and self.owner._mouse_in_canvas():
            modes = {Qt.Key_A: 'manual'}
            if key == Qt.Key_S:
                self.owner._toggle_edit_mode()
            elif key in modes:
                self.owner._begin_pick(modes[key])
            elif self.owner._selected_point is not None and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                step = 10 if shift else 1
                dx = -step if key == Qt.Key_Left else step if key == Qt.Key_Right else 0
                dy = -step if key == Qt.Key_Up else step if key == Qt.Key_Down else 0
                try:
                    px, py = self.owner.engine.point_pixels(*self.owner._selected_point)
                    self.owner.engine.move_point(*self.owner._selected_point, max(0, min(self.owner.engine.image.width - 1, px + dx)), max(0, min(self.owner.engine.image.height - 1, py + dy)))
                except (ValueError, IndexError) as exc:
                    self.owner._set_status(str(exc))

    def _accepts_edit_shortcut(self, *, allow_editor=False):
        """Local editor shortcut scope, not an application-wide key dispatcher."""
        if not self.owner.winfo_exists():
            return False
        if hasattr(self.owner, '_visible_state'):
            if not self.owner.isVisible():
                return False
        else:
            try:
                if not QRetainedItem(self.owner.tag, backend=self.owner._renderer_backend()).isVisible():
                    return False
            except Exception:
                pass
        from DearUIQt.input_gate import native_modal_input_active
        if native_modal_input_active():
            return False
        application = QApplication.instance()
        if application is not None:
            modal = application.activeModalWidget()
            if modal is not None and modal is not self.owner:
                return False
            if application.activePopupWidget() is not None:
                return False
        if getattr(self.owner, '_close_confirmation_pending', False):
            return False
        selector = getattr(getattr(self.owner, '_file_dialog', None), 'dialog', None)
        if selector is not None and selector.winfo_exists():
            return False
        settings = getattr(self.owner, '_settings_dialog', None)
        if settings is not None and settings.isVisible():
            return False
        menu = getattr(self.owner, 'dataset_menu', None)
        if menu is not None and (not getattr(menu, '_deleted', False)):
            visible = getattr(menu, 'isVisible', None)
            if callable(visible):
                if visible():
                    return False
            else:
                try:
                    if QRetainedItem(getattr(menu, 'tag', menu), backend=self.owner._renderer_backend()).isVisible():
                        return False
                except Exception:
                    pass
        canvas_keyboard_focus = False
        try:
            application = QApplication.instance()
            canvas_keyboard_focus = bool(application is not None and application.focusObject() is getattr(self.owner, '_canvas_widget', None))
        except Exception:
            pass
        resolver = getattr(self.owner.view, '_find_main_viewport_hwnd', None)
        native = getattr(self.owner, '_native_window_backend', None)
        hwnd = int(native.winId(self.owner.tag) or 0) if native is not None else 0
        if not hwnd:
            hwnd = resolver() if callable(resolver) else 0
        if hwnd:
            from WinUx.ui.native.dialog_focus import foreground_hwnd, window_state
            if not all(window_state(hwnd)):
                return False
            foreground = foreground_hwnd()
            if foreground and foreground != hwnd and (not canvas_keyboard_focus):
                return False
        if not allow_editor and (not canvas_keyboard_focus):
            for item in getattr(self.owner, 'enter_editors', ()):
                if QRetainedItem(item, backend=self.owner._renderer_backend()).nativeState().get('active', False):
                    return False
        focused_item = QRetainedItem.focusedItem(backend=self.owner._renderer_backend())
        if focused_item is not None and (not canvas_keyboard_focus):
            try:
                item_type = focused_item.itemType()
                if not allow_editor and any((kind in item_type for kind in ('Input', 'Combo', 'Slider', 'Drag', 'Color'))):
                    return False
                visited = set()

                def native_id(item):
                    if isinstance(item, str):
                        value = self.owner._renderer_backend().get_alias_id(item)
                        return value if isinstance(value, int) and value else item
                    return item
                owner = native_id(self.owner.tag)
                item = native_id(focused_item.tag)
                while item and item != owner and (item not in visited):
                    visited.add(item)
                    item = native_id(QRetainedItem(item, backend=self.owner._renderer_backend()).parentItem())
                if item != owner:
                    return False
            except Exception:
                return False
        return True

    def _focus_canvas_keyboard(self):
        """Give the paint canvas logical keyboard focus even if its drawlist cannot own native focus.

        Dear PyGui drawlists are not normal focusable controls on every backend.
        A point click can therefore leave an InputText/table reported as the
        renderer-focused item.  Document shortcuts such as Delete must follow
        the canvas interaction, not that stale native focus.
        """
        canvas = getattr(self.owner, '_canvas_widget', None)
        if canvas is None:
            return False
        native_focused = False
        try:
            native_focused = bool(canvas.setFocus())
        except Exception:
            pass
        try:
            application = QApplication.instance()
            if application is not None:
                application.setFocusObject(canvas)
                return True
        except Exception:
            pass
        return native_focused

    def _mouse_in_canvas(self):
        return self.owner._canvas_widget.exists() and self.owner._canvas_widget.underMouse() and (not self.owner._canvas_view_tools_under_mouse())

    def _canvas_rect(self):
        try:
            rect = self.owner._canvas_widget.globalGeometry()
            return (rect.topLeft().toTuple(), (rect.width(), rect.height()))
        except Exception:
            return ((0, 0), (1, 1))

    def _image_to_canvas(self, px, py):
        scale = self.owner._fit_scale * self.owner._zoom
        return (self.owner._pan[0] + px * scale, self.owner._pan[1] + py * scale)

    def _canvas_to_image(self, mouse):
        (ox, oy), _ = self.owner._canvas_rect()
        scale = self.owner._fit_scale * self.owner._zoom
        if scale <= 0:
            return None
        return ((mouse[0] - ox - self.owner._pan[0]) / scale, (mouse[1] - oy - self.owner._pan[1]) / scale)

    def _begin_pick(self, mode):
        if self.owner.engine.image is None:
            return self.owner._set_status('Open an image first.')
        if mode == 'area':
            self.owner._show_tool('axes')
            self.owner._set_calibration_method('smart')
        elif mode in ('calibration_x', 'calibration_y', 'x1', 'x2', 'y1', 'y2'):
            self.owner._set_calibration_method('manual')
        if mode in ('curve', 'manual', 'edit', 'delete') and self.owner.engine.active_dataset.locked:
            return self.owner._set_status('Unlock this dataset before editing its curve.')
        if mode == 'curve':
            self.owner._show_tool('extract')
        if mode in ('manual', 'edit', 'delete'):
            self.owner._edit_mode_toggled(True)
            return
        self.owner._region_first_corner = self.owner._region_press = None
        self.owner._drag_start = self.owner._drag_preview = None
        self.owner._region_alignment_preview = None
        if self.owner._edit_enabled:
            self.owner._set_edit_enabled(False)
        self.owner._calibration_sequence = []
        if mode in ('manual', 'edit', 'delete'):
            self.owner._show_tool('extract')
        elif mode == 'curve':
            self.owner._show_tool('extract')
        elif mode in ('area', 'x1', 'x2', 'y1', 'y2', 'calibration_x', 'calibration_y'):
            self.owner._show_tool('axes')
        self.owner._pick_mode = mode
        help_text = {'area': 'Select Plot: drag a rectangle or click two opposite corners around the chart axes. X1/Y1 use bottom-left, X2 bottom-right and Y2 top-left.', 'edit': 'Drag a marker to move it.', 'curve': 'Click directly on the curve stroke to sample its color.', 'manual': 'Click to add points. Use the magnifier for precision.', 'calibration_x': 'Click the known X tick to add or reposition a calibration point.', 'calibration_y': 'Click the known Y tick to add or reposition a calibration point.'}
        self.owner._set_status({'area': 'Select chart region.', 'curve': 'Pick curve color. Esc cancels.', 'calibration_x': 'Pick X tick.', 'calibration_y': 'Pick Y tick.'}.get(mode, 'Pick {} tick.'.format(mode.upper())), details=help_text.get(mode, 'Click the known {} tick on the image.'.format(mode.upper())) + ' Esc cancels.')
        if mode in ('calibration_x', 'calibration_y'):
            self.owner.set_control_visible(self.owner.calibration_hint, True)
            self.owner.set_control_value(self.owner.calibration_hint, help_text[mode] + ' Esc cancels.')
        elif mode in ('x1', 'x2', 'y1', 'y2'):
            self.owner.set_control_visible(self.owner.calibration_hint, True)
            self.owner.set_control_value(self.owner.calibration_hint, 'Click {} on a known axis tick. Esc cancels.'.format(mode.upper()))
        elif mode == 'area':
            self.owner.set_control_visible(self.owner.calibration_hint, True)
            self.owner.set_control_value(self.owner.calibration_hint, 'Select Plot: drag a rectangle or click two opposite corners. Esc cancels.')
        self.owner._paint_pointer()

    def _cancel_pick(self):
        transaction = getattr(self.owner, '_edit_transaction', None)
        if transaction is not None and transaction.isActive():
            transaction.cancel()
        had_draft = getattr(self.owner, '_calibration_draft', None) is not None
        self.owner._calibration_draft = None
        if had_draft:
            self.owner._selected_calibration_point = None
            self.owner._refresh_calibration_points()
        self.owner._reset_point_gesture()
        self.owner._pick_mode = None
        self.owner._calibration_pick = None
        self.owner._calibration_sequence = []
        if hasattr(self.owner, 'calibration_hint'):
            self.owner.set_control_value(self.owner.calibration_hint, '')
            self.owner.set_control_visible(self.owner.calibration_hint, False)
        self.owner._drag_start = self.owner._drag_preview = self.owner._drag_target = None
        self.owner._region_first_corner = self.owner._region_press = None
        self.owner._anchor_drag_target = self.owner._anchor_drag_preview = self.owner._hover_anchor = None
        if had_draft:
            self.owner._redraw()
        else:
            self.owner._paint_pointer()
        self.owner._set_status('Ready.')

    def _mouse_middle_down(self, *_args):
        if self.owner._mouse_in_canvas():
            self.owner._reset_point_gesture()
            self.owner._auto_fit = False
            self.owner._middle_drag = True
            self.owner._last_mouse = QCursor.pos().toTuple()
            self.owner._cursor_canvas = self.owner._cursor_pixel = None
            self.owner._hover_point = None
            self.owner._cursor_over_marker = False
            self.owner._redraw()

    def _mouse_middle_up(self, *_args):
        was_dragging = self.owner._middle_drag
        self.owner._middle_drag = False
        # Re-clamp screen-space axis labels after the fast translated gesture.
        if was_dragging:
            self.owner._redraw()
        self.owner._mouse_move()

    def _mouse_move(self, *_args):
        now = QCursor.pos().toTuple()
        if self.owner._middle_drag:
            if now == self.owner._last_mouse:
                return
            self.owner._pan[0] += now[0] - self.owner._last_mouse[0]
            self.owner._pan[1] += now[1] - self.owner._last_mouse[1]
            self.owner._last_mouse = now
            if self._view_redraw_pending:
                return  # The queued zoom paint will use this final pan too.
            if self._scene_layer is not None and self._scene_layer.exists() and self._scene_pan is not None:
                self._scene_layer.setTranslation(
                    self.owner._pan[0] - self._scene_pan[0],
                    self.owner._pan[1] - self._scene_pan[1])
                self.owner._paint_pointer()
            else:
                self.owner._redraw()
            return
        inside = self.owner._mouse_in_canvas()
        (ox, oy), (width, height) = self.owner._canvas_rect()
        sample = (now, inside, ox, oy, width, height, self.owner._fit_scale,
                  self.owner._zoom, tuple(self.owner._pan), self.owner._edit_enabled,
                  self.owner._pick_mode, self.owner._active_tool,
                  self.owner._anchor_drag_target, self.owner._point_press,
                  self.owner._drag_start, self.owner._drag_target)
        if sample == self._last_hover_sample:
            return
        self._last_hover_sample = sample
        local = (now[0] - ox, now[1] - oy)
        self.owner._cursor_canvas = local if inside and 0 <= local[0] < width and (0 <= local[1] < height) else None
        self.owner._cursor_over_marker = False
        point = self.owner._canvas_to_image(now) if inside and self.owner.engine.image is not None else None
        if self.owner._anchor_drag_target is not None:
            if point is not None:
                self.owner._anchor_drag_preview = (max(0.0, min(self.owner.engine.image.width - 1.0, point[0])), max(0.0, min(self.owner.engine.image.height - 1.0, point[1])))
                transaction = getattr(self.owner, '_edit_transaction', None)
                if transaction is not None and transaction.isActive():
                    context = transaction.context() or {}
                    key = context.get("key", self.owner._anchor_drag_target)
                    point_index = context.get("point_index")
                    transaction.update(
                        tuple(self.owner._anchor_drag_preview),
                        apply=lambda value: self.owner.engine.preview_move_anchor(
                            key, value[0], value[1], point_index=point_index),
                    )
                self.owner._preview_pixel = self.owner._anchor_drag_preview
            self.owner._hover_anchor = self.owner._anchor_drag_target
            self.owner._hover_point = None
            self.owner._cursor_over_marker = True
            self.owner._redraw()
            return
        if self.owner._point_press is not None:
            position = self.owner._canvas_to_image(now)
            if position is not None:
                self.owner._rubberband_end = position
                scale = max(0.001, self.owner._fit_scale * self.owner._zoom)
                if max((abs(position[i] - self.owner._point_press[i]) for i in (0, 1))) * scale >= 4:
                    self.owner._rubberband_active = True
            self.owner._hover_point = None
            self.owner._paint_pointer()
            return
        if point is not None:
            self.owner._preview_pixel = (max(0.0, min(self.owner.engine.image.width - 1.0, point[0])), max(0.0, min(self.owner.engine.image.height - 1.0, point[1])))
        if point is not None and 0 <= point[0] < self.owner.engine.image.width and (0 <= point[1] < self.owner.engine.image.height):
            self.owner._cursor_pixel = point
            self.owner._hover_anchor = self.owner._nearest_anchor(*point)
            self.owner._cursor_over_marker = bool(self.owner._hover_anchor) or cursor_hits_marker(self.owner.engine.datasets, *point, self.owner._fit_scale * self.owner._zoom, size_scale=self.owner._plot_preferences['marker_size_percent'] / 100.0, show_automatic=self.owner._plot_preferences['show_automatic_points'], show_manual=self.owner._plot_preferences['show_manual_points'])
            if self.owner._drag_start is not None or self.owner._drag_target is not None:
                self.owner._drag_preview = point
                if self.owner._drag_target is not None:
                    transaction = getattr(self.owner, '_edit_transaction', None)
                    if transaction is not None and transaction.isActive():
                        target = tuple(self.owner._drag_target)
                        transaction.update(
                            tuple(point),
                            apply=lambda value: self.owner.engine.preview_move_point(
                                target[0], target[1], value[0], value[1]),
                        )
            if self.owner._hover_anchor is None and self.owner._drag_target is None and self.owner._edit_enabled and (self.owner._pick_mode in (None, 'edit')) and (not self.owner.engine.active_dataset.locked):
                self.owner._hover_point = self.owner._nearest_point(*point)
            else:
                self.owner._hover_point = None
        else:
            self.owner._cursor_pixel = None
            self.owner._hover_point = None
            self.owner._hover_anchor = None
        self.owner._paint_pointer()

    def _canvas_pointer_tick(self):
        """Refresh hover and recover document keys missed by native callbacks."""
        self.owner._layout_canvas()
        self.owner._update_canvas_view_tool_states()
        if self.owner._middle_drag:
            self.owner._sync_canvas_cursor()
        else:
            self.owner._mouse_move()
        self.owner._poll_delete_key()
        schedule = getattr(self.owner.view, 'after_render', None)
        if callable(schedule):
            schedule(self.owner._sync_canvas_cursor)

    def _sync_canvas_cursor(self):
        cursor = getattr(self.owner, '_canvas_cursor', None)
        if cursor is None:
            return
        if not self.owner.winfo_exists() or not self.owner.isVisible():
            cursor.update(None)
            return
        if self.owner._canvas_view_tools_under_mouse() and (not (self.owner._middle_drag or self.owner._anchor_drag_target is not None)):
            cursor.update(None)
            return
        mode = 'move' if self.owner._middle_drag or self.owner._anchor_drag_target is not None else 'color_pick' if self.owner._pick_mode == 'curve' else 'point' if self.owner._hover_anchor is not None else 'blank' if self.owner._cursor_canvas is not None and self.owner._plot_preferences['show_crosshair'] else None
        (x, y), (width, height) = self.owner._canvas_rect()
        cursor.update(mode, (x, y, x + width, y + height), capture=self.owner._middle_drag or self.owner._anchor_drag_target is not None, screen_coordinates=self.owner._native_window_backend is not None)

    def _mouse_wheel(self, _sender, app_data):
        if self.owner._plot_preferences['mouse_wheel_zoom'] and self.owner._mouse_in_canvas() and (self.owner.engine.image is not None):
            factor = 1 + self.owner._plot_preferences.get('wheel_zoom_percent', 12) / 100.0
            self.owner._zoom_at(factor if app_data > 0 else 1 / factor, mouse=QCursor.pos().toTuple())

    def _zoom_at(self, factor, mouse=None):
        if self.owner.engine.image is None:
            return
        self.owner._auto_fit = False
        (ox, oy), (cw, ch) = self.owner._canvas_rect()
        local = (mouse[0] - ox, mouse[1] - oy) if mouse is not None else (cw / 2, ch / 2)
        old_scale = self.owner._fit_scale * self.owner._zoom
        anchor = ((local[0] - self.owner._pan[0]) / old_scale, (local[1] - self.owner._pan[1]) / old_scale)
        self.owner._zoom = max(0.05, min(40.0, self.owner._zoom * float(factor)))
        new_scale = self.owner._fit_scale * self.owner._zoom
        self.owner._pan = [local[0] - anchor[0] * new_scale, local[1] - anchor[1] * new_scale]
        self._queue_view_redraw()

    def _queue_view_redraw(self):
        """Accumulate wheel events in model space; paint once before a frame."""
        if self._view_redraw_pending:
            return
        self._view_redraw_pending = True
        runtime = getattr(self.owner.view, '_gui_runtime', None)
        register = getattr(runtime, 'addBeforeRenderCallback', None)
        if callable(register):
            if self._view_redraw_callback is None:
                self._view_redraw_callback = register(self._flush_view_redraw)
        else:
            self.owner.view.after(0, self._flush_view_redraw)

    def _flush_view_redraw(self):
        if getattr(self.owner, '_closed', False):
            runtime = getattr(self.owner.view, '_gui_runtime', None)
            remove = getattr(runtime, 'removeBeforeRenderCallback', None)
            if callable(remove) and self._view_redraw_callback is not None:
                remove(self._view_redraw_callback)
            self._view_redraw_callback = None
            self._view_redraw_pending = False
            return
        if self._view_redraw_pending:
            self._view_redraw_pending = False
            self.owner._redraw()

    def _fit_view(self):
        self.owner._auto_fit = True
        if self.owner.engine.image is None:
            return
        _, (cw, ch) = self.owner._canvas_rect()
        if cw <= 2 or ch <= 2:
            return
        iw, ih = self.owner.engine.image.size
        self.owner._fit_scale = min(cw / iw, ch / ih)
        self.owner._zoom = 1.0
        self.owner._pan = [(cw - iw * self.owner._fit_scale) / 2, (ch - ih * self.owner._fit_scale) / 2]
        self.owner._redraw()

    def _one_to_one(self):
        if self.owner.engine.image is None:
            return
        self.owner._auto_fit = False
        self.owner._fit_scale = 1.0
        self.owner._zoom = 1.0
        self.owner._pan = [0.0, 0.0]
        self.owner._redraw()

    def _paint_calibration_markers(self, painter, cw, ch):
        cal = self.owner.engine.calibration
        colors = {'x': (0, 120, 215, 255), 'y': (30, 150, 80, 255)}
        origin_drawn = False
        for key, anchor in self.owner._calibration_markers():
            x, y = self.owner._image_to_canvas(*self.owner._anchor_display_pixel(key))
            corner = key in ('x1', 'x2', 'y1', 'y2') and (cal.box_rect is not None or not getattr(cal, 'points_' + key[0]))
            origin = corner and key.endswith('1') and (cal.x1 is not None) and (cal.y1 is not None) and (abs(cal.x1.px - cal.y1.px) < 1e-09) and (abs(cal.x1.py - cal.y1.py) < 1e-09)
            if not origin or not origin_drawn:
                self.owner._draw_axis_marker(painter, (x, y), key[0], kind='origin' if origin else 'corner' if corner else 'tick', color=(140, 60, 180, 255) if origin else colors[key[0]])
            origin_drawn = origin_drawn or origin
            verified = key[0] in self.owner.engine.auto_tick_verified_axes or bool(getattr(cal, 'points_' + key[0]))
            estimated = corner and bool(getattr(cal, 'points_' + key[0])) and (self.owner._calibration_point_index(key) is None)
            value = ('~' if estimated else '') + self.owner._fmt_axis(anchor.value, key[0]) if verified else '?'
            if key.endswith('draft'):
                value = '?'
            label = '{} = {}'.format(self.owner._calibration_marker_label_key(key), value)
            label_width = len(label) * 7
            if key.startswith('x'):
                label_x, label_y = (x - label_width / 2, y + 14)
            else:
                label_x, label_y = (x - label_width - 14, y - 7)
            label_x = max(6, min(cw - label_width - 6, label_x))
            label_y = max(6, min(ch - 20, label_y))
            painter.drawText((label_x, label_y), label, color=colors[key[0]], size=14)

    def _redraw(self):
        self._view_redraw_pending = False
        if not self.owner._canvas_widget.exists():
            return
        self._last_hover_sample = None
        if self._scene_layer is None or not self._scene_layer.exists():
            self._scene_layer = RetainedCanvasLayer(self.owner._canvas_widget, translate=True)
        if self.owner._pointer_layer is None or not self.owner._pointer_layer.exists():
            self.owner._pointer_layer = RetainedCanvasLayer(self.owner._canvas_widget)
        painter = self._scene_layer.begin()
        self._scene_pan = tuple(self.owner._pan)
        _, (cw, ch) = self.owner._canvas_rect()
        if self.owner.engine.image is None or self.owner._texture_tag is None:
            self._scene_layer.finish()
            self.owner._paint_pointer()
            return
        iw, ih = self.owner.engine.image.size
        scale = self.owner._fit_scale * self.owner._zoom
        p0 = tuple(self.owner._pan)
        p1 = (self.owner._pan[0] + iw * scale, self.owner._pan[1] + ih * scale)
        painter.drawImage(self.owner._texture_tag, p0, p1)
        cal = self.owner.engine.calibration
        if self.owner.engine.plot_rect:
            left, top, right, bottom = self.owner._region_alignment_preview or self.owner.engine.plot_rect
            painter.drawRect(self.owner._image_to_canvas(left, top), self.owner._image_to_canvas(right, bottom), color=(30, 150, 80, 180), fill=(0, 0, 0, 0))
        self.owner._paint_detected_axis_ticks(painter)
        zoom_scale = max(0.05, scale)
        auto_metrics = self.owner._marker_metrics(zoom_scale, 'auto')
        manual_metrics = self.owner._marker_metrics(zoom_scale, 'manual')
        for ds in self.owner.engine.datasets:
            if not ds.visible:
                continue
            rgb = ds.curve_rgb or (220, 80, 40)
            color = (*rgb, 255)
            marker_style = getattr(ds, 'marker_style', 'circle')
            circles = str(marker_style or 'circle').strip().lower() == 'circle'
            if self.owner._plot_preferences['show_automatic_points']:
                points = ds.extracted_pixels[::max(1, len(ds.extracted_pixels) // 1200 or 1)]
                if circles:
                    self._scene_layer.drawCircles(
                        ((p0[0] + px * scale, p0[1] + py * scale) for px, py in points),
                        auto_metrics.radius, color=(255, 255, 255, 235), fill=color)
                else:
                    for px, py in points:
                        x, y = self.owner._image_to_canvas(px, py)
                        draw_marker(painter, (x, y), auto_metrics.radius, marker_style, color=color, outline=(255, 255, 255, 235), thickness=1.0)
            if self.owner._plot_preferences['show_manual_points']:
                if circles:
                    self._scene_layer.drawCircles(
                        ((p0[0] + p.px * scale, p0[1] + p.py * scale) for p in ds.manual_points),
                        manual_metrics.radius, color=(255, 255, 255, 235), fill=color)
                else:
                    for p in ds.manual_points:
                        x, y = self.owner._image_to_canvas(p.px, p.py)
                        draw_marker(painter, (x, y), manual_metrics.radius, marker_style, color=color, outline=(255, 255, 255, 235), thickness=1.0)
        self.owner._paint_calibration_markers(painter, cw, ch)
        if self.owner._hover_point is not None and self.owner._hover_point != self.owner._selected_point and self.owner._marker_visible(self.owner._hover_point[0]):
            try:
                hovered = self.owner._image_to_canvas(*self.owner.engine.point_pixels(*self.owner._hover_point))
                radius = self.owner._marker_metrics(max(0.05, scale), self.owner._hover_point[0]).selection_radius
                painter.drawEllipse(hovered, radius, color=(0, 120, 215, 220), fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self.owner._hover_point = None
        selected_points = set(self.owner.result_grid.selectedKeys())
        if self.owner._selected_point is not None:
            selected_points.add('{}:{}'.format(*self.owner._selected_point))
        for key in selected_points:
            selected_point = self.owner._key_point(key)
            if not self.owner._marker_visible(selected_point[0]):
                continue
            try:
                selected = self.owner._image_to_canvas(*self.owner.engine.point_pixels(*selected_point))
                radius = self.owner._marker_metrics(max(0.05, scale), selected_point[0]).selection_radius + 1
                painter.drawEllipse(selected, radius, color=(240, 130, 20, 255), fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self.owner._selected_point = None
        self._scene_layer.finish()
        self.owner._paint_pointer()

    def _paint_pointer(self):
        self.owner._sync_canvas_cursor()
        layer = self.owner._pointer_layer
        if layer is None or not layer.exists():
            return
        painter = layer.begin()
        preferences = getattr(self.owner, '_plot_preferences', PlotDigitizerPreferences.DEFAULTS)
        if self.owner._middle_drag:
            if preferences['show_magnifier']:
                self.owner._paint_preview(painter)
            layer.finish()
            return
        if self.owner._rubberband_active and self.owner._point_press is not None and (self.owner._rubberband_end is not None):
            a, b = (self.owner._image_to_canvas(*self.owner._point_press), self.owner._image_to_canvas(*self.owner._rubberband_end))
            painter.drawRect((min(a[0], b[0]), min(a[1], b[1])), (max(a[0], b[0]), max(a[1], b[1])), color=(0, 120, 215, 255), fill=(0, 120, 215, 35))
        if self.owner._drag_start is not None and self.owner._drag_preview is not None:
            a = self.owner._image_to_canvas(*self.owner._drag_start)
            b = self.owner._image_to_canvas(*self.owner._drag_preview)
            painter.drawRect((min(a[0], b[0]), min(a[1], b[1])), (max(a[0], b[0]), max(a[1], b[1])), color=(0, 120, 215, 255), fill=(0, 120, 215, 25))
        if self.owner._drag_target is not None and self.owner._drag_preview is not None and self.owner._marker_visible(self.owner._drag_target[0]):
            radius = self.owner._marker_metrics(max(0.05, self.owner._fit_scale * self.owner._zoom), self.owner._drag_target[0]).selection_radius + 1
            painter.drawEllipse(self.owner._image_to_canvas(*self.owner._drag_preview), radius, color=(240, 130, 20, 255), fill=(0, 0, 0, 0), thickness=2)
        elif self.owner._hover_point is not None and self.owner._marker_visible(self.owner._hover_point[0]):
            try:
                radius = self.owner._marker_metrics(max(0.05, self.owner._fit_scale * self.owner._zoom), self.owner._hover_point[0]).selection_radius
                painter.drawEllipse(self.owner._image_to_canvas(*self.owner.engine.point_pixels(*self.owner._hover_point)), radius, color=(0, 120, 215, 220), fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self.owner._hover_point = None
        anchor_key = self.owner._anchor_drag_target or self.owner._hover_anchor
        if anchor_key is not None and self.owner._active_tool == 'axes':
            anchor_pixel = self.owner._anchor_display_pixel(anchor_key)
            if anchor_pixel is not None:
                painter.drawEllipse(self.owner._image_to_canvas(*anchor_pixel), 9, color=(240, 130, 20, 255) if self.owner._anchor_drag_target else (0, 120, 215, 230), fill=(0, 0, 0, 0), thickness=2)
        _, (cw, ch) = self.owner._canvas_rect()
        color = (0, 120, 215, 180)
        local = self.owner._cursor_canvas
        if local is not None and preferences['show_crosshair']:
            x, y = local
            painter.drawLine((0, y), (cw, y), color=color)
            painter.drawLine((x, 0), (x, ch), color=color)
            if self.owner._cursor_over_marker:
                painter.drawRect((x - 4, y - 4), (x + 4, y + 4), color=(0, 120, 215, 255), fill=(255, 255, 255, 160), thickness=1)
        if preferences['show_magnifier']:
            self.owner._paint_preview(painter)
        layer.finish()

    def _paint_preview(self, painter):
        """Keep the last pointer sample visible at the configured magnification."""
        if self.owner.engine.image is None or self.owner._texture_tag is None:
            return
        iw, ih = self.owner.engine.image.size
        point = self.owner._preview_pixel or (iw / 2.0, ih / 2.0)
        _, (cw, ch) = self.owner._canvas_rect()
        preferences = getattr(self.owner, '_plot_preferences', PlotDigitizerPreferences.DEFAULTS)
        magnification = preferences.get('preview_zoom', 5)
        size = max(1, min(preferences.get('preview_size', 140), cw - 20, ch - 20))
        geometry = preview_geometry((iw, ih), point, self.owner._fit_scale * self.owner._zoom, size, magnification=magnification)
        p0 = (max(8, cw - size - 10), 10)
        p1 = (p0[0] + size, p0[1] + size)
        painter.drawRect((p0[0] - 1, p0[1] - 1), (p1[0] + 1, p1[1] + 1), color=QtFusionPalette.FOCUS, fill=QtFusionPalette.BASE)
        painter.drawImage(self.owner._texture_tag, (p0[0] + geometry.image_min[0], p0[1] + geometry.image_min[1]), (p0[0] + geometry.image_max[0], p0[1] + geometry.image_max[1]), uv_min=geometry.uv_min, uv_max=geometry.uv_max)
        mx, my = (p0[0] + size / 2.0, p0[1] + size / 2.0)
        color = (0, 120, 215, 180)
        if preferences.get('preview_crosshair', True):
            painter.drawLine((p0[0], my), (p1[0], my), color=color)
            painter.drawLine((mx, p0[1]), (mx, p1[1]), color=color)
        painter.drawText((p0[0] + 3, p0[1] + 3), '{}x'.format(magnification), color=(0, 120, 215, 255), size=12)

    def _load_texture(self, image=None):
        """Upload the already-decoded Pillow image to DearPyGui.

        Do not call ``dpg.load_image`` here.  The engine is the single owner of
        image decoding, which keeps standalone and WinUx-hosted behaviour
        identical and also supports every format Pillow can decode.
        """
        image = image or self.owner.engine.image
        if image is None:
            raise RuntimeError('No decoded image is available.')
        rgba = image.convert('RGBA')
        w, h = rgba.size
        if np is not None:
            pixels = (np.asarray(rgba, dtype=np.float32).reshape(-1) / 255.0).tolist()
        else:
            pixels = [channel / 255.0 for pixel in rgba.getdata() for channel in pixel]
        if self.owner._texture_tag is not None and hasattr(self.owner._texture_tag, 'delete'):
            self.owner._texture_tag.delete()
        self.owner._texture_tag = self.owner._texture_registry.addStaticTexture(int(w), int(h), pixels)

    def _layout_canvas(self):
        if not self.owner.winfo_exists() or not hasattr(self.owner, 'canvas_frame'):
            return
        try:
            bounds = item_rect(self.owner.canvas_panel)
            if bounds is None:
                return
            px, py, right, bottom = bounds
            pw, ph = (right - px, bottom - py)
            frame_bounds = item_rect(self.owner.canvas_frame)
            if frame_bounds is None:
                return
            fy = frame_bounds[1]
            if pw <= 2 or ph <= 2:
                return
            frame_size = (max(self.owner.CANVAS_MIN_WIDTH, int(pw - 1)), max(120, int(py + ph - fy - 1)))
            canvas_size = (max(1, frame_size[0] - 2), max(1, frame_size[1] - 2))
            size = (frame_size, canvas_size)
            if size == self.owner._canvas_size:
                return
            self.owner._canvas_size = size
            self.owner._layout_progress_text()
            self.owner._canvas_view_toolbar.move(max(6, (frame_size[0] - self.owner.CANVAS_VIEW_TOOLS_WIDTH) // 2), 6)
            self.owner._canvas_frame_widget.resize(*frame_size)
            self.owner._canvas_widget.resize(*canvas_size)
            self.owner._schedule_data_layout()
        except (KeyError, ValueError):
            return
        if self.owner._auto_fit and self.owner.engine.image is not None:
            self.owner.view.after(1, self.owner._fit_view)
        else:
            self.owner._redraw()

    def _schedule_data_layout(self):
        """Measure after page/selection layout, coalescing resize bursts."""
        if self.owner._active_tool != 'data' or self.owner._data_layout_pending or self.owner.data_worksheet.isDragging():
            return
        self.owner._data_layout_pending = True

        def deliver():
            self.owner._data_layout_pending = False
            self.owner._layout_data_grid()
        schedule = getattr(self.owner.view, 'after_render', None)
        if callable(schedule):
            schedule(deliver)
        else:
            self.owner.view.after(16, deliver)

    def _layout_data_grid(self):
        """Give the table remaining inspector space; scroll rows, not panels.

        Include the point editor when it is open so selecting a row does not
        push its editable coordinates below a fixed 300px table. Small windows
        may still scroll once the readable minimum table height is reached.
        """
        if not self.owner.winfo_exists() or self.owner._active_tool != 'data' or self.owner.data_worksheet.isDragging():
            return
        tail = self.owner.export_data_button
        if self.owner.control_visible(self.owner.point_editor_container):
            tail = self.owner.next_point_button
        panel = item_rect(self.owner.settings_panel)
        bottom_control = item_rect(tail)
        if panel is None or bottom_control is None:
            return
        scroll = QRetainedItem(self.owner.settings_panel).verticalScrollValue()
        free = panel[3] - bottom_control[3] - scroll - self.owner.REGION_GAP
        height = max(100, int(round(self.owner._data_grid_height + free)))
        if abs(height - self.owner._data_grid_height) <= 1:
            return
        self.owner._data_grid_height = height
        self.owner.result_grid.setFixedHeight(height)

    def layout_dialog(self):
        self.owner.view.after(0, self.owner._layout_canvas)
