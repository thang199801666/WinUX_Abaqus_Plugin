"""Native inline regex workbench colors/layout/lifecycle; no physical input."""
import ctypes
from ctypes import wintypes
import os
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
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.reference_chart_form import RegexTesterDialog
from WinUx.ui.components.regex_syntax import REGEX_GROUP_BACKGROUNDS
from WinUx.ui.components.regex_rich_edit import _Range, _CharFormat, _rgb, _PARENT_CLIP_LEASES, _com_method
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='regex-colors-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None

        def pump(count=10):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        try:
            view._gui_runtime.show()
            pattern = r'^(?P<kind>U|RF)([1-3])$'
            dialog = RegexTesterDialog(view, pattern, 'U1\nnoise\nRF3')
            dialog.show()
            pump(30)
            pattern_field = dialog.control_wrapper(dialog.pattern_edit)
            source_field = dialog.control_wrapper(dialog.text_edit)
            assert len(dialog._native_regex_fields) == 5
            assert all(field.hwnd and field._document.value for field in dialog._native_regex_fields)
            assert not hasattr(dialog, '_syntax_preview')
            assert not hasattr(dialog, '_match_preview_widget')
            assert len(dialog._last_live_result['matches']) == 0  # Multiline initially off.
            pattern_field._send(0x0437, 0, ctypes.byref(_Range(2, 4)))
            dialog.set_control_value(dialog.multiline, True)
            dialog._flag_changed()
            pump(15)
            assert len(dialog._last_live_result['matches']) == 2
            pattern = '(?m)' + pattern
            selection = _Range()
            pattern_field._send(0x0434, 0, ctypes.byref(selection))
            assert (selection.start, selection.end) == (6, 8)
            pattern_field._send(0x00C7)  # WM_UNDO: undo checkbox prefix, not source typing.
            pump(15)
            assert pattern_field.text() == pattern[4:]
            assert not dialog.control_value(dialog.multiline)
            dialog.set_control_value(dialog.multiline, True)
            dialog._flag_changed()
            pump(15)
            assert pattern_field.text() == pattern
            pattern_field.setText('(?is)(?m:U3)')
            dialog._input_changed()
            pump(15)
            assert dialog.control_value(dialog.ignore_case)
            assert dialog.control_value(dialog.dotall)
            assert not dialog.control_value(dialog.multiline), 'Scoped m became global'
            dialog.set_control_value(dialog.ignore_case, False)
            dialog._flag_changed()
            pump(15)
            assert pattern_field.text() == '(?s)(?m:U3)'
            pattern_field.setText(pattern)
            dialog._input_changed()
            pump(15)
            assert len({span[2] for span in pattern_field._format_signature[1]}) >= 4

            def background(field, offset):
                before = _Range()
                field._send(0x0434, 0, ctypes.byref(before))
                field._send(0x0437, 0, ctypes.byref(_Range(offset, offset + 1)))
                fmt = _CharFormat()
                fmt.size = ctypes.sizeof(fmt)
                field._send(0x043A, 1, ctypes.byref(fmt))
                field._send(0x0437, 0, ctypes.byref(before))
                return fmt.background

            assert background(pattern_field, 5) == _rgb(REGEX_GROUP_BACKGROUNDS[0])
            assert background(source_field, 0) == _rgb(REGEX_GROUP_BACKGROUNDS[0])
            assert background(source_field, 1) == _rgb(REGEX_GROUP_BACKGROUNDS[1])
            assert dialog._match_overlay is None, 'An input overlay was reintroduced'
            assert dialog.control_value(dialog.pattern_edit) == pattern
            if '--pointer' in sys.argv:
                user = ctypes.windll.user32
                owner = dialog._native_window_backend.winId(dialog.tag)
                cursor = wintypes.POINT()
                user.GetCursorPos(ctypes.byref(cursor))
                user.SetWindowPos(wintypes.HWND(owner), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                try:
                    rect = wintypes.RECT()
                    user.GetWindowRect(wintypes.HWND(source_field.hwnd), ctypes.byref(rect))

                    def click(x, y):
                        target = (int(x), int(y))
                        user.SetCursorPos(*target)
                        pump(2)
                        point = wintypes.POINT()
                        user.GetCursorPos(ctypes.byref(point))
                        assert (point.x, point.y) == target, 'Mouse interference: invalid physical test'
                        user.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(2)
                        user.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(10)

                    click(rect.left + 8, rect.top + 8)
                    assert source_field.hasFocus(), 'Inline editor did not receive a real click'
                    x, y = dpg.get_item_rect_min(dialog.quick_reference_search)
                    click(x + 20, y + 8)
                    assert int(user.GetFocus() or 0) == owner, 'Native child retained keyboard focus after parent click'
                    user.SendMessageW(wintypes.HWND(owner), 0x0102, ord('a'), 0)
                    pump(10)
                    assert 'a' in dialog.control_value(dialog.quick_reference_search)
                    assert source_field.text() == 'U1\nnoise\nRF3'
                    print('PASS: physical Rich Edit -> ImGui focus handoff and keyboard routing', flush=True)
                finally:
                    user.mouse_event(0x0004, 0, 0, 0, 0)
                    user.SetCursorPos(cursor.x, cursor.y)
            if '--screenshot' in sys.argv:
                from PIL import ImageGrab
                sample_pattern = r'(?m)^(\d{2}\:\d{2}\.\d{3})'
                sample_text = '\n'.join((
                    '01:10.538 Follow Up on Chapters',
                    '03:06.643 Follow Up on Reader View',
                    '05:16.596 Follow Up on Adding a Workout',
                    '08:33.877 Tiny Tip Show Hidden files',
                    '12:45.427 iOS Settings', '24:42.526 Amazon Ad',
                    '25:35.526 Security Bits', '1:38:10.349 Outro'))
                dialog.set_control_value(dialog.pattern_edit, sample_pattern)
                dialog.set_control_value(dialog.text_edit, sample_text)
                dialog.focus_control(dialog.pattern_edit)
                pump(5)
                dialog.set_control_value(dialog.quick_reference_search, '')
                dialog._input_changed()
                pump(15)
                assert len(dialog._last_live_result['matches']) == 7
                hwnd = dialog._native_window_backend.winId(dialog.tag)
                user32 = ctypes.windll.user32
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                pump(8)
                bounds = wintypes.RECT()
                assert user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(bounds))
                destination = temp / 'regex-workbench-colors.png'
                image = ImageGrab.grab()
                scale = image.width / user32.GetSystemMetrics(0)
                image.crop(tuple(round(value * scale) for value in
                    (bounds.left, bounds.top, bounds.right, bounds.bottom))).save(destination)
                print('SCREENSHOT', destination, flush=True)
                dialog.set_control_value(dialog.pattern_edit, pattern)
                dialog.set_control_value(dialog.text_edit, 'U1\nnoise\nRF3')
                dialog._input_changed()
                pump(15)
            dialog._next_match()
            assert 'MATCH 2 OF 2' in dialog.control_value(dialog.results_edit)
            assert '\nMATCH 1\n' in dialog.control_value(dialog.results_edit)
            assert '\nMATCH 2\n' in dialog.control_value(dialog.results_edit)
            dialog.set_control_value(dialog.match_jump_edit, '1')
            assert dialog._jump_to_match()
            assert dialog._selected_match_index == 0
            dialog.set_control_value(dialog.match_view_selector, 'Selected only')
            dialog._match_view_changed()
            pump(5)
            information = dialog.control_value(dialog.results_edit)
            assert 'MATCH 1 OF 2' in information
            assert "'RF3'" not in information
            assert 'Location' in information
            dialog.set_control_value(dialog.match_jump_edit, '2')
            assert dialog._jump_to_match()
            pump(5)
            assert 'MATCH 2 OF 2' in dialog.control_value(dialog.results_edit)
            assert "'RF3'" in dialog.control_value(dialog.results_edit)
            dialog.set_control_value(dialog.match_jump_edit, '999')
            assert not dialog._jump_to_match()
            assert dialog._selected_match_index == 1
            dialog.set_control_value(dialog.match_view_selector, 'All matches')
            dialog._match_view_changed()
            pump(5)
            assert '\nMATCH 1\n' in dialog.control_value(dialog.results_edit)
            source_field._send(0x0437, 0, ctypes.byref(_Range(-1, -1)))
            inserted = ctypes.create_unicode_buffer('\r\nU2')
            source_field._send(0x00C2, 1, inserted)
            pump(20)
            assert len(dialog._last_live_result['matches']) == 3
            source_field._send(0x00C7)
            pump(20)
            assert len(dialog._last_live_result['matches']) == 2, source_field.text()

            # The Function/Tools row must fit at the minimum supported width.
            dpg.configure_item(dialog.tag, width=980, height=640)
            pump(20)
            panel = QRetainedItem(dialog._test_panel_widget.tag).globalGeometry()
            function = QRetainedItem(dialog.function_selector).globalGeometry()
            tools = QRetainedItem(dialog.tools_selector).globalGeometry()
            assert function.width() >= 100 and tools.width() >= 100, (function, tools)
            assert function.right() <= tools.left()
            assert tools.right() <= panel.right() + 2, (tools, panel)
            example = QRetainedItem(dialog.subject_example_button).globalGeometry()
            clear = QRetainedItem(dialog.subject_clear_button).globalGeometry()
            assert example.right() <= clear.left()
            assert clear.right() <= panel.right() + 2
            assert example.width() >= 60 and clear.width() >= 45
            jump = QRetainedItem(dialog.match_jump_edit).globalGeometry()
            go = QRetainedItem(dialog.match_jump_button).globalGeometry()
            copy = QRetainedItem(dialog.copy_match_button).globalGeometry()
            assert jump.right() <= go.left() and go.right() <= copy.left()
            inspector = QRetainedItem(dialog._inspector_panel_widget.tag).globalGeometry()
            assert copy.right() <= inspector.right() + 2
            source = QRetainedItem(dialog.text_edit).globalGeometry()
            assert source.height() >= 180, source
            # Gutter and editor use the same native font/scroll coordinate space.
            original_text = source_field.text()
            source_field.setText('\n'.join('U1' for _ in range(100)))
            dialog._input_changed()
            pump(15)
            source_field.set_scroll_position(0, 200)
            pump(10)
            gutter_field = dialog.control_wrapper(dialog.line_numbers_edit)
            def assert_centered_number(start, length):
                left, right, rect = wintypes.POINT(), wintypes.POINT(), wintypes.RECT()
                gutter_field._send(0x00D6, ctypes.cast(ctypes.byref(left), ctypes.c_void_p).value, start)
                gutter_field._send(0x00D6, ctypes.cast(ctypes.byref(right), ctypes.c_void_p).value, start + length)
                ctypes.windll.user32.GetClientRect(wintypes.HWND(gutter_field.hwnd), ctypes.byref(rect))
                assert abs((left.x + right.x) / 2 - rect.right / 2) <= 2, (left.x, right.x, rect.right)
            assert_centered_number(0, 1)
            assert_centered_number(gutter_field.text().index('100'), 3)
            assert abs(gutter_field.scroll_position()[1] - source_field.scroll_position()[1]) <= 2
            # Navigation reveals distant matches without taking focus, moving
            # the subject selection or rewriting source text.
            dialog._selected_match_index = 0
            source_field._send(0x0437, 0, ctypes.byref(_Range(0, 1)))
            focused = ctypes.windll.user32.GetFocus()
            dialog._previous_match()  # Wrap to the final (100th) match.
            pump(5)
            assert dialog._selected_match_index == 99
            assert source_field.scroll_position()[1] > 1000
            assert dialog.control_wrapper(dialog.results_edit).scroll_position()[1] > 0
            selection = _Range()
            source_field._send(0x0434, 0, ctypes.byref(selection))
            assert (selection.start, selection.end) == (0, 1)
            assert ctypes.windll.user32.GetFocus() == focused
            assert source_field.text() == '\n'.join('U1' for _ in range(100))
            assert abs(gutter_field.scroll_position()[1] - source_field.scroll_position()[1]) <= 2
            dialog._next_match()  # Wrap back to the beginning.
            pump(5)
            assert dialog._selected_match_index == 0
            assert source_field.scroll_position()[1] < 30
            # Unicode offsets and end-of-document zero-width matches.
            pattern_field.setText(r'(?m)^')
            source_field.setText('🙂\n' * 100)
            dialog._input_changed()
            pump(15)
            dialog._selected_match_index = 0
            dialog._previous_match()
            pump(5)
            assert dialog._last_live_result['matches'][-1]['span'] == (200, 200)
            assert source_field.scroll_position()[1] > 1000
            # A long single line must reveal horizontally as well.
            pattern_field.setText('U1')
            source_field.setText('🙂' + 'x' * 300 + 'U1')
            dialog._input_changed()
            pump(15)
            dialog._next_match()
            assert source_field.scroll_position()[0] > 100
            scroll = source_field.scroll_position()
            assert not source_field.reveal_position(9999)
            assert source_field.scroll_position() == scroll
            pattern_field.setText(pattern)
            source_field.setText(original_text)
            dialog._input_changed()
            pump(15)

            dialog._set_tool_mode('substitution')
            pump()
            assert not ctypes.windll.user32.IsWindowVisible(wintypes.HWND(source_field.hwnd)), 'Native editor leaked into another mode'
            dialog._set_tool_mode('match')
            pump()
            assert ctypes.windll.user32.IsWindowVisible(wintypes.HWND(source_field.hwnd))

            dialog.focus_control(dialog.text_edit)
            pump(3)
            dialog.set_control_value(dialog.pattern_edit, '([bad')
            dialog._input_changed()
            pump(15)
            assert dialog._regex_error_position is not None
            assert background(pattern_field, dialog._regex_error_position) == _rgb((255, 215, 220))
            assert background(source_field, 0) == _rgb((255, 255, 255))
            assert 'Regex error' in dialog.control_value(dialog.results_edit)
            error_information = dialog.control_value(dialog.results_edit)
            dialog.set_control_value(dialog.match_view_selector, 'Selected only')
            dialog._match_view_changed()
            pump(5)
            assert dialog.control_value(dialog.results_edit) == error_information
            assert not dpg.get_item_configuration(dialog.match_jump_button)['enabled']
            dialog.set_control_value(dialog.match_view_selector, 'All matches')
            dialog._match_view_changed()
            dialog.set_control_value(dialog.pattern_edit, r'U\d')
            dialog._input_changed()
            pump(15)
            assert background(pattern_field, 0) != _rgb((255, 215, 220))
            assert len(dialog._last_live_result['matches']) == 1

            dialog._load_regex_example()
            pump(15)
            assert len(dialog._last_live_result['matches']) == 2
            assert dialog.control_value(dialog.input_position) == '4 lines · 15 chars'
            example_text, example_pattern = source_field.text(), pattern_field.text()
            dialog._clear_regex_subject()
            pump(15)
            assert source_field.text() == ''
            assert pattern_field.text() == example_pattern
            assert dialog.control_value(dialog.input_position) == '1 line · 0 chars'
            assert dialog.control_value(dialog.line_numbers_edit) == '1'
            source_field._send(0x00C7)
            pump(15)
            assert source_field.text() == example_text, 'Clear erased undo history'

            source_field.setText('🙂\nU1')
            dialog._input_changed()
            pump(15)
            source_field._send(0x0437, 0, ctypes.byref(_Range(4, 4)))
            pump(5)
            assert dialog.control_value(dialog.line_column_status) == 'Line 2, column 2'
            assert dialog.control_value(dialog.input_position) == '2 lines · 4 chars'
            source_field._send(0x0437, 0, ctypes.byref(_Range(0, 4)))
            native = ctypes.c_void_p()
            _com_method(source_field._document, 8, ctypes.c_long, ctypes.c_void_p)(
                source_field._document, ctypes.byref(native))
            try:
                _com_method(native, 59, ctypes.c_long, ctypes.c_long)(native, 1)
                pump(5)
                assert dialog.control_value(dialog.line_column_status) == 'Line 1, column 1'
            finally:
                _com_method(native, 2, wintypes.ULONG)(native)

            # Native formatting must not truncate the source/evaluation data.
            long_pattern = 'a' * 4200
            dialog.set_control_value(dialog.pattern_edit, long_pattern)
            dialog._input_changed()
            pump(15)
            assert dialog.control_value(dialog.pattern_edit) == long_pattern
            handles = [field.hwnd for field in dialog._native_regex_fields]
            dialog.destroy()
            dialog = None
            pump()
            assert all(not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)) for hwnd in handles)
            assert source_field._owner not in _PARENT_CLIP_LEASES
            print('PASS: inline pattern/subject colors, shared capture palette, live native edits/undo, '
                  'errors/recovery, minimum-width layout, hidden-mode isolation and HWND cleanup', flush=True)
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
