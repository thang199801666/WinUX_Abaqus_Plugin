"""Validation contract for Plot Digitizer Increase/Reduce target-count dialog."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.ui.sample_count_dialog import SampleCountDialog


class SampleCountDialogValidationTests(unittest.TestCase):
    def test_default_current_count_is_valid_for_both_modes(self):
        self.assertEqual(SampleCountDialog.validate_target("increase", 24, "24"), (24, ""))
        self.assertEqual(SampleCountDialog.validate_target("reduce", 24, "24"), (24, ""))

    def test_increase_cannot_go_below_current(self):
        target, error = SampleCountDialog.validate_target("increase", 24, "23")
        self.assertIsNone(target)
        self.assertIn("cannot be smaller", error)
        self.assertEqual(SampleCountDialog.validate_target("increase", 24, "25"), (25, ""))

    def test_reduce_cannot_go_above_current(self):
        target, error = SampleCountDialog.validate_target("reduce", 24, "25")
        self.assertIsNone(target)
        self.assertIn("cannot be larger", error)
        self.assertEqual(SampleCountDialog.validate_target("reduce", 24, "23"), (23, ""))

    def test_invalid_text_is_rejected(self):
        for value in ("", "12.5", "abc", "1e2", "-1", "0"):
            with self.subTest(value=value):
                target, error = SampleCountDialog.validate_target("increase", 10, value)
                self.assertIsNone(target)
                self.assertTrue(error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
