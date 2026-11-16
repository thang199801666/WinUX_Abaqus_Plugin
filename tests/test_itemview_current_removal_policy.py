"""Item views opt out of QItemSelectionModel neighbor-current fallback."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ItemViewRemovalPolicySourceTests(unittest.TestCase):
    def test_base_item_view_disables_current_removal_fallback(self):
        text = (ROOT / "DearUIQt/modelview/base.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("setCurrentRemovalFallbackEnabled(False)"), 3)

    def test_tree_view_disables_current_removal_fallback(self):
        text = (ROOT / "DearUIQt/modelview/tree.py").read_text(encoding="utf-8")
        self.assertIn("setCurrentRemovalFallbackEnabled(False)", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
