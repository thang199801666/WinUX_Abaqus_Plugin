from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")


def test_reference_chart_is_reachable_from_main_menu():
    block = VIEW[VIEW.index("    def _build_menu(self):"):VIEW.index(
        "    @staticmethod\n    def _add_icon_menu_item", VIEW.index("    def _build_menu(self):"))]
    assert 'with dpg.menu(label="Reference") as reference_menu:' in block
    assert 'reference_menu, "Chart...", "JobViewer"' in block
    assert 'self._show_reference_chart_dialog' in block


def test_reference_library_is_initialized_at_view_scope():
    assert 'self._reference_chart_library = None' in VIEW
    assert 'self._reference_chart_dialog = None' in VIEW
