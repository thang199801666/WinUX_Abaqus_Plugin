import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.components.explorer_item_model import ExplorerItemModel, stable_item_identity
from WinUx.components.explorer_list_model import ListViewItem


class ExplorerItemModelTests(unittest.TestCase):
    def test_metadata_replacement_preserves_selection_anchor_and_current(self):
        model = ExplorerItemModel()
        model.items = [ListViewItem("a", "/a"), ListViewItem("b", "/b")]
        state = model.replace([ListViewItem("b", "/b", size=9), ListViewItem("a", "/a")],
                              selected={1}, anchor=1, current=1)
        self.assertEqual(state.old_topology, state.new_topology)
        self.assertEqual((state.selected, state.anchor, state.current), ({1}, 1, 1))

    def test_navigation_clears_old_selection(self):
        model = ExplorerItemModel()
        model.items = [ListViewItem("a", "/old/a")]
        state = model.replace([ListViewItem("a", "/new/a")], {0}, 0, 0)
        self.assertEqual((state.selected, state.anchor, state.current), (set(), None, None))

    def test_job_identity_survives_name_change(self):
        model = ExplorerItemModel()
        model.items = [ListViewItem("old", data={"job_id": 42})]
        state = model.replace([ListViewItem("new", data={"job_id": "42"})], {0}, 0, 0)
        self.assertEqual(state.selected, {0})
        self.assertEqual(state.old_topology, state.new_topology)

    def test_parent_and_folders_stay_first_in_both_directions(self):
        model = ExplorerItemModel()
        for ascending in (True, False):
            model.items = [ListViewItem("z"), ListViewItem("b", is_dir=True),
                           ListViewItem("..", is_dir=True), ListViewItem("a", is_dir=True), ListViewItem("x")]
            model.sort(ascending=ascending)
            expected = ["..", "a", "b", "x", "z"] if ascending else ["..", "b", "a", "z", "x"]
            self.assertEqual([i.name for i in model.items], expected)

    def test_all_metadata_sort_columns(self):
        model = ExplorerItemModel()
        for key in ("date", "size", "type"):
            model.items = [ListViewItem("a", size=3, mtime=3, item_type="Z"),
                           ListViewItem("b", size=1, mtime=1, item_type="A")]
            model.sort(key)
            self.assertEqual([i.name for i in model.items], ["b", "a"])

    def test_keyboard_current_follows_object_when_sort_reorders(self):
        model = ExplorerItemModel()
        first, second = ListViewItem("a"), ListViewItem("b")
        model.items = [first, second]
        state = model.reorder({0}, 0, 1, ascending=False)
        self.assertEqual(model.items, [second, first])
        self.assertEqual((state.selected, state.anchor, state.current), ({1}, 1, 0))

    def test_removed_current_falls_back_to_first_selected(self):
        model = ExplorerItemModel()
        model.items = [ListViewItem("a"), ListViewItem("b")]
        state = model.replace([ListViewItem("b")], {-1, 1, 99}, 0, 0)
        self.assertEqual((state.selected, state.anchor, state.current), ({0}, None, 0))

    def test_identity_work_is_two_linear_scans(self):
        model = ExplorerItemModel()
        items = [ListViewItem(str(i), str(i)) for i in range(100)]
        model.items = items
        calls = []
        def identity(item):
            calls.append(item)
            return stable_item_identity(item)
        model.replace(items, range(100), 99, 98, identity=identity)
        self.assertEqual(len(calls), 200)

    def test_cached_sort_does_not_eagerly_recompute_casefold(self):
        class CachedName(str):
            def casefold(self):
                raise AssertionError("cached name should be used")
        model = ExplorerItemModel()
        model.items = [SimpleNamespace(name=CachedName("b"), is_dir=False, cached_name_sort="b"),
                       SimpleNamespace(name=CachedName("a"), is_dir=False, cached_name_sort="a")]
        model.sort()
        self.assertEqual([str(i.name) for i in model.items], ["a", "b"])

    def test_real_facade_routes_metadata_refresh_to_existing_rows(self):
        view = facade_harness()
        view.items = [ListViewItem("a", "/a")]
        view.selected, view.last_clicked_index, view._current_index = {0}, 0, 0
        updated = ListViewItem("a", "/a", size=99)
        self.assertIs(view.set_items([updated]), view)
        self.assertIs(view.items[0], updated)
        self.assertEqual((view.selected, view.last_clicked_index, view._current_index), ({0}, 0, 0))
        view._refresh_row_content.assert_called_once()
        view._rebuild_body_rows.assert_not_called()
        view._rebuild_draw_items.assert_not_called()

    def test_real_facade_rebuilds_when_row_topology_changes(self):
        view = facade_harness()
        view.items = [ListViewItem("a", "/a")]
        view.set_items([ListViewItem("b", "/b")])
        view._rebuild_body_rows.assert_called_once()
        view._refresh_row_content.assert_not_called()


def facade_harness():
    """Exercise actual facade methods without loading the native DPG DLL."""
    source = Path(__file__).resolve().parents[1] / "WinUx/components/explorer_list_view.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExplorerListView")
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
               and node.name in {"items", "_stable_item_identity", "set_items"}]
    harness = ast.ClassDef(name="Harness", bases=[], keywords=[], body=methods, decorator_list=[])
    namespace = {"stable_item_identity": stable_item_identity,
                 "dpg": SimpleNamespace(does_item_exist=lambda tag: True)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(source), "exec"), namespace)
    view = namespace["Harness"]()
    view._item_model = ExplorerItemModel()
    view.selected, view.last_clicked_index, view._current_index = set(), None, None
    view.sort_key, view.sort_ascending = "name", True
    view._header_items, view.body_canvas = {"name": {}}, "body"
    view._row_registry_can_reuse = lambda old, new: old == new
    for method in ("_hide_item_tooltips", "_rebuild_pinned_row", "_refresh_row_content", "_layout_all",
                   "_rebuild_body_rows", "_rebuild_draw_items", "_update_status_bar"):
        setattr(view, method, Mock())
    return view
