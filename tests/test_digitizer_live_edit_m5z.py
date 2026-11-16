"""M5z: live Plot Digitizer edits use QEditTransaction with one undo command."""
import inspect
import unittest
from PIL import Image

from DearUIQt import QEditTransaction, __version__ as dearuiqt_version
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.ui.controllers.calibration import CalibrationController
from WinUx.plotdigitizer.ui.controllers.canvas import CanvasController


class DigitizerLiveEditM5zTests(unittest.TestCase):
    def test_release_version(self):
        self.assertGreaterEqual(tuple(map(int, dearuiqt_version.split("."))), (1, 108, 0))

    def make_engine(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new("RGB", (160, 120), "white"), "m5z.png")
        engine.set_plot_rect_with_corner_anchors((10, 10, 150, 110), detect_ticks=False)
        engine.set_axis_bounds({"x1": 0, "x2": 10, "y1": 0, "y2": 100})
        engine.add_manual_point(20, 100)
        engine._undo_stack.clear()
        engine._redo_stack.clear()
        return engine

    def test_live_point_updates_are_history_free_until_commit(self):
        engine = self.make_engine()
        before = engine.capture_edit_snapshot()
        tx = QEditTransaction()
        tx.begin("Move point", capture=engine.capture_edit_snapshot, restore=engine.restore_edit_snapshot,
                 context={"kind": "point", "target": ("manual", 0)}, value=(20, 100))
        tx.update((24, 94), apply=lambda value: engine.preview_move_point("manual", 0, *value))
        tx.update((28, 90), apply=lambda value: engine.preview_move_point("manual", 0, *value))
        self.assertEqual((28.0, 90.0), engine.point_pixels("manual", 0))
        self.assertEqual(0, engine.undo_stack.count())
        snap = tx.snapshot()
        tx.commit(value=(28, 90), apply=lambda _value: engine.commit_live_edit(
            "Move point", snap, event="data_changed", merge_id=1001,
            merge_key=("point", engine.active_dataset_index, "manual", 0), merge_window=0.65))
        self.assertEqual(1, engine.undo_stack.count())
        final = engine._snapshot()
        self.assertTrue(engine.undo())
        self.assertEqual(before, engine._snapshot())
        self.assertTrue(engine.redo())
        self.assertEqual(final, engine._snapshot())

    def test_cancel_live_point_restores_snapshot_without_history(self):
        engine = self.make_engine()
        before = engine.capture_edit_snapshot()
        tx = QEditTransaction()
        tx.begin("Move point", capture=engine.capture_edit_snapshot, restore=engine.restore_edit_snapshot)
        tx.update((35, 85), apply=lambda value: engine.preview_move_point("manual", 0, *value))
        self.assertNotEqual(before, engine._snapshot())
        self.assertTrue(tx.cancel())
        self.assertEqual(before, engine._snapshot())
        self.assertEqual(0, engine.undo_stack.count())

    def test_live_anchor_cancel_restores_calibration(self):
        engine = self.make_engine()
        before = engine.capture_edit_snapshot()
        tx = QEditTransaction()
        tx.begin("Move anchor", capture=engine.capture_edit_snapshot, restore=engine.restore_edit_snapshot)
        tx.update((16, 108), apply=lambda value: engine.preview_move_anchor("x1", *value))
        self.assertEqual((16.0, 108.0), (engine.calibration.x1.px, engine.calibration.x1.py))
        self.assertEqual(0, engine.undo_stack.count())
        tx.cancel()
        self.assertEqual(before, engine._snapshot())

    def test_preview_events_do_not_use_committed_event_names(self):
        engine = self.make_engine()
        events = []
        engine.subscribe(lambda event, _engine: events.append(event))
        engine.preview_move_point("manual", 0, 21, 99)
        engine.preview_move_anchor("x1", 11, 109)
        self.assertIn("data_preview_changed", events)
        self.assertIn("calibration_preview_changed", events)
        self.assertNotIn("data_changed", events)
        self.assertNotIn("calibration_changed", events)

    def test_plot_controllers_apply_live_engine_updates(self):
        canvas = inspect.getsource(CanvasController)
        calibration = inspect.getsource(CalibrationController)
        self.assertIn("engine.preview_move_point", canvas)
        self.assertIn("engine.preview_move_anchor", canvas)
        self.assertIn("engine.commit_live_edit", calibration)
        self.assertIn("capture=self.owner.engine.capture_edit_snapshot", calibration)


if __name__ == "__main__":
    unittest.main()
