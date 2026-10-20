"""Regression contract for r72 grouped title dragging and Esc cancellation."""
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
    spec = importlib.util.spec_from_file_location("dearuiqt_dock_layout_tree_r72", TREE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DockLayoutTree


def _two_groups():
    Tree = _tree_class()
    tree = Tree()
    tree.add_tab("a", "right")
    tree.add_tab("b", "right")
    tree.add_tab("c", "right")
    assert tree.dock_relative("a", "c", "right") == "split"
    tree.add_tab("d", "right", target="c")
    assert tree.group_keys("a") == ("a", "b")
    assert tree.group_keys("c") == ("c", "d")
    return tree


def test_layout_tree_moves_complete_tab_leaf_on_group_edge_drop():
    tree = _two_groups()
    assert tree.dock_group_relative("c", "a", "bottom") == "split"
    assert tree.group_keys("a") == ("a", "b")
    assert tree.group_keys("c") == ("c", "d")
    state = tree.to_state()
    restored = type(tree).from_state(state)
    assert restored.group_keys("a") == ("a", "b")
    assert restored.group_keys("c") == ("c", "d")


def test_layout_tree_group_center_drop_preserves_source_order_and_active_tab():
    tree = _two_groups()
    tree.set_active("a")
    assert tree.dock_group_relative("c", "a", "center") == "tabified"
    assert tree.group_keys("c") == ("c", "d", "a", "b")
    assert tree.active_for("c") == "a"


def test_grouped_dragging_implies_allow_tabbed_docks():
    assert "if self._dock_options & self.GroupedDragging:" in MANAGER
    assert "self._dock_options |= self.AllowTabbedDocks" in MANAGER
    assert "def groupedDraggingEnabled(self):" in MANAGER


def test_grouped_drag_is_title_only_and_excludes_complete_source_leaf_from_targets():
    title = MANAGER[
        MANAGER.index("def _begin_title_drag("):
        MANAGER.index("def _begin_tab_drag(")
    ]
    assert "self._title_drag_group_keys" in title
    assert "self.groupedDraggingEnabled()" in title
    assert "self._dock_drop_target_for_keys(mouse, key, drag_keys=drag_keys)" in title
    assert "self.dock_group_relative(" in title
    # QTabBar drags remain a one-dock gesture, matching Qt GroupedDragging docs.
    tab = MANAGER[MANAGER.index("def _begin_tab_drag("):MANAGER.index("def update_interaction(")]
    assert "_title_drag_group_keys" not in tab


def test_group_drop_rejects_destination_if_any_member_disallows_area():
    assert "def _group_drop_allowed(self, target_key, group_keys):" in MANAGER
    group_drop = MANAGER[
        MANAGER.index("def dock_group_relative("):
        MANAGER.index("def resize_docks(")
    ]
    assert "for key in source_keys:" in group_drop
    assert "not self._area_allowed(entry.get(\"window\"), area)" in group_drop


def test_escape_cancels_all_drag_paths_and_restores_opaque_split_resize():
    assert "def _escape_pressed():" in MANAGER
    assert "def cancel_active_drag(self):" in MANAGER
    cancel = MANAGER[
        MANAGER.index("def cancel_active_drag(self):"):
        MANAGER.index("def update_interaction(self):")
    ]
    assert "self._cancel_split_drag(restore=True)" in cancel
    assert "self._reset_title_drag()" in cancel
    assert "self._reset_tab_drag()" in cancel
    assert "self._split_drag_restore_state = self._layout_tree.to_state()" in MANAGER
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    assert "if self._escape_pressed():" in update
    assert "self.cancel_active_drag()" in update


def test_tearoff_is_deferred_until_release_so_escape_can_cancel():
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    assert "self._tab_drag_outside = bool(" in update
    assert "elif outside:" in update
    title = MANAGER[
        MANAGER.index("def _update_title_interaction("):
        MANAGER.index("def _begin_tab_drag(")
    ]
    assert "self._title_drag_outside = bool(" in title
    assert "elif outside:" in title


def test_dearuiqt_version_advances_for_r72_grouped_drag_contract():
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 11, 0)
