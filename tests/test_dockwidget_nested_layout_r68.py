"""Regression contract for r68 recursive QMainWindow-like dock layouts."""
from pathlib import Path
import importlib.util
import re

ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "DearUIQt" / "docking" / "dock_manager.py"
TREE_PATH = ROOT / "DearUIQt" / "docking" / "layout_tree.py"
PACKAGE_PATH = ROOT / "DearUIQt" / "__init__.py"
MANAGER = MANAGER_PATH.read_text(encoding="utf-8")
TREE_SOURCE = TREE_PATH.read_text(encoding="utf-8")
PACKAGE = PACKAGE_PATH.read_text(encoding="utf-8")


def _tree_class():
    spec = importlib.util.spec_from_file_location("dearuiqt_dock_layout_tree_r68", TREE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DockLayoutTree


def test_layout_tree_splits_horizontally_and_vertically():
    Tree = _tree_class()
    tree = Tree()
    assert tree.add_tab("a", "right")
    assert tree.split("a", "b", 1) == "split"
    assert tree.split("b", "c", 2) == "split"
    groups = tree.layout("right", 120, 80, visible_keys={"a", "b", "c"})
    by_key = {group["keys"][0]: group["rect"] for group in groups}
    assert by_key["a"] == (0, 0, 60, 80)
    assert by_key["b"] == (60, 0, 60, 40)
    assert by_key["c"] == (60, 40, 60, 40)


def test_split_on_tabified_first_follows_qt_and_adds_tab():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "left")
    tree.add_tab("b", "left")
    assert tree.group_keys("a") == ("a", "b")
    assert tree.split("a", "c", "horizontal") == "tabified"
    assert tree.group_keys("a") == ("a", "b", "c")
    assert tree.tabified("c") == ("a", "b")


def test_resize_docks_changes_sibling_weights_not_absolute_geometry():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "bottom")
    tree.split("a", "b", "horizontal")
    assert tree.resize_docks(["a", "b"], [1, 3], 1)
    groups = tree.layout("bottom", 200, 100, visible_keys={"a", "b"})
    by_key = {group["keys"][0]: group["rect"] for group in groups}
    assert by_key["a"][2] == 50
    assert by_key["b"][2] == 150


def test_hidden_split_branch_redistributes_space_like_qsplitter():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    groups = tree.layout("right", 160, 90, visible_keys={"a"})
    assert len(groups) == 1
    assert groups[0]["keys"] == ("a",)
    assert groups[0]["rect"] == (0, 0, 160, 90)


def test_layout_state_round_trip_preserves_tree_and_supports_renaming():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.split("a", "b", "horizontal")
    tree.tabify("b", "c")
    tree.set_active("c")
    state = tree.to_state(key_encoder=lambda key: "obj-" + key)
    restored = Tree.from_state(state)
    assert restored.rename("obj-a", "live-a")
    assert restored.rename("obj-b", "live-b")
    assert restored.rename("obj-c", "live-c")
    assert restored.tabified("live-c") == ("live-b",)
    groups = restored.layout(
        "right", 100, 60, visible_keys={"live-a", "live-b", "live-c"})
    assert len(groups) == 2
    tabbed = next(group for group in groups if "live-c" in group["keys"])
    assert tabbed["keys"] == ("live-b", "live-c")
    assert tabbed["active"] == "live-c"


def test_manager_exposes_qmainwindow_split_and_resize_contract():
    assert "from .layout_tree import DockLayoutTree" in MANAGER
    assert "def split_dock_widget(self, first, second, orientation):" in MANAGER
    assert "splitDockWidget = split_dock_widget" in MANAGER
    assert "def resize_docks(self, docks, sizes, orientation):" in MANAGER
    assert "resizeDocks = resize_docks" in MANAGER
    assert ("self._layout_tree.layout(" in MANAGER
            or "self._layout_tree.layout_details(" in MANAGER)
    assert "self._layout_tree.split(first, second, orientation)" in MANAGER
    assert "self._layout_tree.resize_docks(resolved, sizes, orientation)" in MANAGER


def test_manager_renders_multiple_split_leaf_groups_and_tab_strips():
    assert "self._tab_views: Dict[str, Dict[str, object]] = {}" in MANAGER
    assert "def _ensure_tab_view(self, group_id):" in MANAGER
    assert "for group in groups:" in MANAGER
    assert 'gx, gy, gw, gh = group["rect"]' in MANAGER
    assert 'root, pos=(gx, content_y), width=gw, height=content_h' in MANAGER


def test_format3_state_contains_recursive_layout_and_keeps_legacy_formats():
    assert '"format": 3' in MANAGER
    assert '"layout": self._layout_tree.to_state(' in MANAGER
    assert "DockLayoutTree.from_state(state.get(\"layout\"))" in MANAGER
    assert "r66/r67 format-2 state had no recursive topology" in MANAGER
    assert "Backward-compatible r65 payload" in MANAGER


def test_dearuiqt_version_advances_for_nested_docking_contract():
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 7, 0)
