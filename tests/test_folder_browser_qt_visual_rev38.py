from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_folder_dialog_has_coherent_qfiledialog_visual_regions():
    source = FORM.read_text(encoding="utf-8")
    assert "self.location_toolbar = dpg.add_child_window" in source
    assert "self.command_toolbar = dpg.add_child_window" not in source
    assert "browser_workspace_theme()" in source
    assert "self.selection_bar = dpg.add_child_window" in source
    assert "browser_selection_bar_theme()" in source


def test_search_and_address_keep_stable_shared_qlineedit_contract():
    form = FORM.read_text(encoding="utf-8")
    address = ADDRESS.read_text(encoding="utf-8")
    assert "self.filter_edit = self.line_edit" in form
    assert "self.editor = dialog.line_edit" in address
    assert "browser_field_shell_theme(focused=False)" in address
    assert "browser_field_shell_theme(focused=True)" in address


def test_workspace_owns_frame_instead_of_nested_list_frame():
    source = FORM.read_text(encoding="utf-8")
    assert "dpg.configure_item(self.listbox.tag, border=False)" in source
    assert "borders_outerH=False, borders_outerV=False" in source
    assert "browser_details_theme()" in source


def test_new_folder_is_compact_tool_button_not_large_text_button():
    source = FORM.read_text(encoding="utf-8")
    assert "self.new_folder_button = dpg.add_image_button" in source
    assert "new_folder_texture()" in source
    assert '"New folder", self._show_new_folder, "flat"' not in source


def test_folder_browser_style_is_based_on_shared_qt_fusion_palette():
    source = STYLE.read_text(encoding="utf-8")
    assert "QtFusionPalette" in source
    assert "QtFusionMetrics" in source
    assert "add_dpg_scroller_style" in source
