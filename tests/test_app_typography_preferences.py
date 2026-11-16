"""Regression coverage for Settings > General > Appearance typography."""
from __future__ import annotations

from pathlib import Path

from WinUx.preferences.appearance import (
    DEFAULT_UI_FONT_FAMILY,
    DEFAULT_UI_FONT_SIZE,
    DEFAULT_UI_FONT_STYLE,
    MIN_UI_FONT_SIZE,
    MAX_UI_FONT_SIZE,
    normalize_ui_font_size,
)
from WinUx.preferences.general import GeneralPreferences


def test_general_preferences_persist_typography(tmp_path):
    prefs = GeneralPreferences(root=tmp_path)
    prefs.save(
        auto_login=False,
        ui_font_family=DEFAULT_UI_FONT_FAMILY,
        ui_font_size=18,
        ui_font_style=DEFAULT_UI_FONT_STYLE,
    )
    values = prefs.load()
    assert values["ui_font_family"] == DEFAULT_UI_FONT_FAMILY
    assert values["ui_font_size"] == 18
    assert values["ui_font_style"] == DEFAULT_UI_FONT_STYLE


def test_font_size_is_clamped():
    assert normalize_ui_font_size(-100) == MIN_UI_FONT_SIZE
    assert normalize_ui_font_size(999) == MAX_UI_FONT_SIZE
    assert normalize_ui_font_size(None) == DEFAULT_UI_FONT_SIZE


def test_settings_and_main_window_are_wired_to_typography():
    root = Path(__file__).resolve().parents[1]
    form = (root / "WinUx/dialogs/settings/settings_form.py").read_text(encoding="utf-8")
    main = (root / "WinUx/ui/main_window.py").read_text(encoding="utf-8")
    rendering = (root / "WinUx/ui/components/explorer/rendering.py").read_text(encoding="utf-8")
    rename = (root / "WinUx/ui/components/explorer/rename.py").read_text(encoding="utf-8")
    lifecycle = (root / "WinUx/ui/behaviors/window/lifecycle.py").read_text(encoding="utf-8")
    toolbar = (root / "WinUx/ui/components/toolbar.py").read_text(encoding="utf-8")

    assert '"Choose Font..."' in form
    assert '"App font"' not in form
    assert '"Font size"' not in form
    assert '"Font style"' not in form
    assert '_font_summary_widget' in form
    assert '"ui_font_family"' in form
    assert '"ui_font_size"' in form
    assert '"ui_font_style"' in form
    assert "configure_ui_context(self, general_values, load_terminal=False)" in main
    assert 'values.get("ui_font_family"' in rendering
    assert 'font_face=getattr(self, "_font_family", "Segoe UI")' in rename
    assert "configure_ui_context(self, values, load_terminal=False)" in lifecycle
    assert "apply_typography(values)" in lifecycle
    assert "def apply_typography(self, preferences=None):" in rendering
    assert "path_button_font(preferences, force=True)" in toolbar
    assert "Use Font dialog to choose family, style and size" in form
