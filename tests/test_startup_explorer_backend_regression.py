"""Explorer startup regressions runnable with ``abaqus python -m unittest``."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from DearUIQt.themes.factories import menu_button_theme, menu_image_button_theme


ROOT = Path(__file__).resolve().parents[1]


class ExplorerStartupRegressionTests(unittest.TestCase):
    def test_explorer_has_no_unbound_legacy_backend_references(self):
        source = ROOT / "WinUx/ui/components/explorer_list_view.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        references = [node.lineno for node in ast.walk(tree)
                      if isinstance(node, ast.Name) and node.id == "dpg"]
        self.assertEqual(references, [], "Use the Explorer's QGuiRuntime backend")

    def test_uncached_menu_themes_do_not_generate_shared_aliases(self):
        for factory in (menu_button_theme, menu_image_button_theme):
            with self.subTest(factory=factory.__name__), patch(
                    "DearUIQt.themes.factories.make_theme") as make:
                factory(backend=object(), cache=False)
                self.assertIsNone(make.call_args.kwargs["tag"])
                self.assertFalse(make.call_args.kwargs["cache"])

    def test_cached_menu_themes_keep_stable_aliases(self):
        for factory in (menu_button_theme, menu_image_button_theme):
            with self.subTest(factory=factory.__name__), patch(
                    "DearUIQt.themes.factories.make_theme") as make:
                factory(backend=object())
                first = make.call_args.kwargs["tag"]
                factory(backend=object())
                self.assertTrue(first)
                self.assertEqual(make.call_args.kwargs["tag"], first)
                self.assertTrue(make.call_args.kwargs["cache"])

    def test_uncached_menu_themes_preserve_explicit_alias(self):
        for factory in (menu_button_theme, menu_image_button_theme):
            with self.subTest(factory=factory.__name__), patch(
                    "DearUIQt.themes.factories.make_theme") as make:
                factory(backend=object(), tag="owned-menu-theme", cache=False)
                self.assertEqual(make.call_args.kwargs["tag"], "owned-menu-theme")


if __name__ == "__main__":
    unittest.main()
