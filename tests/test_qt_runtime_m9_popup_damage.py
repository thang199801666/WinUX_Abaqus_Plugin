from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QObject, QRect
from DearUIQt.gui import QPopupSurface, QWindowHost


class QtRuntimeM9PopupDamageTests(unittest.TestCase):
    def test_show_and_hide_damage_are_coalesced_by_window_host(self):
        host = QWindowHost(geometry=(0, 0, 800, 600))
        surface = QPopupSurface()
        self.assertTrue(surface.beginShow(host=host, geometry=(10, 20, 120, 80)))
        self.assertEqual((10, 20, 120, 80), tuple((lambda r:(r.x(),r.y(),r.width(),r.height()))(host.takeDirtyRegion())))
        surface.markVisible()
        self.assertTrue(surface.invalidate((20, 30, 10, 10)))
        self.assertTrue(surface.invalidate((40, 50, 20, 15)))
        dirty = host.takeDirtyRegion()
        self.assertEqual((20, 30, 40, 35), (dirty.x(), dirty.y(), dirty.width(), dirty.height()))
        surface.beginHide()
        dirty = host.takeDirtyRegion()
        self.assertEqual((10, 20, 120, 80), (dirty.x(), dirty.y(), dirty.width(), dirty.height()))
        surface.markHidden()
        surface.delete(); host.delete()

    def test_hidden_surface_cannot_generate_stale_damage(self):
        host = QWindowHost(geometry=(0, 0, 800, 600))
        surface = QPopupSurface()
        self.assertFalse(surface.invalidate((1, 2, 3, 4)))
        self.assertFalse(host.hasPendingUpdate())
        surface.delete(); host.delete()

    def test_diagnostics_detect_visual_input_split_and_keep_generation(self):
        owner = QObject()
        host = QWindowHost(native_handle=123, geometry=(0, 0, 800, 600))
        surface = QPopupSurface()
        surface.beginShow(owner=owner, host=host, geometry=(3, 4, 50, 60))
        surface.markVisible(); surface.acquireInput()
        snap = surface.diagnosticsSnapshot()
        self.assertTrue(snap['consistent'])
        self.assertTrue(snap['visual_requested'])
        self.assertTrue(snap['input_owned'])
        self.assertEqual(123, snap['host_native_handle'])
        self.assertEqual((3, 4, 50, 60), snap['geometry'])
        self.assertEqual(1, snap['generation'])
        surface.beginHide(); surface.markHidden()
        surface.beginShow(owner=owner, host=host, geometry=(5, 6, 70, 80))
        self.assertEqual(2, surface.diagnosticsSnapshot()['generation'])
        surface.markHidden()
        surface.delete(); host.delete(); owner.delete()

    def test_window_host_diagnostics_never_consume_dirty_region(self):
        host = QWindowHost(native_handle=99, viewport_id='main', geometry=(1, 2, 300, 200))
        host.requestUpdate(QRect(4, 5, 20, 30))
        snap = host.diagnosticsSnapshot()
        self.assertEqual(99, snap['native_handle'])
        self.assertEqual('main', snap['viewport_id'])
        self.assertEqual((4, 5, 20, 30), snap['dirty_region'])
        self.assertTrue(host.hasPendingUpdate())
        host.delete()

    def test_qmenu_marks_only_row_damage_on_hover_transition(self):
        source = (ROOT / 'DearUIQt' / 'widgets' / 'menu.py').read_text(encoding='utf-8')
        self.assertIn('self._row_dirty_rects[action_id] = QRect(', source)
        self.assertIn('self._request_popup_update(self._row_dirty_region(action_id))', source)
        self.assertIn('def popupDiagnostics(self):', source)

    def test_combopopup_uses_same_dirty_row_contract(self):
        source = (ROOT / 'DearUIQt' / 'widgets' / 'combo_popup.py').read_text(encoding='utf-8')
        self.assertIn('self._request_popup_update(self._row_dirty_region(action_id))', source)
        self.assertIn('if self._row_hover_state.get(str(action_id)) == state:', source)


if __name__ == '__main__':
    unittest.main()
