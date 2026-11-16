from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QPoint, QRect
from DearUIQt.gui import QWindowHost


class WindowHostM7aTests(unittest.TestCase):
    def test_geometry_mapping_uses_one_host_coordinate_contract(self):
        host = QWindowHost(geometry=(100, 200, 640, 480), native_handle=77, viewport_id='main')
        self.assertEqual(host.nativeHandle(), 77)
        self.assertEqual(host.viewportId(), 'main')
        p = host.mapToGlobal(QPoint(7, 9))
        self.assertEqual((p.x(), p.y()), (107, 209))
        q = host.mapFromGlobal(QPoint(125, 245))
        self.assertEqual((q.x(), q.y()), (25, 45))
        host.delete()

    def test_dirty_updates_are_coalesced_until_render_consumes_them(self):
        wakes = []
        host = QWindowHost(geometry=(0, 0, 800, 600), request_update=lambda: wakes.append('wake'))
        host.requestUpdate(QRect(10, 10, 20, 20))
        host.requestUpdate(QRect(25, 5, 20, 40))
        self.assertEqual(wakes, ['wake'])
        dirty = host.dirtyRegion()
        self.assertEqual((dirty.x(), dirty.y(), dirty.width(), dirty.height()), (10, 5, 35, 40))
        taken = host.takeDirtyRegion()
        self.assertEqual((taken.x(), taken.y(), taken.width(), taken.height()), (10, 5, 35, 40))
        self.assertFalse(host.hasPendingUpdate())
        host.requestUpdate(QRect(1, 1, 2, 2))
        self.assertEqual(wakes, ['wake', 'wake'])
        host.delete()

    def test_close_is_idempotent_and_rejects_future_updates(self):
        closed = []
        host = QWindowHost(close=lambda: closed.append(True))
        self.assertTrue(host.close())
        self.assertTrue(host.isClosed())
        self.assertFalse(host.close())
        self.assertFalse(host.requestUpdate(QRect(0, 0, 1, 1)))
        self.assertEqual(closed, [True])
        host.delete()


if __name__ == '__main__':
    unittest.main()
