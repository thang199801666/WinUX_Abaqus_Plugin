from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = (ROOT / "WinUx" / "components" / "explorer_layout.py").read_text(encoding="utf-8")
LISTVIEW = (ROOT / "WinUx" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")


def test_auto_width_uses_local_geometry_handlers():
    assert "def _install_auto_width_geometry_handlers" in LAYOUT
    assert "add_item_resize_handler" in LAYOUT
    assert "add_item_visible_handler" in LAYOUT
    assert "bind_geometry_handler(self.body_window" in LAYOUT


def test_geometry_event_refits_against_live_viewport():
    assert "def _on_auto_width_geometry_event" in LAYOUT
    assert "available = float(self._available_width())" in LAYOUT
    assert "self._fit_columns_auto_width(available)" in LAYOUT
    assert "abs(available - total) < 0.5" in LAYOUT


def test_handlers_are_installed_before_initial_content_layout():
    install = LISTVIEW.index("self._install_auto_width_geometry_handlers()")
    initial_path = LISTVIEW.index("if self.current_path is not None:", install)
    assert install < initial_path
