from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from WinUx.services.server_notepad_layout import ServerNotepadLayout
from WinUx.services.server_notepad_process import ServerNotepadWindow


class LayoutProgressTests(unittest.TestCase):
    def test_progress_preserves_value_and_hide_show_contract(self):
        view = SimpleNamespace(_load_progress_var=Mock(), load_progress=Mock(),
            _status_stats_separator=object())
        view.load_progress.winfo_ismapped.return_value = False
        layout = ServerNotepadLayout(view)
        layout._show_load_progress(True, 25)
        view._load_progress_var.set.assert_called_once_with(25.0)
        view.load_progress.pack.assert_called_once()
        layout._show_load_progress(False)
        view.load_progress.pack_forget.assert_called_once_with()


class HiddenNotepadLayoutTests(unittest.TestCase):
    def setUp(self):
        self.window = None
        self.patches = [patch.object(ServerNotepadWindow, '_load_local_state', return_value={}),
            patch.object(ServerNotepadWindow, '_activate_native_window'),
            patch.object(ServerNotepadWindow, 'deiconify'),
            patch.object(ServerNotepadWindow, '_save_active', autospec=True)]
        self.mocks = [value.start() for value in self.patches]
        try:
            self.window = ServerNotepadWindow(SimpleNamespace(pump=Mock()))
        except tk.TclError as exc:
            for value in reversed(self.patches):
                value.stop()
            self.skipTest('native Tk unavailable: {}'.format(exc))

    def tearDown(self):
        if self.window is not None:
            for identifier in self.window.tk.call('after', 'info'):
                self.window.after_cancel(identifier)
            self.window.destroy()
        for value in reversed(self.patches):
            value.stop()

    def test_hidden_window_constructs_menu_toolbar_docks_and_status(self):
        window = self.window
        self.assertEqual(window.state(), 'withdrawn')
        self.assertIsInstance(window._layout, ServerNotepadLayout)
        self.assertIs(window._layout.view, window)
        self.assertTrue(window.notebook.winfo_exists())
        self.assertTrue(window.toolbar.winfo_exists())
        self.assertTrue(window.statusbar.winfo_exists())
        self.assertTrue(window._tab_strip.frame.winfo_exists())
        self.assertIn('Editor_Save', window._toolbar_images)
        self.assertTrue(window.bind('<Control-s>'))
        self.assertTrue(window.bind('<F3>'))

    def test_save_menu_callback_and_progress_route_through_view(self):
        window = self.window
        menu = window.file_menu
        indices = [i for i in range(menu.index('end') + 1)
            if menu.type(i) == 'command' and menu.entrycget(i, 'label') == 'Save']
        self.assertEqual(len(indices), 1)
        menu.invoke(indices[0])
        self.mocks[-1].assert_called_once_with(window)
        window._show_load_progress(True, 42)
        self.assertEqual(window._load_progress_var.get(), 42.0)
        self.assertEqual(window.load_progress.winfo_manager(), 'pack')
        window._show_load_progress(False)
        self.assertEqual(window.load_progress.winfo_manager(), '')


if __name__ == '__main__':
    unittest.main()
