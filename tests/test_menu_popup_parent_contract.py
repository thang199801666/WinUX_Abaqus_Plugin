"""Regression: QMenu popup owner must use QObject parent attribute, not parent()."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "DearUIQt" / "widgets" / "menu.py"


class MenuPopupParentContractTests(unittest.TestCase):
    def test_popup_does_not_call_qobject_parent_as_function(self):
        source = MENU.read_text(encoding="utf-8")
        self.assertNotIn("surface.beginShow(owner=self.parent()", source)
        self.assertIn('surface.beginShow(owner=getattr(self, "parent", None)', source)

    def test_qobject_parent_is_attribute_in_current_core_contract(self):
        source = (ROOT / "DearUIQt" / "core" / "object.py").read_text(encoding="utf-8")
        self.assertIn("self.parent = None", source)
        self.assertIn("self.setParent(parent)", source)


if __name__ == "__main__":
    unittest.main()
