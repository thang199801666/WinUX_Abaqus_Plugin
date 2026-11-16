from pathlib import Path
import unittest

from DearUIQt.docking import QDockDropController, QDockWindowLifecycle

ROOT = Path(__file__).resolve().parents[1]


class DockDropControllerM5iTests(unittest.TestCase):
    def test_semantic_dispositions_and_callbacks(self):
        events = []
        controller = QDockDropController(
            on_dock=lambda area, scope, result: events.append(("dock", area, scope, result.get("source"))),
            on_float=lambda result: events.append(("float", result.get("source"))),
            on_cancel=lambda result: events.append(("cancel", result.get("docked"))),
        )
        life = QDockWindowLifecycle("floating", True)
        controller.bindLifecycle(life)

        life.beginMove("left", "outer")
        life.endMove(docked=True, source="renderer")
        self.assertEqual(events[-1], ("dock", "left", "outer", "renderer"))

        life.setMode("floating")
        life.beginMove()
        life.endMove(docked=False, source="renderer")
        self.assertEqual(events[-1], ("float", "renderer"))

        life.beginMove()
        life.endMove(docked=True, canceled=True, source="renderer")
        self.assertEqual(events[-1], ("cancel", True))

    def test_source_is_optional_for_compatibility(self):
        results = []
        life = QDockWindowLifecycle("floating", True)
        life.moveFinished.connect(results.append)
        life.beginMove("right", "inner")
        life.endMove(docked=True)
        self.assertNotIn("source", results[-1])
        self.assertEqual(results[-1]["target"], {"area": "right", "scope": "inner"})

    def test_unbind_stops_execution(self):
        events = []
        controller = QDockDropController(on_float=lambda result: events.append(result))
        life = QDockWindowLifecycle("floating", True)
        controller.bindLifecycle(life)
        self.assertTrue(controller.unbindLifecycle())
        life.beginMove()
        life.endMove(docked=False)
        self.assertEqual(events, [])

    def test_feature_paths_bind_drop_controller(self):
        console = (ROOT / "WinUx/ui/behaviors/docking/console.py").read_text()
        plot = (ROOT / "WinUx/ui/behaviors/docking/plot.py").read_text()
        self.assertIn("QDockDropController", console)
        self.assertIn("_console_drop_controller().bindLifecycle(life)", console)
        self.assertIn("QDockDropController", plot)
        self.assertIn("_plot_drop_controller(key).bindLifecycle(life)", plot)

    def test_native_gesture_does_not_execute_request_dock_directly(self):
        native = (ROOT / "WinUx/dialogs/native_dock_hosts.py").read_text()
        start = native.index("    def _handle_dock_gesture")
        end = native.index("    def _close_completed", start)
        body = native[start:end]
        self.assertNotIn('self.post("request_dock")', body)
        self.assertIn('source="native"', native)


if __name__ == "__main__":
    unittest.main()
