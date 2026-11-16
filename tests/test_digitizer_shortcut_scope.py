"""Document shortcut ownership must compare canonical native IDs, not aliases."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class ShortcutScopeTests(unittest.TestCase):
    def test_alias_owner_accepts_numeric_canvas_ancestor(self):
        self.assertTrue(self.accepts('mvDrawlist', {200: 150, 150: 100}))

    def test_foreign_window_and_text_editors_are_rejected(self):
        self.assertFalse(self.accepts('mvDrawlist', {200: 300, 300: 0}))
        self.assertFalse(self.accepts('mvInputText', {200: 150, 150: 100}))

    def accepts(self, item_type, parents):
        backend = Mock()
        backend.get_alias_id.side_effect = lambda tag: 100 if tag == 'digitizer' else 0
        backend.get_item_parent.side_effect = lambda tag: parents.get(tag, 0)
        dialog = PlotDigitizerDialog.__new__(PlotDigitizerDialog)
        dialog.tag = 'digitizer'
        dialog.winfo_exists = lambda: True
        dialog._visible_state = True
        dialog.isVisible = lambda: True
        dialog._file_dialog = None
        dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 0)
        focused = SimpleNamespace(tag=200, itemType=lambda: item_type)
        with patch('WinUx.plotdigitizer.ui.dialog._renderer_backend', return_value=backend), \
                patch('DearUIQt.input_gate.native_modal_input_active', return_value=False), \
                patch('WinUx.plotdigitizer.ui.dialog.QRetainedItem.focusedItem', return_value=focused):
            return dialog._accepts_edit_shortcut()


if __name__ == '__main__':
    unittest.main()
