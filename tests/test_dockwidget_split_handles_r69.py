"""Regression contract for r69 draggable nested dock split handles."""
from pathlib import Path
import importlib.util
import re

ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "DearUIQt" / "docking" / "dock_manager.py"
TREE_PATH = ROOT / "DearUIQt" / "docking" / "layout_tree.py"
PACKAGE_PATH = ROOT / "DearUIQt" / "__init__.py"
MANAGER = MANAGER_PATH.read_text(encoding="utf-8")
PACKAGE = PACKAGE_PATH.read_text(encoding="utf-8")


def _tree_class():
    spec = importlib.util.spec_from_file_location("dearuiqt_dock_layout_tree_r69", TREE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DockLayoutTree


def test_layout_details_reserves_thin_handle_and_wider_hit_target():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    details = tree.layout_details(
        "right", 121, 80, visible_keys={"a", "b"},
        handle_width=1, handle_hit_width=9)
    by_key = {group["keys"][0]: group["rect"] for group in details["groups"]}
    assert by_key["a"] == (0, 0, 60, 80)
    assert by_key["b"] == (61, 0, 60, 80)
    assert len(details["handles"]) == 1
    handle = details["handles"][0]
    assert handle["orientation"] == "horizontal"
    assert handle["rect"] == (60, 0, 1, 80)
    assert handle["hit_rect"] == (56, 0, 9, 80)


def test_nested_layout_emits_independent_horizontal_and_vertical_handles():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    tree.split("b", "c", "vertical")
    details = tree.layout_details(
        "right", 121, 81, visible_keys={"a", "b", "c"},
        handle_width=1, handle_hit_width=9)
    assert [(h["path"], h["orientation"]) for h in details["handles"]] == [
        ((), "horizontal"), ((1,), "vertical")]


def test_resize_split_handle_updates_pair_weights_without_changing_topology():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    before_state = tree.to_state()
    details = tree.layout_details(
        "right", 121, 60, visible_keys={"a", "b"},
        handle_width=1, handle_hit_width=9)
    handle = details["handles"][0]
    assert tree.resize_split_handle(
        handle["area"], handle["path"], handle["before_index"],
        handle["after_index"], 80, 40)
    groups = tree.layout_details(
        "right", 121, 60, visible_keys={"a", "b"}, handle_width=1
    )["groups"]
    by_key = {group["keys"][0]: group["rect"] for group in groups}
    assert by_key["a"][2] == 80
    assert by_key["b"][2] == 40
    after_state = tree.to_state()
    assert before_state["areas"]["right"]["orientation"] == after_state["areas"]["right"]["orientation"]
    assert before_state["areas"]["right"]["children"] == after_state["areas"]["right"]["children"]
    assert before_state["areas"]["right"]["weights"] != after_state["areas"]["right"]["weights"]


def test_split_drag_clamp_preserves_total_and_minimum_extent():
    Tree = _tree_class()
    before, after = Tree.clamp_split_pair(60, 60, 1000, minimum=24)
    assert before == 96
    assert after == 24
    before, after = Tree.clamp_split_pair(60, 60, -1000, minimum=24)
    assert before == 24
    assert after == 96
    assert before + after == 120


def test_hidden_split_branch_removes_handle_and_restores_full_extent():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    details = tree.layout_details(
        "right", 120, 70, visible_keys={"a"},
        handle_width=1, handle_hit_width=9)
    assert details["handles"] == ()
    assert details["groups"][0]["rect"] == (0, 0, 120, 70)


def test_manager_owns_protected_split_handle_views_and_pointer_capture():
    assert "SPLIT_HANDLE_WIDTH = 1" in MANAGER
    assert "SPLIT_HANDLE_HIT_WIDTH = 9" in MANAGER
    assert "register_pointer_protected_item(hitbox)" in MANAGER
    assert "acquire_pointer_input(self._split_drag_owner)" in MANAGER
    assert "release_pointer_input(self._split_drag_owner)" in MANAGER
    assert "unregister_pointer_protected_item(hitbox)" in MANAGER
    assert 'dpg.move_item(view["hitbox"], parent=self.parent)' in MANAGER


def test_manager_routes_layout_through_handle_geometry_and_opaque_drag_resize():
    assert "self._layout_tree.layout_details(" in MANAGER
    assert "handle_width=self.SPLIT_HANDLE_WIDTH" in MANAGER
    assert "handle_hit_width=self.SPLIT_HANDLE_HIT_WIDTH" in MANAGER
    assert "self._sync_split_handle_views(details[\"handles\"])" in MANAGER
    assert "DockLayoutTree.clamp_split_pair(" in MANAGER
    assert "self._layout_tree.resize_split_handle(" in MANAGER
    assert "self.layout(width, height, force=True)" in MANAGER


def test_manager_prioritizes_split_drag_before_tab_drag():
    update_pos = MANAGER.index("def update_interaction(self):")
    split_pos = MANAGER.index("self._update_split_interaction(down, mouse, pressed_now)", update_pos)
    tab_pos = MANAGER.index("# First down frame over a tab", update_pos)
    assert split_pos < tab_pos


def test_dearuiqt_version_advances_for_draggable_splitter_contract():
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 8, 0)
