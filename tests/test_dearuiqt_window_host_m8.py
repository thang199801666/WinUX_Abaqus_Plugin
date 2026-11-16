import unittest

from DearUIQt.gui import QPopupSurface, QWindowHost
from DearUIQt.runtime import QGuiRuntime


class _Backend:
    pass


class WindowHostM8Tests(unittest.TestCase):
    def test_runtime_wrappers_share_one_host_per_backend(self):
        backend = _Backend()
        first = QGuiRuntime(backend)
        second = QGuiRuntime(backend)
        self.assertIs(first.windowHost(), second.windowHost())
        first.setNativeHandle(1234)
        self.assertEqual(second.windowHost().nativeHandle(), 1234)

    def test_different_backends_do_not_share_hosts(self):
        self.assertIsNot(QGuiRuntime(_Backend()).windowHost(),
                         QGuiRuntime(_Backend()).windowHost())

    def test_popup_surface_follows_host_lifetime(self):
        host = QWindowHost()
        surface = QPopupSurface()
        self.assertTrue(surface.beginShow(host=host, geometry=(10, 20, 30, 40)))
        self.assertTrue(surface.markVisible())
        self.assertTrue(surface.acquireInput())
        self.assertTrue(surface.isVisible())
        self.assertTrue(surface.ownsInput())
        host.close()
        self.assertFalse(surface.isVisible())
        self.assertFalse(surface.ownsInput())
        self.assertFalse(surface.visualRequested())
        self.assertIsNone(surface.host())
        self.assertTrue(surface.isConsistent())

    def test_reusing_surface_moves_host_close_connection(self):
        first = QWindowHost()
        second = QWindowHost()
        surface = QPopupSurface()
        surface.beginShow(host=first)
        surface.markVisible()
        surface.beginHide()
        surface.markHidden()
        surface.beginShow(host=second)
        surface.markVisible()
        first.close()
        self.assertTrue(surface.isVisible())
        second.close()
        self.assertFalse(surface.isVisible())

    def test_deleted_shared_host_is_recreated_for_all_wrappers(self):
        backend = _Backend()
        first = QGuiRuntime(backend)
        second = QGuiRuntime(backend)
        host = first.windowHost()
        host.delete()
        replacement = second.windowHost()
        self.assertIsNot(host, replacement)
        self.assertIs(first.windowHost(), replacement)


if __name__ == '__main__':
    unittest.main()
