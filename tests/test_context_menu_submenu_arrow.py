from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "WinUx" / "components" / "explorer_context_menu.py"
FACADE = ROOT / "WinUx" / "components" / "explorer_list_view.py"


class ContextMenuSubmenuArrowTests(unittest.TestCase):
    def test_submenu_arrow_is_separate_solid_right_column(self):
        source = CONTEXT.read_text(encoding="utf-8") + "\n" + FACADE.read_text(encoding="utf-8")
        self.assertNotIn('label="▶"', source)
        self.assertIn('dpg.draw_triangle(', source)
        self.assertIn('fill=arrow_color', source)
        self.assertIn('arrow_width = 16 if children else 0', source)
        self.assertIn('text_width = base_text_width - arrow_width', source)
        self.assertIn('dpg.add_drawlist(', source)
        self.assertIn('dpg.add_item_clicked_handler(', source)
        self.assertIn('dpg.mvThemeCol_Text, p.TEXT', source)
        self.assertNotIn('                                      ›', source)

    def test_submenu_arrow_uses_compact_triangle(self):
        source = CONTEXT.read_text(encoding="utf-8") + "\n" + FACADE.read_text(encoding="utf-8")
        self.assertIn("(7, 12), (7, 16), (10, 14)", source)


if __name__ == "__main__":
    unittest.main()
