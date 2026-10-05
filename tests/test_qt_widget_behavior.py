from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "WinUx" / "components"


class QtWidgetBehaviorTests(unittest.TestCase):
    def test_qt_palette_exposes_focus_header_menu_and_inactive_selection_roles(self):
        source = (COMPONENTS / "qt_style.py").read_text(encoding="utf-8")
        for token in (
            "FOCUS =",
            "SELECTION_INACTIVE =",
            "SELECTION_INACTIVE_BORDER =",
            "HEADER_HOVER =",
            "HEADER_PRESSED =",
            "MENU_HOVER =",
            "MENU_ACTIVE =",
            "HEADER_HEIGHT =",
            "ROW_HEIGHT =",
        ):
            self.assertIn(token, source)

    def test_explorer_has_qabstractitemview_style_current_index_and_keyboard_navigation(self):
        source = (COMPONENTS / "explorer_list_view.py").read_text(encoding="utf-8")
        source += (COMPONENTS / "explorer_themes.py").read_text(encoding="utf-8")
        for token in (
            "self._current_index",
            "def _on_navigation_key",
            "def _ensure_index_visible",
            "def _apply_keyboard_current",
            "def _on_space_pressed",
            "mvKey_Up",
            "mvKey_Down",
            "mvKey_Home",
            "mvKey_End",
            "mvKey_PageUp",
            "mvKey_PageDown",
            "SELECTION_INACTIVE",
        ):
            self.assertIn(token, source)

    def test_header_cells_have_qheaderview_hover_and_pressed_visual_states(self):
        source = (COMPONENTS / "explorer_list_view.py").read_text(encoding="utf-8")
        for token in (
            "def _update_header_cell_visuals",
            "def _update_header_hover_state",
            "HEADER_HOVER",
            "HEADER_PRESSED",
            '"background"',
        ):
            self.assertIn(token, source)

    def test_context_menu_has_qmenu_keyboard_navigation(self):
        source = (COMPONENTS / "explorer_list_view.py").read_text(encoding="utf-8")
        source += "\n" + (COMPONENTS / "explorer_context_menu.py").read_text(encoding="utf-8")
        source += "\n" + (COMPONENTS / "explorer_rendering.py").read_text(encoding="utf-8")
        for token in (
            "def _on_context_menu_key",
            "def _context_keyboard_candidates",
            "def _set_context_keyboard_id",
            "_context_menu_keyboard_button_theme",
            "p.MENU_HOVER",
            "p.MENU_ACTIVE",
            "m.POPUP_ROUNDING",
        ):
            self.assertIn(token, source)

    def test_qcombobox_has_keyboard_index_and_disabled_behavior(self):
        source = (COMPONENTS / "qt_combo_box.py").read_text(encoding="utf-8")
        for token in (
            "def set_enabled",
            "def current_index",
            "def set_current_index",
            "def popup_open",
            "def _f4_pressed",
            "def _up_pressed",
            "def _down_pressed",
            "get_item_state",
        ):
            self.assertIn(token, source)

    def test_qcombobox_uses_native_imgui_combo_popup_for_modal_safe_selection(self):
        source = (COMPONENTS / "qt_combo_box.py").read_text(encoding="utf-8")
        self.assertIn("self.button = dpg.add_combo(", source)
        self.assertIn("no_preview=True", source)
        self.assertIn("callback=self._native_selected", source)
        self.assertNotIn("self._popup = dpg.add_child_window(", source)
        self.assertNotIn("dpg.add_selectable(", source)
        self.assertNotIn("add_mouse_release_handler", source)

    def test_qcombobox_native_arrow_shares_qt_fusion_shell_theme(self):
        source = (COMPONENTS / "qt_combo_box.py").read_text(encoding="utf-8")
        self.assertIn("with dpg.theme_component(dpg.mvCombo):", source)
        self.assertIn("self.container = dpg.add_child_window(", source)
        self.assertIn("dpg.mvStyleVar_ChildBorderSize, 1", source)
        self.assertIn("dpg.mvStyleVar_CellPadding, 0, 0", source)
        self.assertIn("no_preview=True", source)
        self.assertNotIn('label="v"', source)
        self.assertNotIn('▾', source)
        self.assertIn("self.search = None", source)


    def test_dialog_line_edit_and_combo_helpers_use_qt_focus_themes(self):
        theme = (ROOT / "WinUx" / "dialogs" / "theme.py").read_text(encoding="utf-8")
        dialog = (ROOT / "WinUx" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
        for token in (
            "def line_edit_theme",
            "def combo_theme",
            "p.FOCUS if focused else p.BORDER",
            "def bind_line_edit_style",
            "def bind_combo_style",
        ):
            self.assertIn(token, theme)
        for token in (
            "def line_edit",
            "def combo",
            "line_edit_shell_theme",
            "line_edit_editor_theme",
            "bind_combo_style(item)",
            "def focus_editor",
        ):
            self.assertIn(token, dialog)

    def test_editable_qcombobox_is_dpg_only_and_leaves_input_clicks_to_imgui(self):
        source = (COMPONENTS / "qt_combo_box.py").read_text(encoding="utf-8")
        self.assertIn("qt_combo.shell.focus", source)
        self.assertIn("qt_combo.editor.disabled", source)
        self.assertIn("qt_combo.arrow.disabled", source)
        self.assertIn("def _refresh_shell_theme", source)
        self.assertIn("ARROW_WIDTH = METRICS.arrow_width", source)
        self.assertIn("auto_select_all=False", source)
        self.assertIn("FrameBorderSize, 0", source)
        self.assertIn("self.button = dpg.add_combo(", source)
        self.assertIn("no_preview=True", source)
        self.assertIn("callback=self._native_selected", source)
        self.assertNotIn("dpg.draw_triangle(", source)
        self.assertNotIn("self._popup = dpg.add_child_window(", source)
        input_handlers = source.split("def _install_input_state_handlers", 1)[1].split(
            "def _button_activated", 1)[0]
        self.assertNotIn("add_item_clicked_handler", input_handlers)
        self.assertNotIn("focus_item(self.input)", input_handlers)

    def test_qcombobox_dropdown_uses_native_begincombo_inside_modal(self):
        source = (COMPONENTS / "qt_combo_box.py").read_text(encoding="utf-8")
        self.assertIn("Dear PyGui only", source)
        self.assertIn("self.button = dpg.add_combo(", source)
        self.assertIn("no_preview=True", source)
        self.assertNotIn("self._find_popup_parent()", source)
        self.assertNotIn("self._popup = dpg.add_child_window(", source)
        self.assertNotIn("tkinter", source)
        self.assertNotIn("PyQt", source)
        self.assertNotIn("NativeQt", source)


    def test_qdialog_default_reject_and_treeview_helpers_are_shared(self):
        source = (ROOT / "WinUx" / "dialogs" / "modern.py").read_text(encoding="utf-8")
        for token in (
            "def install_qt_dialog_behavior",
            "def register_qt_dialog_action",
            "_winux_qt_default_button",
            "_winux_qt_cancel_button",
            "def install_qt_treeview_behavior",
            "<Control-space>",
            "def configure_qt_menu",
            "Vertical.TScrollbar",
            "Horizontal.TProgressbar",
            "def install_qt_widget_behavior",
            "class QtDialogButtonBox",
            "<Control-a>",
            "<F4>",
            "<Alt-Down>",
        ):
            self.assertIn(token, source)

    def test_qheaderview_click_release_resize_to_contents_and_single_section_resize(self):
        source = (COMPONENTS / "explorer_list_view.py").read_text(encoding="utf-8")
        dispatch = (COMPONENTS / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")
        columns = (COMPONENTS / "explorer_columns.py").read_text(encoding="utf-8")
        self.assertIn("def _auto_size_column_to_contents", columns)
        for token in (
            "self._last_header_separator_click_time",
            "self._separator_click_candidate_key",
            "self._header_dragged",
            "Sort is committed on release",
            "Qt Interactive resize changes the grabbed section only",
        ):
            self.assertIn(token, source + dispatch)

    def test_floating_table_forms_use_shared_qt_table_behavior(self):
        dialogs = ROOT / "WinUx" / "dialogs"
        for name in (
            "bookmarks_form.py",
            "odb_extract_form.py",
            "odb_check_form.py",
            "sync_preview_form.py",
        ):
            source = (dialogs / name).read_text(encoding="utf-8")
            self.assertTrue(
                "QtTable" in source,
                name,
            )



    def test_native_qtreeview_qheaderview_wrapper_and_shortcuts_are_shared(self):
        source = (ROOT / "WinUx" / "dialogs" / "modern.py").read_text(encoding="utf-8")
        for token in (
            "class QtTreeView",
            "def install_qt_header_behavior",
            "def resize_tree_column_to_contents",
            "def _smart_tree_sort_key",
            "<Double-1>",
            '" [asc]"',
            '" [desc]"',
            "<Control-Tab>",
            "<Control-Shift-Tab>",
        ):
            self.assertIn(token, source)

    def test_primary_floating_table_forms_use_qttable(self):
        dialogs = ROOT / "WinUx" / "dialogs"
        for name in (
            "bookmarks_form.py",
            "sync_preview_form.py",
            "odb_check_form.py",
            "odb_extract_form.py",
        ):
            source = (dialogs / name).read_text(encoding="utf-8")
            self.assertIn("QtTable", source)

    def test_floating_forms_use_shared_qdialog_button_box(self):
        dialogs = ROOT / "WinUx" / "dialogs"
        for name in (
            "login_form.py",
            "settings_form.py",
            "job_edit_form.py",
            "server_path_form.py",
            "bookmarks_form.py",
            "site_manager_form.py",
            "sync_preview_form.py",
        ):
            source = (dialogs / name).read_text(encoding="utf-8")
            self.assertIn("self.button_box(", source)

    def test_native_chrome_matches_fixed_vs_resizable_qdialog_flags(self):
        source = (ROOT / "WinUx" / "platform" / "native_dialog_host.py").read_text(
            encoding="utf-8")
        for token in (
            "WS_THICKFRAME",
            "WS_MAXIMIZEBOX",
            "WS_MINIMIZEBOX",
            "desired &= ~WS_MINIMIZEBOX",
            "window.resizable()",
        ):
            self.assertIn(token, source)

    def test_modified_components_are_syntax_valid(self):
        for name in ("qt_style.py", "explorer_list_view.py", "qt_combo_box.py"):
            source = (COMPONENTS / name).read_text(encoding="utf-8")
            compile(source, str(COMPONENTS / name), "exec")
        dialogs = ROOT / "WinUx" / "dialogs"
        for name in (
            "modern.py", "bookmarks_dialog.py", "odb_extract_dialog.py",
            "odb_check_dialog.py", "sync_preview_dialog.py",
        ):
            source = (dialogs / name).read_text(encoding="utf-8")
            compile(source, str(dialogs / name), "exec")

    def test_explorer_list_view_imports_shared_scroller_metrics_before_class_scope_use(self):
        source = (ROOT / "WinUx" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")
        import_line = "from .shared_scroller import SharedScrollerMetrics"
        use_line = "SCROLLBAR_HIT_SIZE = float(SharedScrollerMetrics.HIT_THICKNESS)"
        self.assertIn(import_line, source)
        self.assertIn(use_line, source)
        self.assertLess(source.index(import_line), source.index(use_line))


if __name__ == "__main__":
    unittest.main()
