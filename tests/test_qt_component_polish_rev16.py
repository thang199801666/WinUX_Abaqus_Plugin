from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_toolbar_search_is_one_qlineedit_like_shell():
    src = read("components/toolbar.py")
    assert "def search_shell_theme" in src
    assert "def search_editor_theme" in src
    assert "self.search_shell = dpg.add_child_window" in src
    assert "parent=self.search_shell" in src
    assert "width_stretch=True" in src
    assert "dpg.bind_item_theme(self.search_input, search_editor_theme())" in src


def test_generic_qframe_panel_surface_is_square_not_card_like():
    src = read("widgets/imgui_qt_style.py")
    block = src.split("def panel_surface_theme", 1)[1].split("def panel_header_theme", 1)[0]
    assert "mvStyleVar_ChildRounding, 0" in block
    assert "mvStyleVar_ChildBorderSize, 1 if bordered else 0" in block


def test_file_panel_client_uses_shared_qframe_surface():
    src = read("components/file_panel.py")
    assert "from ..widgets.imgui_qt_style import panel_surface_theme" in src
    assert "self.body, panel_surface_theme(" in src
    assert "bordered=False, compact=True" in src


def test_floating_tool_windows_use_nearly_square_qt_chrome():
    src = read("view.py")
    assert "mvStyleVar_WindowRounding, 1" in src
    assert "mvThemeCol_ResizeGrip, (0, 0, 0, 0)" in src


def test_transfer_rows_are_compact_qframe_records():
    src = read("dialogs/transfer_center_form.py")
    assert "height=72, border=True" in src
    assert "transfer_row_theme(dpg)" in src


def test_product_version_stays_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
