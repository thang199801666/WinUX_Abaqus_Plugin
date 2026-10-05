from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_file_toolbar_buttons_fill_qtoolbar_cells_without_oversized_icons():
    src = read("components/toolbar.py")
    assert "TOOLBAR_BUTTON_WIDTH = 30" in src
    assert "TOOLBAR_BUTTON_HEIGHT = 28" in src
    assert "TOOLBAR_ICON_SIZE = 22" in src
    assert "width=icon_extent" in src
    assert "height=icon_extent" in src
    assert "width=18" not in src.split("def add_resource_button", 1)[1].split("class FileToolbar", 1)[0]


def test_toolbar_cell_padding_centers_30x28_button_in_32px_action_cell():
    src = read("components/toolbar.py")
    assert "mvStyleVar_CellPadding, 1, 2" in src
    assert "init_width_or_weight=32" in src
    assert "height=TOOLBAR_BUTTON_HEIGHT" in src


def test_qtoolbutton_theme_builds_30x28_hit_target_around_22px_icon():
    src = read("widgets/imgui_qt_style.py")
    block = src.split("def tool_button_theme", 1)[1].split("def path_bar_theme", 1)[0]
    assert "mvStyleVar_FramePadding, 4, 3" in block


def test_product_version_stays_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
