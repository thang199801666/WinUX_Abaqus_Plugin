"""Exercise native editor key events, toggle themes and tab ownership."""
import ctypes
from ctypes import wintypes
import os
import sys
import unittest

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.runtime.dpg_callbacks import run_callback_jobs
from WinUx.ui import QPushButton, QCheckBox, QLineEdit, QTabWidget


class NativeComponentInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dpg.create_context()
        dpg.configure_app(manual_callback_management=True)
        cls.title = 'Qt component interaction test %d' % os.getpid()
        dpg.create_viewport(title=cls.title, width=700, height=420)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    @classmethod
    def tearDownClass(cls):
        dpg.destroy_context()

    def setUp(self):
        self.window = dpg.add_window(width=650, height=360)
        dpg.set_primary_window(self.window, True)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.delete()
        dpg.delete_item(self.window)

    def pump(self):
        dpg.render_dearpygui_frame()
        run_callback_jobs(dpg.get_callback_queue() or [])

    def test_button_and_checkbox_native_values_and_toggle_theme(self):
        button = QPushButton('Pin', parent=self.window, backend=dpg, checkable=True)
        box = QCheckBox('Show', parent=self.window, backend=dpg)
        self.widgets.extend([button, box])
        original_theme = dpg.get_item_theme(button.tag)
        button.click()
        self.assertTrue(button.isChecked())
        self.assertNotEqual(dpg.get_item_theme(button.tag), original_theme)
        button.setDisabled(True)
        self.assertFalse(button.click())
        self.assertTrue(button.isChecked())
        box.setCheckState(box.Checked)
        self.assertTrue(dpg.get_value(box.tag))
        box.click()
        self.assertFalse(dpg.get_value(box.tag))

    def test_real_enter_key_emits_return_and_finish_without_losing_text(self):
        edit = QLineEdit('value', parent=self.window, backend=dpg)
        self.widgets.append(edit)
        events = []
        edit.returnPressed.connect(lambda: events.append('return'))
        edit.editingFinished.connect(lambda: events.append('finished'))
        for _ in range(3):
            self.pump()
        edit.setFocus()
        for _ in range(3):
            self.pump()
        self.assertTrue(edit.hasFocus())
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = user32.FindWindowW(None, self.title)
        self.assertTrue(hwnd)
        user32.PostMessageW(hwnd, 0x0102, ord('X'), 0)
        for _ in range(3):
            self.pump()
        before_enter = edit.text()
        self.assertIn('X', before_enter)
        self.assertTrue(edit.isModified())
        user32.PostMessageW(hwnd, 0x0100, 13, 0x001c0001)
        user32.PostMessageW(hwnd, 0x0101, 13, 0xc01c0001)
        for _ in range(6):
            self.pump()
        self.assertEqual(events, ['return', 'finished'])
        self.assertEqual(edit.text(), before_enter)
        registry = edit._key_handlers
        edit.delete()
        self.assertFalse(dpg.does_item_exist(registry))

    def test_tabs_insert_hide_clear_and_delete_native_children(self):
        tabs = QTabWidget(parent=self.window, backend=dpg)
        self.widgets.append(tabs)
        first, second = tabs.addTab('First'), tabs.addTab('Second')
        tabs.setCurrentWidget(second)
        inserted = tabs.insertTab(0, 'New')
        self.assertEqual(dpg.get_item_children(tabs.tag, 1), [inserted.tag, first.tag, second.tag])
        self.assertIs(tabs.currentWidget(), second)
        tabs.setTabVisible(2, False)
        self.assertFalse(dpg.get_item_configuration(second.tag)['show'])
        self.assertIs(tabs.currentWidget(), first)
        first.delete()
        self.assertIs(tabs.currentWidget(), inserted)
        tabs.clear()
        self.assertEqual(tabs.count(), 0)
        self.assertTrue(all(not dpg.does_item_exist(page.tag) for page in (first, second, inserted)))

    def test_editor_readonly_password_and_placeholder_follow_retained_setters(self):
        edit = QLineEdit(parent=self.window, backend=dpg)
        self.widgets.append(edit)
        edit.setReadOnly(True)
        edit.setEchoMode(edit.Password)
        edit.setPlaceholderText('Password')
        config = dpg.get_item_configuration(edit.tag)
        self.assertTrue(config['readonly'])
        self.assertTrue(config['password'])
        self.assertEqual(config['hint'], 'Password')
        edit.setReadOnly(False)
        edit.setEchoMode(edit.Normal)
        self.assertFalse(dpg.get_item_configuration(edit.tag)['readonly'])
        self.assertFalse(dpg.get_item_configuration(edit.tag)['password'])
