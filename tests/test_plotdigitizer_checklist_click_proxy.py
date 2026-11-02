from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.ui.checklist import DigitizerCheckList


class Backend:
    def __init__(self):
        self.values = {11: False}
        self.set_calls = []

    def set_value(self, tag, value):
        self.values[tag] = bool(value)
        self.set_calls.append((tag, bool(value)))


class FakeChecklist:
    def __init__(self):
        self._deleted = False
        self.backend = Backend()
        self.checkboxes = {'row': 11}
        self.item = SimpleNamespace(checked=False, enabled=True)
        self.events = []
        self.current = None

    def itemForKey(self, key):
        return self.item if key == 'row' else None

    def _check_clicked(self, sender, checked, key):
        self.item.checked = bool(checked)
        self.events.append((sender, bool(checked), key))

    def setCurrentKey(self, key, select=True):
        self.current = key
        return True

    def _toggle_row_checkbox(self, key):
        return DigitizerCheckList._toggle_row_checkbox(self, key)


class ChecklistCaptionClickTests(unittest.TestCase):
    def test_caption_click_selects_row_and_toggles_checkbox(self):
        fake = FakeChecklist()
        self.assertTrue(DigitizerCheckList._caption_clicked(fake, 'row'))
        self.assertEqual(fake.current, 'row')
        self.assertTrue(fake.item.checked)
        self.assertTrue(fake.backend.values[11])
        self.assertEqual(fake.events, [(11, True, 'row')])

    def test_caption_click_rejects_disabled_row(self):
        fake = FakeChecklist()
        fake.item.enabled = False
        self.assertFalse(DigitizerCheckList._caption_clicked(fake, 'row'))
        self.assertIsNone(fake.current)
        self.assertFalse(fake.item.checked)
        self.assertEqual(fake.backend.set_calls, [])

    def test_caption_click_rejects_deleted_view(self):
        fake = FakeChecklist()
        fake._deleted = True
        self.assertFalse(DigitizerCheckList._caption_clicked(fake, 'row'))
        self.assertEqual(fake.backend.set_calls, [])


    def test_coordinate_combo_callback_never_changes_workflow_page(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py').read_text()
        block = source.split('    def _coordinate_mode_changed', 1)[1].split('    def _refresh_grid', 1)[0]
        self.assertIn('self._refresh_grid()', block)
        self.assertNotIn('_show_tool', block)
        self.assertNotIn('view.after', block)

    def test_no_application_wide_mouse_proxy_remains(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'checklist.py').read_text()
        self.assertNotIn('QGlobalInputBinding', source)
        self.assertNotIn('_proxy_row_click', source)
        self.assertIn('QItemInputBinding(canvas', source)


if __name__ == '__main__':
    unittest.main()
