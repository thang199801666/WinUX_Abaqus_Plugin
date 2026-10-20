"""Regression: editable combo popup width must follow the full shell width."""
from pathlib import Path


def test_combo_popup_geometry_uses_shell_width_and_positions_popup_below_control():
    source = (Path(__file__).resolve().parents[1] / 'DearUIQt/widgets/combo_box.py').read_text(encoding='utf-8')
    geometry = source.split('def _popup_geometry', 1)[1].split('def _position_popup', 1)[0]
    assert 'dpg.get_item_rect_min(self.shell)' in geometry
    assert 'dpg.get_item_rect_size(self.shell)' in geometry
    assert 'width = max(1, int(round(width)))' in geometry
    assert 'popup_top = int(round(top + height - 1))' in geometry
    assert 'return (int(round(left)), popup_top, width, popup_height)' in geometry


def test_combo_popup_window_is_repositioned_with_the_shell_width():
    source = (Path(__file__).resolve().parents[1] / 'DearUIQt/widgets/combo_box.py').read_text(encoding='utf-8')
    position = source.split('def _position_popup', 1)[1].split('def open_popup', 1)[0]
    assert 'left, popup_top, width, popup_height = self._popup_geometry()' in position
    assert 'dpg.configure_item(self._popup, show=True, width=width, height=popup_height, pos=(left, popup_top))' in position


def test_combo_popup_rows_fill_the_popup_width_like_qt_combobox():
    source = (Path(__file__).resolve().parents[1] / 'DearUIQt/widgets/combo_box.py').read_text(encoding='utf-8')
    rebuild = source.split('def _rebuild_popup_items', 1)[1].split('def _sync_popup_selection', 1)[0]
    assert 'self._popup = dpg.add_window(' in source
    assert 'self.listbox = dpg.add_child_window(' in source
    assert 'dpg.add_selectable(' in rebuild
    assert 'parent=self.listbox,' in rebuild
    assert 'width=-1,' in rebuild
