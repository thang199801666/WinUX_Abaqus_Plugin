"""Regression contract for r71 QDockWidget title-bar live docking."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "DearUIQt" / "docking" / "dock_manager.py"
JOB_PLOTS_PATH = ROOT / "WinUx" / "ui" / "components" / "job_plots.py"
PACKAGE_PATH = ROOT / "DearUIQt" / "__init__.py"
MANAGER = MANAGER_PATH.read_text(encoding="utf-8")
JOB_PLOTS = JOB_PLOTS_PATH.read_text(encoding="utf-8")
PACKAGE = PACKAGE_PATH.read_text(encoding="utf-8")


def test_manager_tracks_single_leaf_title_drag_state():
    assert "self._title_press_key: Optional[str] = None" in MANAGER
    assert "self._title_drag_key: Optional[str] = None" in MANAGER
    assert "self._title_drag_owner = object()" in MANAGER
    assert "def _hovered_title_key(self):" in MANAGER
    assert "len(self._layout_tree.group_keys(key)) != 1" in MANAGER
    assert 'handle = getattr(dock, "drag_handle", None)' in MANAGER


def test_title_drag_uses_same_five_way_live_drop_engine_as_tabs():
    block = MANAGER[
        MANAGER.index("def _update_title_interaction("):
        MANAGER.index("def _begin_tab_drag(")
    ]
    assert "self._dock_drop_target_at(mouse, key)" in block
    assert "self._set_tab_drop_target(drop_target)" in block
    assert "self.dock_relative(" in block
    assert 'drop_target.get("zone") or "center"' in block


def test_title_drag_runs_even_when_no_qtabbar_exists():
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    title_pos = update.index("self._update_title_interaction(down, mouse, pressed_now)")
    no_tabs_pos = update.index("if not self._tab_buttons:")
    assert title_pos < no_tabs_pos


def test_movable_and_floatable_permissions_are_independent():
    assert "def _window_user_floatable(cls, window):" in MANAGER
    assert 'DockWidgetFloatable", 0x04' in MANAGER
    title = MANAGER[
        MANAGER.index("def _update_title_interaction("):
        MANAGER.index("def _begin_tab_drag(")
    ]
    assert "self._window_user_floatable(entry.get(\"window\"))" in title
    # The tab tear-off path must obey the same QDockWidgetFloatable gate.
    update = MANAGER[MANAGER.index("def update_interaction(self):"):]
    tearoff = update[update.index("self._pointer_outside_dock_site(mouse)"):]
    assert "self._window_user_floatable(entry.get(\"window\"))" in tearoff


def test_title_drag_tearoff_preserves_pointer_anchor_and_generic_fallback():
    shared = MANAGER[
        MANAGER.index("def _request_drag_tearoff("):
        MANAGER.index("def _tearoff_title_drag(")
    ]
    title = MANAGER[
        MANAGER.index("def _tearoff_title_drag("):
        MANAGER.index("def _update_title_interaction(")
    ]
    assert "self._title_drag_anchor(key, mouse)" in title
    assert "self._request_drag_tearoff(key, mouse, drag_anchor)" in title
    assert "callback(key, mouse, drag_anchor)" in shared
    assert 'setter = getattr(dock, "setFloating", None)' in shared
    assert "setter(True)" in shared
    assert "self.set_floating(key, True)" in shared


def test_job_plot_no_longer_registers_competing_immediate_undock_handler():
    # The compatibility helper may remain, but there must be no handler wired
    # to it: DockManager now owns the title gesture and live docking preview.
    assert "def _on_header_drag(" in JOB_PLOTS
    assert "callback=self._on_header_drag" not in JOB_PLOTS
    assert "callback=self._on_header_drag_release" not in JOB_PLOTS
    assert "DockManager owns default QDockWidget title-bar gestures" in JOB_PLOTS


def test_manager_cleanup_releases_title_drag_capture():
    close = MANAGER[MANAGER.index("def close(self):"):]
    assert "self._reset_title_drag()" in close
    reset = MANAGER[
        MANAGER.index("def _reset_title_drag("):
        MANAGER.index("def _tearoff_title_drag(")
    ]
    assert "release_pointer_input(self._title_drag_owner)" in reset
    assert "self._clear_tab_drop_target()" in reset


def test_dearuiqt_version_advances_for_title_drag_contract():
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 10, 0)
