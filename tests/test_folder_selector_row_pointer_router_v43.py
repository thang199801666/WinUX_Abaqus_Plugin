import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def _source():
    return FORM.read_text(encoding="utf-8")


def _row_pointer_method(dpg):
    tree = ast.parse(_source())
    folder_list = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FolderListView"
    )
    method = next(
        node for node in folder_list.body
        if isinstance(node, ast.FunctionDef) and node.name == "_row_pointer_clicked"
    )
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"dpg": dpg, "METRICS": SimpleNamespace(row_height=24)}
    exec(compile(module, str(FORM), "exec"), namespace)
    return namespace["_row_pointer_clicked"]


class _FakeDpg:
    def __init__(self, point=(360, 125)):
        self.point = point
        self.rect_min = {
            500: (100, 100),  # table
            101: (140, 120),  # short Name selectable for row A
            102: (140, 144),  # short Name selectable for row B
        }
        self.rect_size = {
            500: (400, 180),
            101: (70, 24),
            102: (90, 24),
        }
        self.hidden = set()

    def does_item_exist(self, _item):
        return True

    def is_item_shown(self, item):
        return item not in self.hidden

    def get_mouse_pos(self, local=False):
        assert local is False
        return self.point

    def get_item_rect_min(self, item):
        return self.rect_min[item]

    def get_item_rect_size(self, item):
        return self.rect_size[item]


class _View:
    _deleted = False
    table = 500
    items = {"A": 101, "B": 102}

    def __init__(self):
        self.clicked = []

    def _clicked(self, sender, value, key):
        self.clicked.append((sender, value, key))


def test_full_visual_row_click_routes_even_outside_name_selectable_width():
    # x=360 is far beyond the Name selectable (x=140..210) but still inside
    # the same visual table row. QFileDialog semantics require this to select A.
    dpg = _FakeDpg(point=(360, 125))
    view = _View()
    _row_pointer_method(dpg)(view)
    assert view.clicked == [(101, True, "A")]


def test_row_router_uses_current_visible_rows_and_ignores_gaps():
    dpg = _FakeDpg(point=(360, 175))  # inside table but below the rendered rows
    view = _View()
    _row_pointer_method(dpg)(view)
    assert view.clicked == []

    dpg.point = (360, 149)
    dpg.hidden.add(102)
    _row_pointer_method(dpg)(view)
    assert view.clicked == []


def test_click_outside_table_is_not_stolen_by_global_router():
    dpg = _FakeDpg(point=(80, 125))
    view = _View()
    _row_pointer_method(dpg)(view)
    assert view.clicked == []


def test_pointer_router_is_owned_and_deleted_with_list_view():
    source = _source()
    assert "def _install_row_pointer_router(self):" in source
    assert "callback=self._row_pointer_clicked" in source
    assert "self._install_row_pointer_router()" in source
    delete = source.split("    def delete(self):", 1)[1].split("    def setItems", 1)[0]
    assert "registry = self._row_pointer_registry" in delete
    assert "dpg.delete_item(registry)" in delete


def test_existing_native_cell_callbacks_remain_as_backend_fallback():
    source = _source()
    assert "self._bind_visual_cell_hit(icon_slot, item.key)" in source
    assert "self._bind_visual_cell_hit(date_text, item.key)" in source
    assert "self._bind_visual_cell_hit(type_text, item.key)" in source
    assert "_last_click_frame" in source
