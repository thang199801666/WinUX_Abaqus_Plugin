from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "WinUx/ui/components/reference_data_table.py"


def test_reference_table_uses_release_not_global_press_for_pointer_work():
    source = TABLE.read_text(encoding="utf-8")
    init = source[source.index("self._key_binding = QGlobalInputBinding"):
                  source.index("self._context_menu = QMenu")]
    assert "onMouseRelease(Qt.LeftButton" in init
    assert "onMouseRelease(Qt.RightButton" in init
    assert "onMouseClick(Qt.LeftButton" not in init
    assert "onMouseClick(Qt.RightButton" not in init


def test_reference_pointer_hit_test_uses_current_rect_not_stale_hover_state():
    source = TABLE.read_text(encoding="utf-8")
    block = source[source.index("    @staticmethod\n    def _point_in_native_rect"):
                   source.index("    def _row_at_pointer")]
    assert "get_item_rect_min" in block
    assert "get_item_rect_size" in block
    code = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith(("#", "\"\"\"")))
    assert "backend.is_item_hovered" not in code
    assert ".underMouse()" not in code


def test_reference_release_callback_defers_focus_and_selection_mutation():
    source = TABLE.read_text(encoding="utf-8")
    block = source[source.index("    def _mouse_left_released"):
                   source.index("    def _scroll_first")]
    assert "self.after(1, self._select_row_deferred" in block
    assert "self.after(1, self._activate_clicked_cell" in block
    assert "self.select_row(" not in block.split("self.after(1, self._select_row_deferred", 1)[0]
