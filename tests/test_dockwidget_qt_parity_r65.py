"""Regression contract for r65 QDockWidget parity work."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCK = (ROOT / "DearUIQt" / "docking" / "dock_widget.py").read_text(encoding="utf-8")
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
CONSOLE = (ROOT / "WinUx" / "ui" / "behaviors" / "console_docking.py").read_text(encoding="utf-8")


def test_dock_exposes_qt_state_signals_and_toggle_action():
    for signal in (
        "allowedAreasChanged = Signal()",
        "dockLocationChanged = Signal()",
        "featuresChanged = Signal()",
        "topLevelChanged = Signal()",
        "visibilityChanged = Signal()",
        "windowTitleChanged = Signal()",
    ):
        assert signal in DOCK
    assert "self._toggle_view_action = QAction(" in DOCK
    assert "def toggleViewAction(self):" in DOCK


def test_dock_exposes_qdockwidget_style_state_api():
    for method in (
        "def windowTitle(self):",
        "def setWindowTitle(self, title):",
        "def allowedAreas(self):",
        "def setAllowedAreas(self, areas):",
        "def isAreaAllowed(self, area):",
        "def dockLocation(self):",
        "def setDockLocation(self, area):",
        "def isFloating(self):",
        "def setFloating(self, floating):",
        "def isVisible(self):",
        "def setVisible(self, visible):",
        "def setWidget(self, widget):",
        "def takeWidget(self):",
    ):
        assert method in DOCK


def test_programmatic_state_changes_emit_qt_signals():
    assert "self.allowedAreasChanged.emit(int(self.allowed_areas))" in DOCK
    assert "self.dockLocationChanged.emit(name)" in DOCK
    assert "self.featuresChanged.emit(int(self.features))" in DOCK
    assert "self.topLevelChanged.emit(floating)" in DOCK
    assert "self.visibilityChanged.emit(visible)" in DOCK
    assert "self.windowTitleChanged.emit(title)" in DOCK


def test_features_value_is_callable_for_qt_and_int_compatible_for_legacy_callers():
    assert "class DockWidgetFeatures(int):" in DOCK
    assert "def __call__(self):" in DOCK
    assert "self.features = DockWidgetFeatures(" in DOCK


def test_console_view_menu_reuses_dock_toggle_action_as_single_source_of_truth():
    assert "console_action = self.console_dock.toggleViewAction()" in VIEW
    assert 'action(\n            "Console"' not in VIEW
    assert "on_visibility_change=lambda visible: self.set_console_visible(" in VIEW
    assert "visible=self._console_dock_visible" in VIEW
    assert "dock.set_visible(visible, notify=False)" in CONSOLE


def test_close_updates_visibility_before_host_callback():
    close = DOCK[DOCK.index("    def _close_clicked"):DOCK.index("    @staticmethod", DOCK.index("    def _close_clicked"))]
    assert close.index("self.set_visible(False)") < close.index("callback = self.on_close")


def test_tabified_docks_separate_requested_and_effective_visibility():
    manager = (ROOT / "DearUIQt" / "docking" / "dock_manager.py").read_text(encoding="utf-8")
    assert "def visible_docked_keys(self):" in manager
    assert "return self.visible_docked_keys()" in manager
    assert 'effective = getattr(window, "_set_effective_visibility", None)' in manager
    assert "effective(is_active)" in manager
    assert "def _set_effective_visibility(self, visible: bool):" in DOCK


def test_dock_manager_exposes_qmainwindow_style_aliases():
    manager = (ROOT / "DearUIQt" / "docking" / "dock_manager.py").read_text(encoding="utf-8")
    for contract in (
        "addDockWidget = add_dock_widget",
        "removeDockWidget = remove_dock_widget",
        "tabifyDockWidget = tabify_dock_widget",
        "raiseDockWidget = raise_dock_widget",
        "dockWidgetArea = dock_widget_area",
        "tabifiedDockWidgets = tabified_dock_widgets",
        "restoreDockWidget = restore_dock_widget",
    ):
        assert contract in manager
