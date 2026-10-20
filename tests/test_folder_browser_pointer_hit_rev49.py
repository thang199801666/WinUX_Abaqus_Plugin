from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_sidebar_visual_layer_forwards_left_click_through_qtreewidget():
    source = FORM.read_text(encoding="utf-8")
    tree = (ROOT / "DearUIQt" / "modelview" / "tree_widget.py").read_text(encoding="utf-8")
    assert "QTreeWidget(" in source
    assert "self._places_tree.itemClicked.connect(self._place_tree_clicked" in source
    assert "add_item_clicked_handler" in tree
    assert "bind_item_handler_registry(overlay, registry)" in tree
    assert "self.itemClicked.emit(item, 0)" in tree


def test_folder_row_non_selectable_cells_forward_to_row_click_logic():
    source = FORM.read_text(encoding="utf-8")
    assert "def _visual_cell_clicked(self, _sender, _app_data, key):" in source
    assert "self._clicked(item, True, key)" in source
    assert "self._bind_visual_cell_hit(icon_slot, item.key)" in source
    assert "self._bind_visual_cell_hit(date_text, item.key)" in source
    assert "self._bind_visual_cell_hit(type_text, item.key)" in source


def test_folder_row_visual_hit_registries_are_released_on_rebuild():
    source = FORM.read_text(encoding="utf-8")
    start = source.index("def setItems(self, items):")
    end = source.index("def _sync_selection_visuals", start)
    block = source[start:end]
    assert "for registry in self._visual_hit_registries:" in block
    assert "dpg.delete_item(registry)" in block
    assert "self._visual_hit_registries.clear()" in block
