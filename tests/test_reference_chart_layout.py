"""Chart minimum-size/spacing regression: abaqus python tests/test_reference_chart_layout.py."""
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import validate_reference, make_formula_reference
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-chart-spacing-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp_root / 'chart-layout-logs')}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            xy = validate_reference({'name': '29-20170283A', 'points': [
                [index * .000123456789, index * .1234567890123] for index in range(13873)]})
            formula = make_formula_reference('regex(".*U3.*")', 'Formula')
            dialog = ReferenceChartDialog(view, [xy, formula], lambda result: None)

            def pump(frames=18):
                for _ in range(frames):
                    view.update()
                    time.sleep(.01)

            def rect(item):
                widget = dialog.control_wrapper(item)
                if widget is None:
                    widget = item
                value = widget.globalGeometry()
                return value.x(), value.y(), value.x() + value.width(), value.y() + value.height()

            def inside(outer, inner):
                assert inner[0] >= outer[0] - 2 and inner[1] >= outer[1] - 2, (outer, inner)
                assert inner[2] <= outer[2] + 2 and inner[3] <= outer[3] + 2, (outer, inner)

            try:
                dialog.show()
                assert dpg.get_item_configuration(dialog._workspace_grid.tag)['resizable']
                assert dialog._resizable
                assert not dpg.get_item_configuration(dialog.tag)['no_resize']
                for item, sizes in ((xy, ((980, 610), (1280, 720))),
                                    (formula, ((980, 610), (1280, 740)))):
                    dialog._load_item(item)
                    previous = None
                    for size in sizes:
                        dialog.resize(*size)
                        pump()
                        dialog._sync_pane_geometry()
                        pump()
                        if dialog._native_window_backend is not None:
                            hwnd = dialog._native_window_backend.winId(dialog.tag)
                            if hwnd:
                                getter = ctypes.windll.user32.GetWindowLongPtrW
                                getter.argtypes = [wintypes.HWND, ctypes.c_int]
                                getter.restype = ctypes.c_ssize_t
                                assert getter(wintypes.HWND(hwnd), -16) & 0x00040000, 'Native dialog lacks the resizable window frame'
                        library, editor = rect(dialog._library_panel_widget), rect(dialog._editor_panel_widget)
                        assert editor[0] - library[2] >= 4, (library, editor)
                        new, delete = rect(dialog.new_series_button), rect(dialog.delete_series_button)
                        assert delete[0] - new[2] >= 4, (new, delete)
                        inside(library, new)
                        inside(library, delete)
                        type_rect = rect(dialog.reference_type_combo)
                        inside(library, type_rect)
                        # Reference type now belongs to the Series control group
                        # directly below New/Delete; Series name is context-menu
                        # only and its compatibility buffer must stay hidden.
                        assert type_rect[1] >= max(new[3], delete[3]) - 2, (new, delete, type_rect)
                        assert not dialog.control_wrapper(dialog.name_edit).isVisible()
                        details = rect(dialog._details_panel_widget)
                        assert editor[1] <= details[1] + 4, (details, editor)
                        preview = rect(dialog._preview_frame)
                        assert preview[0] - editor[2] >= 4, (editor, preview)
                        plot_rect = rect(dialog._preview_plot)
                        message_rect = rect(dialog._preview_message)
                        inside(preview, plot_rect)
                        inside(preview, message_rect)
                        header_rect = rect(dialog._preview_header)
                        assert plot_rect[1] - header_rect[3] >= 10, ('Plot was not lowered', header_rect, plot_rect)
                        for axis in (dialog._preview_x_axis, dialog._preview_y_axis):
                            assert dpg.get_item_configuration(axis.tag)['no_highlight'], 'Axis hover fill can obscure frame'
                        # Preview summary belongs to the compact header; the
                        # chart itself should then use the body all the way to
                        # the bottom of the pane.
                        assert message_rect[3] <= plot_rect[1] + 3, (message_rect, plot_rect)
                        assert preview[3] - plot_rect[3] <= 8, (preview, plot_rect)
                        inside(library, rect(dialog._saved_list_view))
                        widths = (library[2] - library[0], editor[2] - editor[0], preview[2] - preview[0])
                        assert dialog._authoring_splitter.count() == 2
                        assert widths[1] >= 360, ('Worksheet is too narrow', widths)
                        assert widths[2] >= 300, ('Preview is too narrow', widths)
                        assert widths[2] > widths[1], ('Preview should be the dominant authoring pane', widths)
                        if item is xy:
                            assert dialog.data_table.model.row_count >= 13873
                            assert len(xy['points']) == 13873
                        if previous is not None:
                            assert abs(widths[0] - previous[0]) <= 2, ('Series width changed', previous, widths)
                            assert abs(widths[1] - previous[1]) <= 4, ('XY Data should stay near its preferred width', previous, widths)
                            assert widths[2] - previous[2] >= 250, ('Preview should absorb almost all resize width', previous, widths)
                        previous = widths
                        if item is formula:
                            assert dpg.get_item_rect_size(dialog.formula_functions)[1] >= 100
                            inside(editor, rect(dialog._formula_functions_view))
                dialog.resize(980, 610)
                dialog._toggle_formula_builder()
                pump()
                helper = rect(dialog._formula_builder_widget)
                for control in (dialog.generate_direction, dialog.generate_formula_button,
                                dialog.generate_antialiasing, dialog.generate_reverse_u, dialog.generate_reverse_rf):
                    inside(helper, rect(control))
                assert dpg.get_item_rect_size(dialog.formula_functions)[1] >= 100, dpg.get_item_rect_size(dialog.formula_functions)
                if '--pointer' in sys.argv:
                    dialog.resize(1080, 740)
                    pump()
                    user32 = ctypes.windll.user32
                    hwnd = dialog._native_window_backend.winId(dialog.tag)
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                    current = ctypes.windll.kernel32.GetCurrentThreadId()
                    attached = user32.AttachThreadInput(current, thread, True)
                    try:
                        user32.SetForegroundWindow(wintypes.HWND(hwnd))
                    finally:
                        if attached:
                            user32.AttachThreadInput(current, thread, False)
                    pump()
                    assert int(user32.GetForegroundWindow() or 0) == hwnd, 'Physical test requires an interactive desktop'
                    left, right = rect(dialog._library_panel_widget), rect(dialog._editor_panel_widget)
                    start = ((left[2] + right[0]) // 2, left[1] + 90)
                    user32.SetCursorPos(*start)
                    pump(3)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    try:
                        pump(3)
                        for step in range(1, 11):
                            user32.SetCursorPos(start[0] + step * 6, start[1])
                            pump(2)
                    finally:
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                    pump()
                    moved = rect(dialog._library_panel_widget)
                    assert moved[2] - left[2] >= 30, ('Divider drag did not resize the library', left, moved)
                    assert abs(moved[0] - left[0]) <= 1, 'Divider drag moved the dialog'
                    editor_width = dialog._editor_panel_widget.globalGeometry().width()
                    assert abs(dialog._formula_feedback.wrapWidth() - (editor_width - 4)) <= 2
                    width = moved[2] - moved[0]
                    dialog.resize(1200, 760)
                    pump()
                    resized = rect(dialog._library_panel_widget)
                    assert abs((resized[2] - resized[0]) - width) <= 3, 'Host resize reset the user divider width'
                print('PASS: compact Series/XY panes, Preview-dominant stretch layout, adjustable XY width, '
                      'header summaries, full-height Preview, 13,873-point worksheet and contained controls')
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
