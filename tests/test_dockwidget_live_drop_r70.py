"""Regression contract for r70 QMainWindow-like live dock drop targets."""
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
    spec = importlib.util.spec_from_file_location("dearuiqt_dock_layout_tree_r70", TREE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DockLayoutTree


def _leaf_rects(tree, keys):
    groups = tree.layout("right", 120, 80, visible_keys=set(keys))
    return {group["keys"]: group["rect"] for group in groups}


def test_edge_drop_splits_whole_existing_tab_leaf():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.add_tab("b", "right")
    tree.add_tab("c", "right")
    assert tree.group_keys("a") == ("a", "b", "c")

    assert tree.dock_relative("a", "c", "left") == "split"
    groups = tree.layout("right", 120, 80, visible_keys={"a", "b", "c"})
    assert len(groups) == 2
    assert groups[0]["keys"] == ("c",)
    assert groups[1]["keys"] == ("a", "b")
    assert groups[0]["rect"] == (0, 0, 60, 80)
    assert groups[1]["rect"] == (60, 0, 60, 80)


def test_bottom_drop_from_another_leaf_moves_only_dragged_dock():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    tree.tabify("b", "c")
    assert tree.group_keys("b") == ("b", "c")

    assert tree.dock_relative("a", "c", "bottom") == "split"
    assert tree.group_keys("b") == ("b",)
    groups = tree.layout("right", 120, 80, visible_keys={"a", "b", "c"})
    by_keys = {group["keys"]: group["rect"] for group in groups}
    assert ("a",) in by_keys
    assert ("b",) in by_keys
    assert ("c",) in by_keys
    # c is below a inside the left half; b keeps the right half.
    assert by_keys[("a",)] == (0, 0, 60, 40)
    assert by_keys[("c",)] == (0, 40, 60, 40)
    assert by_keys[("b",)] == (60, 0, 60, 80)


def test_center_drop_tabifies_and_removes_old_leaf():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    assert tree.dock_relative("a", "b", "center") == "tabified"
    assert tree.group_keys("a") == ("a", "b")
    groups = tree.layout("right", 120, 80, visible_keys={"a", "b"})
    assert len(groups) == 1
    assert groups[0]["keys"] == ("a", "b")
    assert groups[0]["active"] == "b"


def test_live_drop_topology_survives_state_round_trip():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.add_tab("b", "right")
    tree.add_tab("c", "right")
    tree.dock_relative("a", "c", "right")
    state = tree.to_state()
    restored = Tree.from_state(state)
    assert restored.group_keys("a") == ("a", "b")
    assert restored.group_keys("c") == ("c",)
    groups = restored.layout("right", 160, 90, visible_keys={"a", "b", "c"})
    assert [group["keys"] for group in groups] == [("a", "b"), ("c",)]


def test_manager_uses_existing_viewport_front_dock_drop_preview():
    assert "from .dock_widget import DockDropPreview" in MANAGER
    assert "self._drop_preview = DockDropPreview(" in MANAGER
    assert "def _dock_drop_target_at(self, mouse, drag_key):" in MANAGER
    assert "def _drop_zone_for_rect(cls, mouse, rect):" in MANAGER
    assert "def _drop_preview_rect(rect, zone):" in MANAGER
    assert 'in ("left", "right", "top", "bottom", "center")' in MANAGER
    assert "self._drop_preview.show(" in MANAGER
    assert "self._drop_preview.hide()" in MANAGER
    assert "self._drop_preview.destroy()" in MANAGER


def test_tab_reorder_precedes_five_way_docking_and_tearoff_requires_site_exit():
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    assert "outside_source_strip = self._pointer_outside_tab_strip(" in update
    assert "if outside_source_strip else None" in update
    assert "elif (outside_source_strip and self._pointer_outside_dock_site(mouse))" in update
    assert "elif not outside_source_strip:" in update
    assert "self._hide_insert_marker()" in update
    assert "not self._window_user_movable" in MANAGER


def test_drop_release_mutates_topology_instead_of_always_reordering():
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    drop_pos = update.index("if drop_target is not None:")
    reorder_pos = update.index("elif index is not None:", drop_pos)
    assert drop_pos < reorder_pos
    assert "self.dock_relative(" in update[drop_pos:reorder_pos]
    assert "dockRelative = dock_relative" in MANAGER
    assert "self._layout_tree.dock_relative(target, moving, zone)" in MANAGER


def test_dearuiqt_version_advances_for_live_dock_drop_contract():
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 9, 0)
