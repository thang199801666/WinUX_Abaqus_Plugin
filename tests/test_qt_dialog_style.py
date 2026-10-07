"""Static regressions for the shared Qt/Fusion dialog visual contract.

These checks intentionally avoid importing Dear PyGui so they can also run in
CI environments that do not load the bundled Windows-only DPG extension.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DIALOGS = ROOT / "WinUx" / "dialogs"


class QtDialogStyleTests(unittest.TestCase):
    def test_theme_has_one_shared_qt_control_contract(self):
        source = (DIALOGS / "theme.py").read_text(encoding="utf-8")
        for token in (
            "mvInputText", "mvInputInt", "mvInputFloat", "mvCombo", "mvListbox",
            "mvRadioButton", "mvSelectable", "mvProgressBar", "mvTable",
            "MIN_DIALOG_WIDTH", "MIN_DIALOG_HEIGHT", "NAV_WIDTH", "STATUS_HEIGHT",
        ):
            self.assertIn(token, source)

    def test_default_button_is_qt_neutral_with_focus_border(self):
        source = (DIALOGS / "theme.py").read_text(encoding="utf-8")
        start = source.index("def primary_button_theme")
        end = source.index("def secondary_button_theme", start)
        block = source[start:end]
        self.assertIn("p.BUTTON", block)
        self.assertIn("p.FOCUS", block)
        self.assertNotIn("p.HIGHLIGHT_TEXT", block)

    def test_sections_and_navigation_are_qt_like_not_white_cards(self):
        source = (DIALOGS / "theme.py").read_text(encoding="utf-8")
        section = source[source.index("def surface_theme"):source.index("def body_theme")]
        self.assertIn("DialogPalette.WINDOW_BG", section)
        self.assertIn("mvStyleVar_ChildBorderSize", section)
        self.assertIn("def navigation_theme", source)

    def test_qtdialog_owns_shared_form_status_navigation_and_button_box_layout(self):
        source = (DIALOGS / "qt_dialog.py").read_text(encoding="utf-8")
        for token in (
            "def note(", "def status_text(", "def navigation_panel(",
            "QDialogButtonBox-like layout", "QFormLayout-style row",
            "DialogMetrics.MIN_DIALOG_WIDTH", "freeze_rows=1",
        ):
            self.assertIn(token, source)

    def test_main_forms_use_shared_status_slots(self):
        files = (
            "bookmarks_form.py", "diagnostics_form.py", "job_edit_form.py",
            "job_manager_form.py", "login_form.py", "server_path_form.py",
            "site_manager_form.py", "sync_preview_form.py",
        )
        for name in files:
            source = (DIALOGS / name).read_text(encoding="utf-8")
            self.assertIn("status_text(", source, name)

    def test_settings_uses_shared_navigation_and_status_contract(self):
        source = (DIALOGS / "settings_form.py").read_text(encoding="utf-8")
        self.assertIn("self.navigation_panel", source)
        self.assertIn("self.status_text", source)
        self.assertIn("def _set_status", source)
        self.assertIn("error_text_theme", source)

    def test_form_labels_are_not_attached_to_builtin_combo_chrome(self):
        site = (DIALOGS / "site_manager_form.py").read_text(encoding="utf-8")
        odb = (DIALOGS / "odb_extract_form.py").read_text(encoding="utf-8")
        self.assertNotIn('dpg.add_combo([], label="Saved sites"', site)
        self.assertIn('"Saved sites"', site)
        self.assertNotIn('label="Combine operation"', odb)
        self.assertIn('"Combine operation"', odb)

    def test_dialog_density_is_compact_and_shared(self):
        source = (DIALOGS / "theme.py").read_text(encoding="utf-8")
        for token in (
            "LABEL_WIDTH = 104", "BUTTON_WIDTH = 82", "BUTTON_HEIGHT = 26",
            "FOOTER_HEIGHT = 48", "WINDOW_PAD_X = 10", "ROW_SPACING = 5",
            "NAV_WIDTH = 156",
        ):
            self.assertIn(token, source)

    def test_primary_dialogs_use_compact_preferred_sizes(self):
        login = (DIALOGS / "login_form.py").read_text(encoding="utf-8")
        settings = (DIALOGS / "settings_form.py").read_text(encoding="utf-8")
        blocking = (DIALOGS / "blocking_form.py").read_text(encoding="utf-8")
        self.assertIn("self.preferred_size = (420, 184)", login)
        self.assertIn("self.preferred_size = (760, 520)", settings)
        self.assertIn("self.preferred_size = (480,", blocking)


if __name__ == "__main__":
    unittest.main()
