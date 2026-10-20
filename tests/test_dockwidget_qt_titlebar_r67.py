"""Regression contract for r67 QDockWidget title-bar/QMainWindow policy parity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCK = (ROOT / "DearUIQt" / "docking" / "dock_widget.py").read_text(encoding="utf-8")
MANAGER = (ROOT / "DearUIQt" / "docking" / "dock_manager.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")


def test_qdockwidget_exposes_vertical_title_bar_feature_without_changing_default():
    assert "DockWidgetVerticalTitleBar = 0x08" in DOCK
    default = DOCK[DOCK.index("AllDockWidgetFeatures = ("):DOCK.index("# QMainWindow", DOCK.index("AllDockWidgetFeatures = ("))]
    assert "DockWidgetClosable | DockWidgetMovable | DockWidgetFloatable" in default
    assert "DockWidgetVerticalTitleBar" not in default
    assert "def vertical_title_bar(self):" in DOCK


def test_qdockwidget_exposes_custom_title_bar_api_and_restores_default_chrome():
    assert "self._title_bar_widget = None" in DOCK
    assert "def titleBarWidget(self):" in DOCK
    assert "def setTitleBarWidget(self, widget):" in DOCK
    setter = DOCK[DOCK.index("    def setTitleBarWidget"):DOCK.index("    def _toggle_view_action_triggered", DOCK.index("    def setTitleBarWidget"))]
    assert "dpg.move_item(widget, parent=self.title_bar)" in setter
    assert "self._title_bar_widget = widget" in setter
    assert "self._sync_action_visibility()" in setter
    assert "self.sync_layout(force=True)" in setter


def test_custom_title_bar_owns_chrome_and_is_retained_when_floating():
    sync = DOCK[DOCK.index("    def _sync_action_visibility"):DOCK.index("    def _title_double_clicked")]
    assert "custom = self._title_bar_widget is not None" in sync
    assert "for item in (self.drag_handle, self.title_text, self.title_overlay):" in sync
    layout = DOCK[DOCK.index("    def sync_layout"):DOCK.index("    def close(self):", DOCK.index("    def sync_layout"))]
    assert "if self.floating and not custom:" in layout
    assert "if custom:" in layout
    assert "self._title_bar_widget, pos=(0, 0), width=title_w" in layout


def test_qt69_no_dock_location_setter_floats_dock():
    setter = DOCK[DOCK.index("    def setDockLocation(self, area):"):DOCK.index("    def featuresFlags", DOCK.index("    def setDockLocation(self, area):"))]
    assert "if area is self.NoDockLocation:" in setter
    assert "return self.setFloating(True)" in setter


def test_title_double_click_toggles_floatable_state():
    handler = DOCK[DOCK.index("    def _title_double_clicked"):DOCK.index("    def _dock_title_menu_actions")]
    assert "if self.floatable:" in handler
    assert "self._float_clicked()" in handler
    assert "not self.floating" not in handler


def test_dock_manager_exposes_qmainwindow_dock_options_contract():
    for flag in (
        "AnimatedDocks = 0x01",
        "AllowNestedDocks = 0x02",
        "AllowTabbedDocks = 0x04",
        "ForceTabbedDocks = 0x08",
        "VerticalTabs = 0x10",
        "GroupedDragging = 0x20",
    ):
        assert flag in MANAGER
    for method in (
        "def dockOptions(self):",
        "def setDockOptions(self, options):",
        "def isAnimated(self):",
        "def setAnimated(self, enabled):",
        "def isDockNestingEnabled(self):",
        "def setDockNestingEnabled(self, enabled):",
        "def documentMode(self):",
        "def setDocumentMode(self, enabled):",
    ):
        assert method in MANAGER


def test_vertical_tabs_imply_tabbed_docks_like_qt():
    assert "if self._dock_options & self.VerticalTabs:" in MANAGER
    assert "self._dock_options |= self.AllowTabbedDocks" in MANAGER


def test_per_area_tab_position_is_saved_and_restored():
    assert "def setTabPosition(self, areas, tab_position):" in MANAGER
    assert "def tabPosition(self, area):" in MANAGER
    assert "self._tab_positions = {" in MANAGER
    assert '"tab_positions": dict(self._tab_positions)' in MANAGER
    assert 'saved_tab_positions = dict(state.get("tab_positions") or {})' in MANAGER
    layout = MANAGER[MANAGER.index("    def layout(self, width, height"):MANAGER.index("    def save_state", MANAGER.index("    def layout(self, width, height"))]
    assert "current_tab_position = self.tabPosition(self.dock_area)" in layout


def test_dearuiqt_version_advances_for_titlebar_contract():
    import re
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 6, 0)
