"""M5x: continuous Plot Digitizer edits coalesce through QUndoCommand.mergeWith."""
import unittest
from PIL import Image

from WinUx.plotdigitizer.core.engine import DigitizerEngine


class DigitizerUndoMergeM5xTests(unittest.TestCase):
    def make_engine(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new("RGB", (160, 120), "white"), "m5x.png")
        engine.set_plot_rect_with_corner_anchors((10, 10, 150, 110), detect_ticks=False)
        engine.set_axis_bounds({"x1": 0, "x2": 10, "y1": 0, "y2": 100})
        for px, py in ((20, 100), (40, 82), (60, 70)):
            engine.add_manual_point(px, py)
        engine._undo_stack.clear()
        engine._redo_stack.clear()
        return engine

    def test_repeated_move_of_same_point_merges_to_one_step(self):
        engine = self.make_engine()
        before = engine._snapshot()
        engine.move_point("manual", 0, 21, 99)
        engine.move_point("manual", 0, 22, 98)
        engine.move_point("manual", 0, 23, 97)
        self.assertEqual(1, engine.undo_stack.count())
        final = engine._snapshot()
        self.assertTrue(engine.undo())
        self.assertEqual(before, engine._snapshot())
        self.assertTrue(engine.redo())
        self.assertEqual(final, engine._snapshot())

    def test_different_points_do_not_merge(self):
        engine = self.make_engine()
        engine.move_point("manual", 0, 21, 99)
        engine.move_point("manual", 1, 41, 81)
        self.assertEqual(2, engine.undo_stack.count())

    def test_intervening_edit_breaks_move_merge_chain(self):
        engine = self.make_engine()
        engine.move_point("manual", 0, 21, 99)
        engine.set_settings(engine.active_dataset.settings)
        # set_settings may be a no-op for an unchanged settings object, so use a
        # different-point move as the explicit intervening edit.
        engine.move_point("manual", 1, 41, 81)
        engine.move_point("manual", 0, 22, 98)
        self.assertEqual(3, engine.undo_stack.count())

    def test_repeated_anchor_move_merges_but_other_anchor_does_not(self):
        engine = self.make_engine()
        value = engine.calibration.x1.value
        engine.set_anchor("x1", 12, 108, value)
        engine.set_anchor("x1", 13, 107, value)
        self.assertEqual(1, engine.undo_stack.count())
        engine.set_anchor("x2", 149, 109, engine.calibration.x2.value)
        self.assertEqual(2, engine.undo_stack.count())

    def test_merge_window_expiry_creates_new_step(self):
        engine = self.make_engine()
        engine.move_point("manual", 0, 21, 99)
        command = engine.undo_stack.command(0)
        command._merge_stamp -= 1.0
        engine.move_point("manual", 0, 22, 98)
        self.assertEqual(2, engine.undo_stack.count())


if __name__ == "__main__":
    unittest.main()
