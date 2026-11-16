import unittest

from DearUIQt.docking import QDockPreviewController, QDockWindowLifecycle


class _Preview:
    def __init__(self):
        self.calls = []
    def prepare(self):
        self.calls.append(("prepare",))
        return True
    def show_zones(self, bounds, active=None, active_scope=None, preview_rect=None):
        self.calls.append(("show", bounds, active, active_scope, preview_rect))
        return True
    def hide(self):
        self.calls.append(("hide",))
    def destroy(self):
        self.calls.append(("destroy",))


class DockPreviewSignalBindingM5hTests(unittest.TestCase):
    def test_lifecycle_drives_guides_target_and_hide(self):
        preview = _Preview()
        controller = QDockPreviewController(preview=preview)
        life = QDockWindowLifecycle("floating", True)
        controller.bindLifecycle(
            life,
            lambda: (10, 20, 400, 300),
            lambda target: (10, 20, 120, 300) if target["area"] == "left" else None,
        )

        life.beginMove()
        self.assertTrue(controller.isVisible())
        self.assertIsNone(controller.target())

        life.setDropTarget("left", "outer")
        self.assertEqual(controller.target(), {"area": "left", "scope": "outer"})
        self.assertEqual(controller.previewRect(), (10.0, 20.0, 120.0, 300.0))

        life.endMove(docked=True)
        self.assertFalse(controller.isVisible())
        self.assertIsNone(controller.target())
        self.assertIsNone(controller.previewRect())

    def test_unbind_stops_signal_driven_rendering(self):
        preview = _Preview()
        controller = QDockPreviewController(preview=preview)
        life = QDockWindowLifecycle("floating", True)
        controller.bindLifecycle(life, lambda: (0, 0, 100, 100))
        self.assertTrue(controller.unbindLifecycle(life))
        count = len(preview.calls)
        life.beginMove("right", "inner")
        self.assertEqual(len(preview.calls), count)

    def test_destroy_disconnects_all_bindings(self):
        preview = _Preview()
        controller = QDockPreviewController(preview=preview)
        life = QDockWindowLifecycle("floating", True)
        controller.bindLifecycle(life, lambda: (0, 0, 100, 100))
        controller.destroy()
        count = len(preview.calls)
        life.beginMove("bottom", "inner")
        self.assertEqual(len(preview.calls), count)

    def test_feature_drag_paths_do_not_push_preview_true_directly(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        console = (root / "WinUx/ui/behaviors/docking/console.py").read_text()
        plot = (root / "WinUx/ui/behaviors/docking/plot.py").read_text()
        native = (root / "WinUx/dialogs/native_dock_hosts.py").read_text()
        self.assertNotIn("_set_console_dock_preview(True", console)
        self.assertNotIn("_set_plot_dock_preview(True", plot)
        self.assertNotIn("_set_console_dock_preview(True", native)
        self.assertNotIn("_set_plot_dock_preview(True", native)


if __name__ == "__main__":
    unittest.main()
