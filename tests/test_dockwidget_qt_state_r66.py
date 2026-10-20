"""Regression contract for r66 QDockWidget/QMainWindow state parity."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCK = (ROOT / "DearUIQt" / "docking" / "dock_widget.py").read_text(encoding="utf-8")
MANAGER = (ROOT / "DearUIQt" / "docking" / "dock_manager.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")


def test_qdockwidget_has_qobject_identity_for_qmainwindow_state():
    assert "self._object_name = self.tag" in DOCK
    assert "self.objectNameChanged = Signal()" in DOCK
    assert "def objectName(self):" in DOCK
    assert "def setObjectName(self, name):" in DOCK
    assert "self.objectNameChanged.emit(name)" in DOCK


def test_qt69_floating_dock_has_no_dock_location():
    assert "NoDockLocation = None" in DOCK
    location = DOCK[DOCK.index("    def dockLocation(self):"):DOCK.index("    def setDockLocation", DOCK.index("    def dockLocation(self):"))]
    assert "self.NoDockLocation if self.floating else self.dock_area" in location
    floating = DOCK[DOCK.index("    def set_floating(self, floating: bool):"):DOCK.index("    def _sync_close_glyph_visual", DOCK.index("    def set_floating(self, floating: bool):"))]
    assert "self.dockLocationChanged.emit(None if floating else self.dock_area)" in floating


def test_manager_respects_allowed_areas_for_add_move_and_tabify():
    assert "def _area_allowed(cls, window, area):" in MANAGER
    assert "def _coerce_allowed_area(cls, window, area, fallback=\"right\"):" in MANAGER
    assert "if not self._area_allowed(self._entries[second].get(\"window\"), area):" in MANAGER
    assert "# QMainWindow must not force a QDockWidget into a disallowed area." in MANAGER


def test_tabified_dock_query_is_not_visibility_filtered():
    start = MANAGER.index("    def tabified_dock_widgets(self, key):")
    end = MANAGER.index("    tabifiedDockWidgets = tabified_dock_widgets", start)
    body = MANAGER[start:end]
    assert "_window_requested_visible" not in body


def test_state_is_versioned_per_dock_and_uses_object_name():
    assert "def save_state(self, version=0):" in MANAGER
    assert re.search(r'"format": [23]', MANAGER)
    assert '"version": int(version)' in MANAGER
    assert '"object_name": identity' in MANAGER
    assert '"area": self._normalize_area(' in MANAGER
    assert 'entry.get("area") or self.dock_area' in MANAGER
    assert '"floating": bool(entry.get("floating"))' in MANAGER
    assert '"visible": self._window_requested_visible(window)' in MANAGER
    assert "saveState = save_state" in MANAGER
    assert "restoreState = restore_state" in MANAGER


def test_restore_supports_late_created_docks_and_rejects_version_mismatch():
    assert "self._pending_restore: Dict[str, Dict[str, object]] = {}" in MANAGER
    assert "self._pending_restore = dict(saved_docks)" in MANAGER
    assert "pending = self._pending_restore.pop(identity, None)" in MANAGER
    add_start = MANAGER.index("    def add_dock_widget(self, key, window")
    add_end = MANAGER.index("    # Qt-style convenience alias.", add_start)
    assert "_pending_restore.pop" not in MANAGER[add_start:add_end]
    assert 'if state_format >= 2 and int(state.get("version", 0)) != int(version):' in MANAGER
    assert "return False" in MANAGER
    assert "``QMainWindow::restoreDockWidget``" in MANAGER


def test_legacy_r65_state_remains_supported():
    assert "Backward-compatible r65 payload" in MANAGER
    assert 'floating = {str(key) for key in state.get("floating") or ()}' in MANAGER


def test_dearuiqt_version_advances_for_state_contract():
    # Later revisions may legitimately advance the package version; keep the
    # r66 contract as a minimum instead of pinning every future release.
    import re
    match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', PACKAGE)
    assert match is not None
    assert tuple(map(int, match.groups())) >= (1, 5, 0)
