from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_toolbar_controls_get_shared_top_only_visual_alignment_offset():
    src = read("components/toolbar.py")
    assert "TOOLBAR_VERTICAL_OFFSET = 2" in src
    toolbar_block = src.split("class FileToolbar", 1)[1]
    assert "dpg.add_spacer(parent=self.container, height=TOOLBAR_VERTICAL_OFFSET)" in toolbar_block
    # The shim must be inserted before the toolbar table so every control in
    # the row moves together (navigation, path field and search).
    assert toolbar_block.index("dpg.add_spacer(parent=self.container") < toolbar_block.index("self.table = dpg.add_table")


def test_toolbar_outer_height_stays_stable_while_row_moves_down():
    src = read("components/toolbar.py")
    assert "COLLAPSED_HEIGHT = 36" in src
    assert "TOOLBAR_BUTTON_HEIGHT = 28" in src


def test_product_version_stays_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
