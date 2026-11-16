"""Measure rendered splitter tracking and live frame cost without moving the OS cursor."""
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='splitter-tracking-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'splitter-tracking-logs')}):
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})

        def pump(count=20):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        def center(tag, axis):
            rect = view._splitter_item(tag).globalGeometry()
            return rect.x() + rect.width() / 2 if axis == 'x' else rect.y() + rect.height() / 2

        try:
            view._gui_runtime.show()
            view._gui_runtime.configureViewport(width=1240, height=900)
            pump(25)
            for panel in view.panels:
                panel.display(Path(profile), [FileItem('item_%04d.inp' % index,
                    Path(profile) / ('item_%04d.inp' % index), False, 100, 100) for index in range(200)])
            pump(45)
            print('READY: rendered 200 items per panel', flush=True)
            cases = (
                ('file/server', 'x', view.file_panel_separator, '_begin_file_panel_splitter_drag',
                 '_end_file_panel_splitter_drag', '_file_panel_splitter_hit_test'),
                ('file/jobs', 'y', view.horizontal_splitter, '_begin_horizontal_splitter_drag',
                 '_end_horizontal_splitter_drag', '_horizontal_splitter_native_hovered'),
                ('console', 'y', view.console_separator, '_begin_console_splitter_drag',
                 '_end_console_splitter_drag', '_console_splitter_native_hovered'),
                ('plot', 'x', view.job_plot_separator, '_begin_job_plot_splitter_drag',
                 '_end_job_plot_splitter_drag', '_job_plot_splitter_native_hovered'))
            for name, axis, tag, begin, end, hit in cases:
                if name == 'console':
                    view._top_ratio = .45
                    view._console_dock_area = 'bottom'
                    view._console_dock_scope = 'inner'
                    view._console_dock_height = 220
                    view.set_console_visible(True, persist=False, request_login=False)
                    view._apply_split_layout(force=True)
                    pump(25)
                elif name == 'plot':
                    view.set_console_visible(False, persist=False)
                    view._plot_dock_area = 'right'
                    view._plot_dock_scope = 'inner'
                    view._set_plot_dock_open(True)
                    view._apply_split_layout(force=True)
                    pump(25)
                origin = center(tag, axis)
                pointer = [origin]
                timings, errors = [], []
                print('MEASURING:', name, flush=True)
                with patch.object(view, '_splitter_input_blocked', return_value=False), \
                        patch.object(view, '_splitter_hit_activated', return_value=True), \
                        patch.object(view, '_left_mouse_button_down', return_value=True), \
                        patch.object(view, '_native_cursor_screen_' + axis, side_effect=lambda: pointer[0]), \
                        patch.object(view, '_file_panel_splitter_hit_test', return_value=name == 'file/server'), \
                        patch.object(view, '_horizontal_splitter_native_hovered', return_value=name == 'file/jobs'), \
                        patch.object(view, '_console_splitter_native_hovered', return_value=name == 'console'), \
                        patch.object(view, '_job_plot_splitter_native_hovered', return_value=name == 'plot'):
                    getattr(view, begin)(force_new_press=True)
                    with patch.object(view.left, 'resize', wraps=view.left.resize) as left_resize, \
                            patch.object(view.right, 'resize', wraps=view.right.resize) as right_resize:
                        # Include zero movement and reversals to catch press
                        # jumps, accumulated delta errors and release snapping.
                        deltas = [0] + list(range(1, 41)) + list(range(39, -41, -1)) + list(range(-39, 1))
                        for delta in deltas:
                            pointer[0] = origin + delta
                            start = time.perf_counter()
                            view.update()
                            timings.append((time.perf_counter() - start) * 1000)
                            errors.append(abs(center(tag, axis) - (origin + delta)))
                        minimum_targets = {
                            'file/server': (view.left_parent, view.right_parent),
                            'file/jobs': (view.top_region, view.bottom_region),
                            'console': (view.bottom_region, view.console_region),
                            'plot': (view.bottom_region, view.plot_region),
                        }[name]
                        for delta, target in zip((-100000, 100000), minimum_targets):
                            pointer[0] = origin + delta
                            view.update()
                            rect = view._splitter_item(target).globalGeometry()
                            extent = rect.width() if axis == 'x' else rect.height()
                            assert extent == 50, (name, 'minimum extent', target, extent)
                        left_resize.assert_not_called()
                        right_resize.assert_not_called()
                assert max(errors) <= 1.5, (name, 'tracking error', max(errors))
                before_release = center(tag, axis)
                getattr(view, end)()
                pump(8)
                assert abs(center(tag, axis) - before_release) <= 1.5, (name, 'release jump')
                final = view._splitter_item(minimum_targets[1]).globalGeometry()
                assert (final.width() if axis == 'x' else final.height()) == 50, (name, 'release expanded minimum pane')
                assert not any(getattr(panel.listview, '_owner_resize_interactive', False) for panel in view.panels)
                ordered = sorted(timings)
                p95 = ordered[int((len(ordered) - 1) * .95)]
                print('PASS:', name, 'both panes reach 50px; max tracking error %.2f px; frame median %.2f ms, p95 %.2f ms' %
                      (max(errors), statistics.median(timings), p95), flush=True)

            timings = []
            for step in list(range(24)) + list(range(23, -1, -1)):
                view._gui_runtime.configureViewport(width=1240 + step * 3, height=900 + step * 2)
                start = time.perf_counter()
                view.update()
                timings.append((time.perf_counter() - start) * 1000)
            pump(35)
            assert not view._layout_dirty
            assert view._last_content_size == view._content_size()
            print('PASS: native window resize settles to current content bounds; median %.2f ms, p95 %.2f ms' %
                  (statistics.median(timings), sorted(timings)[int(len(timings)*.95)]), flush=True)
        finally:
            view._end_file_panel_splitter_drag()
            view._end_horizontal_splitter_drag()
            view._end_console_splitter_drag()
            view._end_job_plot_splitter_drag()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
