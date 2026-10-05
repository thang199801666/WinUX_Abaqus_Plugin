from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_combo_uses_native_combo_arrow_and_no_draw_triangle_reconfiguration():
    source = _read("components/qt_combo_box.py")
    assert "self.button = dpg.add_combo(" in source
    assert "no_preview=True" in source
    assert "draw_triangle(" not in source
    assert 'label="v"' not in source
    assert "configure_item(self.button, color=" not in source

def test_spinbox_does_not_configure_draw_triangle_after_creation():
    source = _read("widgets/controls.py")
    block = source[source.index("    def _render_spin_arrows"):source.index("    def _format_string", source.index("    def _render_spin_arrows"))]
    assert "backend.configure_item" not in block
    assert "backend.draw_triangle(" in source
    assert 'label="^"' not in source
    assert 'label="v"' not in source


def test_hotfix_keeps_dear_imgui_only_backend():
    source = _read("components/qt_combo_box.py") + _read("widgets/controls.py")
    for forbidden in ("PyQt6", "PySide6", "import tkinter", "from tkinter"):
        assert forbidden not in source
