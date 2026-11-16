from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QObject
from DearUIQt.gui import QPopupSurface, QWindowHost


class PopupSurfaceM7bTests(unittest.TestCase):
    def test_input_cannot_exist_without_visual_surface(self):
        surface = QPopupSurface()
        self.assertFalse(surface.acquireInput())
        self.assertTrue(surface.isConsistent())
        surface.delete()

    def test_show_binds_owner_host_visual_and_input_as_one_lifecycle(self):
        owner = QObject()
        host = QWindowHost(geometry=(100, 100, 500, 400))
        surface = QPopupSurface()
        self.assertTrue(surface.beginShow(owner=owner, host=host, geometry=(10, 20, 120, 80)))
        self.assertTrue(surface.visualRequested())
        self.assertTrue(surface.markVisible())
        self.assertTrue(surface.acquireInput())
        self.assertIs(surface.owner(), owner)
        self.assertIs(surface.host(), host)
        self.assertTrue(surface.ownsInput())
        self.assertTrue(surface.isConsistent())
        self.assertTrue(surface.beginHide())
        self.assertFalse(surface.ownsInput())
        self.assertTrue(surface.markHidden())
        self.assertIsNone(surface.owner())
        self.assertIsNone(surface.host())
        self.assertFalse(surface.visualRequested())
        self.assertTrue(surface.isConsistent())
        surface.delete(); host.delete(); owner.delete()

    def test_deleted_owner_is_guarded_not_kept_alive(self):
        owner = QObject()
        surface = QPopupSurface()
        surface.beginShow(owner=owner)
        owner.delete()
        self.assertIsNone(surface.owner())
        surface.markHidden()
        surface.delete()


if __name__ == '__main__':
    unittest.main()
