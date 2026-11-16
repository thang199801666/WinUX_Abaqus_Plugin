"""Regression contract for persistent Explorer filter state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_toolbar_restores_and_persists_filter_state():
    source = (ROOT / "WinUx/ui/components/toolbar.py").read_text(encoding="utf-8")
    assert "self._restore_filter_state()" in source
    assert "self._filter_preferences.load_filter(self.panel.panel_id)" in source
    assert "self._filter_preferences.save_filter(" in source
    assert 'self.panel._filter_query = self._restored_filter_query if enabled else ""' in source
    assert 'self.panel.apply_filter(query if self.search_visible else "")' in source


def test_file_panel_preserves_active_filter_across_every_path_change():
    source = (ROOT / "WinUx/ui/components/file_panel.py").read_text(encoding="utf-8")
    display = source.split("def display(self, path:", 1)[1].split("\n    def ", 1)[0]
    assert "Filtering is panel state, not directory state" in display
    assert "clear_search" not in display
    assert 'self._filter_query = ""' not in display


def test_disabling_filter_removes_effect_but_preserves_query():
    source = (ROOT / "WinUx/ui/components/toolbar.py").read_text(encoding="utf-8")
    close_search = source.split("def _close_search", 1)[1].split("\n    def ", 1)[0]
    assert 'self.panel.apply_filter("")' in close_search
    assert 'self._save_filter_state(False, self._filter_text())' in close_search


def test_navigation_preferences_store_filter_enabled_and_query():
    source = (ROOT / "WinUx/preferences/navigation.py").read_text(encoding="utf-8")
    assert "def load_filter(self, panel_id):" in source
    assert "def save_filter(self, panel_id, enabled, query):" in source
    assert 'state = {"enabled": bool(enabled), "query": str(query or "")}' in source
