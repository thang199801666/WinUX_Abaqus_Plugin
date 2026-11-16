"""M5w: Plot Digitizer edit history uses DearUIQt QUndoCommand/QUndoStack."""
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from DearUIQt import QUndoCommand, QUndoStack
from WinUx.plotdigitizer.core.engine import DigitizerEngine


class DigitizerUndoCommandM5wTests(unittest.TestCase):
    def make_engine(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new("RGB", (160, 120), "white"), "m5w.png")
        engine.set_plot_rect_with_corner_anchors((10, 10, 150, 110), detect_ticks=False)
        engine.set_axis_bounds({"x1": 0, "x2": 10, "y1": 0, "y2": 100})
        for px, py in ((20, 100), (40, 82), (60, 70), (80, 55), (100, 43), (120, 25), (140, 18)):
            engine.add_manual_point(px, py)
        engine._undo_stack.clear()
        engine._redo_stack.clear()
        return engine

    def test_engine_owns_qundostack_and_public_labels(self):
        engine = self.make_engine()
        self.assertIsInstance(engine.undo_stack, QUndoStack)
        engine.move_point("manual", 0, 22, 98)
        command = engine.undo_stack.command(engine.undo_stack.index() - 1)
        self.assertIsInstance(command, QUndoCommand)
        self.assertEqual("Move point", engine.undo_text)
        self.assertTrue(engine.can_undo)
        self.assertFalse(engine.can_redo)
        engine.undo()
        self.assertEqual("Move point", engine.redo_text)

    def assert_roundtrip(self, mutate, expected_label):
        engine = self.make_engine()
        before = engine._snapshot()
        mutate(engine)
        after = engine._snapshot()
        self.assertNotEqual(before, after)
        self.assertEqual(expected_label, engine.undo_text)
        self.assertTrue(engine.undo())
        self.assertEqual(before, engine._snapshot())
        self.assertTrue(engine.redo())
        self.assertEqual(after, engine._snapshot())

    def test_targeted_edits_are_qundo_commands(self):
        cases = (
            (lambda e: e.move_point("manual", 1, 44, 80), "Move point"),
            (lambda e: e.remove_points([("manual", 1), ("manual", 3)]), "Delete points"),
            (lambda e: e.reduce_samples(3.0), "Reduce samples"),
            (lambda e: e.set_anchor("x1", 12, 108, e.calibration.x1.value), "Calibrate axis"),
        )
        for mutate, label in cases:
            with self.subTest(label=label):
                self.assert_roundtrip(mutate, label)

    def test_legacy_history_views_remain_read_compatible(self):
        engine = self.make_engine()
        engine.move_point("manual", 0, 22, 98)
        self.assertEqual(1, len(engine._undo_stack))
        self.assertEqual("Move point", engine._undo_stack[-1][0])
        engine.undo()
        self.assertEqual(1, len(engine._redo_stack))
        self.assertEqual("Move point", engine._redo_stack[-1][0])

    def test_pdg_history_roundtrip_rebuilds_qundostack(self):
        engine = self.make_engine()
        engine.move_point("manual", 0, 22, 98)
        engine.remove_points([("manual", 2)])
        expected = engine._snapshot()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.pdg"
            engine.save_project(path)
            restored = DigitizerEngine()
            restored.load_project(path)
        self.assertIsInstance(restored.undo_stack, QUndoStack)
        self.assertEqual(expected, restored._snapshot())
        self.assertEqual("Delete points", restored.undo_text)
        self.assertTrue(restored.undo())
        self.assertEqual("Move point", restored.undo_text)
        self.assertTrue(restored.redo())
        self.assertEqual(expected, restored._snapshot())

    def test_no_plot_ui_reads_legacy_history_lists_for_labels(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx/plotdigitizer/ui/controllers/data.py").read_text(encoding="utf-8")
        self.assertNotIn("engine._undo_stack[-1]", source)
        self.assertNotIn("engine._redo_stack[-1]", source)
        self.assertIn("engine.undo_text", source)
        self.assertIn("engine.redo_text", source)


if __name__ == "__main__":
    unittest.main()
