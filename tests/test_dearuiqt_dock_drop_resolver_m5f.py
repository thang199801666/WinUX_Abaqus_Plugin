import unittest
from pathlib import Path

from DearUIQt.docking import QDockDropTargetResolver
from DearUIQt.widgets import DockDropPreview


class DockDropTargetResolverTests(unittest.TestCase):
    def setUp(self):
        self.bounds = (100.0, 50.0, 800.0, 500.0)

    @staticmethod
    def _center(rect):
        x, y, w, h = rect
        return (x + w * 0.5, y + h * 0.5)

    def test_inner_zone_resolves_semantic_target(self):
        point = self._center(DockDropPreview.zone_rectangles(self.bounds)["left"])
        self.assertEqual(
            QDockDropTargetResolver.resolve((point,), self.bounds),
            {"area": "left", "scope": "inner"})

    def test_outer_zone_resolves_outer_scope(self):
        point = self._center(DockDropPreview.outer_zone_rectangles(self.bounds)["bottom"])
        self.assertEqual(
            QDockDropTargetResolver.resolve((point,), self.bounds),
            {"area": "bottom", "scope": "outer"})

    def test_center_tile_remains_neutral(self):
        point = self._center(DockDropPreview.center_rect(self.bounds))
        self.assertIsNone(QDockDropTargetResolver.resolve((point,), self.bounds))

    def test_first_live_candidate_can_resolve(self):
        point = self._center(DockDropPreview.zone_rectangles(self.bounds)["right"])
        self.assertEqual(
            QDockDropTargetResolver.resolve(((0, 0), point), self.bounds)["area"],
            "right")

    def test_contains_is_renderer_independent(self):
        self.assertTrue(QDockDropTargetResolver.contains((100, 50), self.bounds))
        self.assertTrue(QDockDropTargetResolver.contains((900, 550), self.bounds))
        self.assertFalse(QDockDropTargetResolver.contains((99, 49), self.bounds))

    def test_preview_rect_side_geometry(self):
        bounds = (10.0, 20.0, 400.0, 200.0)
        self.assertEqual(QDockDropTargetResolver.previewRect(bounds, "left", 80, 1.0),
                         (10.0, 20.0, 80.0, 200.0))
        self.assertEqual(QDockDropTargetResolver.previewRect(bounds, "right", 80, 1.0),
                         (330.0, 20.0, 80.0, 200.0))
        self.assertEqual(QDockDropTargetResolver.previewRect(bounds, "top", 60, 1.0),
                         (10.0, 20.0, 400.0, 60.0))
        self.assertEqual(QDockDropTargetResolver.previewRect(bounds, "bottom", 60, 1.0),
                         (10.0, 160.0, 400.0, 60.0))

    def test_preview_extent_is_clamped(self):
        rect = QDockDropTargetResolver.previewRect((0, 0, 100, 80), "left", 90, 0.5)
        self.assertEqual(rect, (0.0, 0.0, 50.0, 80.0))

    def test_version_and_feature_code_use_shared_resolver(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 88, 0))
        root = Path(__file__).resolve().parents[1]
        for rel in ("WinUx/ui/behaviors/docking/console.py",
                    "WinUx/ui/behaviors/docking/plot.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertIn("QDockDropTargetResolver.resolve", text)
            self.assertNotIn("DockDropPreview.zone_hit", text)


if __name__ == "__main__":
    unittest.main()
