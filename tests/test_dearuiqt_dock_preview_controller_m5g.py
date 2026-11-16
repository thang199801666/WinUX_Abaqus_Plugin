import unittest
from pathlib import Path

from DearUIQt.docking import QDockPreviewController


class _FakePreview:
    def __init__(self):
        self.prepared = 0
        self.zone_calls = []
        self.result_calls = []
        self.hidden = 0
        self.destroyed = 0

    def prepare(self):
        self.prepared += 1
        return True

    def show_zones(self, bounds, *, active=None, active_scope=None, preview_rect=None):
        self.zone_calls.append((bounds, active, active_scope, preview_rect))
        return True

    def show(self, x, y, width, height, *, inset=True):
        self.result_calls.append(((x, y, width, height), inset))
        return True

    def hide(self):
        self.hidden += 1

    def destroy(self):
        self.destroyed += 1


class DockPreviewControllerTests(unittest.TestCase):
    def test_guides_only_state_is_owned_by_controller(self):
        preview = _FakePreview()
        controller = QDockPreviewController(preview=preview)
        self.assertTrue(controller.show((10, 20, 300, 200)))
        self.assertTrue(controller.isVisible())
        self.assertIsNone(controller.target())
        self.assertEqual(preview.zone_calls[-1], ((10.0, 20.0, 300.0, 200.0), None, None, None))

    def test_active_target_scope_and_result_are_retained(self):
        preview = _FakePreview()
        controller = QDockPreviewController(preview=preview)
        rect = (10, 20, 90, 200)
        self.assertTrue(controller.show(
            (10, 20, 300, 200), {"area": "left", "scope": "outer"},
            preview_rect=rect))
        self.assertEqual(controller.target(), {"area": "left", "scope": "outer"})
        self.assertEqual(controller.activeArea(), "left")
        self.assertEqual(controller.activeScope(), "outer")
        self.assertEqual(controller.previewRect(), tuple(map(float, rect)))
        self.assertEqual(preview.zone_calls[-1][1:], ("left", "outer", tuple(map(float, rect))))

    def test_invalid_target_degrades_to_guides_only(self):
        preview = _FakePreview()
        controller = QDockPreviewController(preview=preview)
        self.assertTrue(controller.show((0, 0, 100, 80), {"area": "center", "scope": "outer"}))
        self.assertIsNone(controller.target())
        self.assertEqual(preview.zone_calls[-1][1:3], (None, None))

    def test_hide_clears_presentation_transaction(self):
        preview = _FakePreview()
        controller = QDockPreviewController(preview=preview)
        controller.show((0, 0, 100, 80), "right", scope="inner", preview_rect=(50, 0, 50, 80))
        self.assertTrue(controller.hide())
        self.assertFalse(controller.isVisible())
        self.assertIsNone(controller.bounds())
        self.assertIsNone(controller.target())
        self.assertIsNone(controller.previewRect())
        self.assertEqual(preview.hidden, 1)

    def test_result_only_path_uses_same_renderer_owner(self):
        preview = _FakePreview()
        controller = QDockPreviewController(preview=preview)
        self.assertTrue(controller.showResult((1, 2, 30, 40), inset=False))
        self.assertEqual(preview.result_calls[-1], ((1.0, 2.0, 30.0, 40.0), False))
        self.assertTrue(controller.isVisible())

    def test_version_and_features_use_controller_instead_of_show_zones(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 89, 0))
        root = Path(__file__).resolve().parents[1]
        for rel in ("WinUx/ui/behaviors/docking/console.py",
                    "WinUx/ui/behaviors/docking/plot.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertIn("_dock_preview_controller", text)
            self.assertNotIn("preview.show_zones", text)


if __name__ == "__main__":
    unittest.main()
