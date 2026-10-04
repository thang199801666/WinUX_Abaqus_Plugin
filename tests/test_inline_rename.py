"""Regression tests for Explorer-style rename selection logic.

This test loads native_rename.py directly so it stays runnable on CI machines
that do not have Dear PyGui installed.
"""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "WinUx"
    / "components"
    / "native_rename.py"
)
SPEC = importlib.util.spec_from_file_location("winux_native_rename", MODULE_PATH)
native_rename = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_rename)


class BasenameSelectionTests(unittest.TestCase):
    def test_file_selects_name_without_final_extension(self):
        self.assertEqual(native_rename.basename_select_end("report.inp"), 6)
        self.assertEqual(native_rename.basename_select_end("archive.tar.gz"), 11)

    def test_directory_selects_entire_label(self):
        self.assertEqual(
            native_rename.basename_select_end("folder.with.dots", is_dir=True),
            len("folder.with.dots"),
        )

    def test_dotfile_without_second_extension_selects_all(self):
        self.assertEqual(native_rename.basename_select_end(".gitignore"), 10)


    def test_split_name_matches_explorer_initial_editor(self):
        self.assertEqual(
            native_rename.split_rename_name("winux_launcher.py"),
            ("winux_launcher", ".py"),
        )
        self.assertEqual(
            native_rename.split_rename_name("archive.tar.gz"),
            ("archive.tar", ".gz"),
        )
        self.assertEqual(
            native_rename.split_rename_name(".gitignore"),
            (".gitignore", ""),
        )
        self.assertEqual(
            native_rename.split_rename_name("folder.with.dots", is_dir=True),
            ("folder.with.dots", ""),
        )

    def test_selection_uses_utf16_units_like_win32_edit(self):
        # U+1F600 occupies two UTF-16 code units, so "a😀" is 3 units.
        self.assertEqual(native_rename.basename_select_end("a😀.txt"), 3)


if __name__ == "__main__":
    unittest.main()


class RenameFontSizingTests(unittest.TestCase):
    def test_inline_rename_uses_measured_body_text_height(self):
        root = Path(__file__).resolve().parents[1] / "WinUx" / "components"
        list_source = (root / "explorer_list_view.py").read_text(encoding="utf-8")
        render_source = (root / "explorer_rendering.py").read_text(encoding="utf-8")
        rename_source = (root / "explorer_rename.py").read_text(encoding="utf-8")
        native_source = (root / "native_rename.py").read_text(encoding="utf-8")
        textbox_source = (root / "explorer_rename_textbox.py").read_text(encoding="utf-8")
        self.assertIn('dpg.get_text_size("Ag", font=font)', render_source)
        self.assertIn("font_px=self._rename_text_render_height()", rename_source)
        self.assertIn("_create_font_matching_height", native_source)
        self.assertIn("GetTextExtentPoint32W", native_source)
        self.assertIn("font_px=max(8", textbox_source)

