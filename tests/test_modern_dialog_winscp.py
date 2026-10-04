from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODERN = ROOT / "WinUx" / "dialogs" / "modern.py"
BLOCKING = ROOT / "WinUx" / "dialogs" / "blocking_form.py"
VIEW = ROOT / "WinUx" / "view.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
LISTVIEW = ROOT / "WinUx" / "components" / "explorer_list_view.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


class ModernDialogRegressionTests(unittest.TestCase):
    def test_modern_framework_owns_fixed_action_metrics(self):
        source = MODERN.read_text(encoding="utf-8")
        self.assertIn("class FixedActionButton", source)
        self.assertIn("BUTTON_WIDTH = 94", source)
        self.assertIn("BUTTON_HEIGHT = 32", source)
        self.assertIn("pack_propagate(False)", source)
        self.assertIn("grid_propagate(False)", source)

    def test_primary_button_caption_does_not_depend_on_ttk_theme(self):
        source = MODERN.read_text(encoding="utf-8")
        self.assertIn("self.button = tk.Button(", source)
        self.assertIn('foreground=colours["foreground"]', source)
        self.assertIn('background=colours["background"]', source)
        self.assertIn('activeforeground=colours["activeforeground"]', source)
        self.assertIn('highlightcolor=colours["focus"]', source)
        fixed = source[source.index("class FixedActionButton"):source.index("class StatusGlyph")]
        self.assertNotIn("ttk.Button(", fixed)

    def test_primary_and_danger_use_explicit_white_caption(self):
        source = MODERN.read_text(encoding="utf-8")
        self.assertIn('"foreground": "#ffffff"', source)
        self.assertIn('"activeforeground": "#ffffff"', source)

    def test_blocking_dialog_uses_qt_style_semantic_actions(self):
        source = BLOCKING.read_text(encoding="utf-8")
        self.assertIn("class BlockingDialog(QtDialog)", source)
        self.assertIn('"Exit WinUx?"', source)
        self.assertIn('"Delete permanently?"', source)
        self.assertIn('"danger" if intent in', source)
        self.assertIn("self.button_box", source)
        self.assertNotIn("tk.Toplevel", source)

    def test_confirm_api_accepts_modern_action_metadata(self):
        source = VIEW.read_text(encoding="utf-8")
        self.assertIn("primary_text=None", source)
        self.assertIn('primary_text = "Replace"', source)
        self.assertIn('intent = "danger"', source)
        self.assertIn('intent="error"', source)

    def test_close_and_delete_use_safe_specific_actions(self):
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn('primary_text="Exit"', source)
        self.assertIn('primary_text="Delete"', source)
        self.assertIn('intent="danger"', source)

    def test_transfer_center_reuses_shared_qt_action_metrics(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn("QtDialog", source.split("class TransferCenterDialog", 1)[1].split(":", 1)[0])
        self.assertIn("DialogMetrics.BUTTON_HEIGHT", source)
        self.assertIn("self.button_box", source)
        self.assertIn('action = self.action(', source)
        self.assertIn('"Cancel",', source)
        self.assertIn('width=94', source)


class WinScpShortcutRegressionTests(unittest.TestCase):
    def test_explorer_registers_winscp_style_shortcuts(self):
        source = LISTVIEW.read_text(encoding="utf-8")
        for key in ("mvKey_F4", "mvKey_F5", "mvKey_F7", "mvKey_R", "mvKey_Up"):
            self.assertIn(key, source)
        self.assertIn("_on_edit_shortcut", source)
        self.assertIn("_on_transfer_shortcut", source)
        self.assertIn("_on_new_folder_shortcut", source)
        self.assertIn("_on_refresh_shortcut", source)
        self.assertIn("_on_parent_shortcut", source)

    def test_controller_routes_shortcuts_through_existing_pipelines(self):
        facade = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("return self._file_command_controller().command(panel, action, selected_paths)", facade)
        source = (CONTROLLER.parent / "controllers" / "file_commands.py").read_text(encoding="utf-8")
        self.assertIn('if action == "transfer_selected":', source)
        self.assertIn("self.app.transfer_selected(panel, paths)", source)
        self.assertIn('if action == "edit":', source)
        self.assertIn("self.app.edit_server_file(panel, [paths[0]])", source)
        self.assertIn('if action == "parent":', source)

    def test_context_menu_advertises_keyboard_accelerators(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        self.assertIn("Upload selected   F5", source)
        self.assertIn("Download selected   F5", source)
        self.assertIn("Edit in WinUx Notepad   F4", source)
        self.assertIn("Rename   F2", source)
        self.assertIn("New Folder   F7", source)
        self.assertIn("Refresh   Ctrl+R", source)


if __name__ == "__main__":
    unittest.main()


class ModernDialogPhase2RegressionTests(unittest.TestCase):
    def test_standalone_dialog_helpers_exist_for_child_windows(self):
        source = MODERN.read_text(encoding="utf-8")
        self.assertIn("class StandaloneModernDialog", source)
        self.assertIn("def show_modern_message", source)
        self.assertIn("def ask_modern_confirm", source)
        self.assertIn("def ask_modern_choice", source)
        self.assertIn("def ask_modern_text", source)
        self.assertIn("def ask_modern_integer", source)
        self.assertIn("FixedActionButton(", source)

    def test_server_notepad_has_no_legacy_messagebox_or_simpledialog(self):
        process = ROOT / "WinUx" / "services" / "server_notepad_process.py"
        editor = ROOT / "WinUx" / "services" / "server_notepad_editor.py"
        source = process.read_text(encoding="utf-8") + "\n" + editor.read_text(encoding="utf-8")
        self.assertNotIn("messagebox.show", source)
        self.assertNotIn("messagebox.ask", source)
        self.assertNotIn("simpledialog.ask", source)
        self.assertIn("ask_modern_text(", source)
        self.assertIn("ask_modern_integer(", source)
        self.assertIn("ask_modern_choice(", source)
        self.assertIn("show_modern_message(", source)

    def test_server_notepad_find_and_preferences_use_fixed_action_buttons(self):
        process = ROOT / "WinUx" / "services" / "server_notepad_process.py"
        source = process.read_text(encoding="utf-8")
        pref = source[source.index("def _show_preferences"):source.index("def _zoom_in")]
        find = source[source.index("def _show_find_replace"):source.index("def _find_from_dialog")]
        self.assertIn("prepare_modern_toplevel", pref)
        self.assertIn("FixedActionButton", pref)
        self.assertNotIn("ttk.Button(", pref)
        self.assertIn("prepare_modern_toplevel", find)
        self.assertIn("FixedActionButton", find)
        self.assertNotIn("ttk.Button(", find)
