"""Regression coverage for the application-wide semantic Light/Dark palette."""
from __future__ import annotations

from pathlib import Path

from DearUIQt.gui.palette import QtFusionPalette, set_color_scheme
from DearUIQt.notifications.theme import QNotificationTheme
from DearUIQt.ribbon.visual_styles import get_ribbon_visual_style
from DearUIQt.docking.dock_widget import DockDropPreview


def _brightness(color):
    return sum(int(v) for v in color[:3])


def test_semantic_feedback_roles_follow_scheme():
    try:
        set_color_scheme("Light")
        light = {
            "success": QtFusionPalette.SUCCESS,
            "success_bg": QtFusionPalette.SUCCESS_BG,
            "warning": QtFusionPalette.WARNING,
            "warning_bg": QtFusionPalette.WARNING_BG,
            "error_bg": QtFusionPalette.ERROR_BG,
        }
        set_color_scheme("Dark")
        assert QtFusionPalette.SUCCESS != light["success"]
        assert QtFusionPalette.WARNING != light["warning"]
        assert _brightness(QtFusionPalette.SUCCESS_BG) < _brightness(light["success_bg"])
        assert _brightness(QtFusionPalette.WARNING_BG) < _brightness(light["warning_bg"])
        assert _brightness(QtFusionPalette.ERROR_BG) < _brightness(light["error_bg"])
        assert _brightness(QtFusionPalette.TEXT) > _brightness(QtFusionPalette.WINDOW)
    finally:
        set_color_scheme("Light")


def test_notification_defaults_are_resolved_at_creation_time():
    try:
        set_color_scheme("Light")
        light = QNotificationTheme()
        set_color_scheme("Dark")
        dark = QNotificationTheme()
        assert dark.background == QtFusionPalette.MENU[:3]
        assert dark.foreground == QtFusionPalette.TEXT[:3]
        assert dark.secondary == QtFusionPalette.TEXT_MUTED[:3]
        assert dark.background != light.background
        assert dark.foreground != light.foreground
    finally:
        set_color_scheme("Light")


def test_builtin_ribbon_styles_are_rematerialized_after_scheme_change():
    try:
        set_color_scheme("Light")
        light = get_ribbon_visual_style("clean")
        set_color_scheme("Dark")
        dark = get_ribbon_visual_style("clean")
        assert dark.root_bg == QtFusionPalette.WINDOW_ALT
        assert dark.body_bg == QtFusionPalette.BASE
        assert dark.text == QtFusionPalette.TEXT
        assert dark.root_bg != light.root_bg
        assert dark.text != light.text
    finally:
        set_color_scheme("Light")


def test_dock_drop_preview_uses_current_palette_not_white_tiles():
    try:
        set_color_scheme("Light")
        light = DockDropPreview("theme_test_light")
        light_fill = light.PANEL_FILL
        set_color_scheme("Dark")
        dark = DockDropPreview("theme_test_dark")
        assert dark.PANEL_FILL[:3] == QtFusionPalette.MENU[:3]
        assert dark.ZONE_FILL[:3] == QtFusionPalette.BASE[:3]
        assert dark.PANEL_FILL != light_fill
    finally:
        set_color_scheme("Light")


def test_theme_sensitive_editor_and_selector_surfaces_do_not_bake_light_faces():
    root = Path(__file__).resolve().parents[1]
    editors = (root / "DearUIQt/widgets/editors.py").read_text(encoding="utf-8")
    selector = (root / "WinUx/dialogs/selectors/folder_browser_style.py").read_text(encoding="utf-8")
    rename = (root / "WinUx/ui/components/explorer/rename.py").read_text(encoding="utf-8")
    toolbar = (root / "WinUx/ui/components/toolbar.py").read_text(encoding="utf-8")

    assert "fill=QtFusionPalette.BUTTON" in editors
    assert "p.BUTTON_ACTIVE if pressed" in editors
    assert "color=QtFusionPalette.BORDER_LIGHT" in selector
    assert "editor_fill = QtFusionPalette.BASE" in rename
    assert "text_color=QtFusionPalette.TEXT" in rename
    assert "ThemeColor.BUTTON_HOVERED: p.DANGER_HOVER" in toolbar


def test_central_inline_editor_factory_uses_active_surface_not_white():
    root = Path(__file__).resolve().parents[1]
    factories = (root / "DearUIQt/themes/factories.py").read_text(encoding="utf-8")
    assert "surface = p.BASE" in factories
    assert "border = p.BORDER_DARK if border is None else border" in factories
    assert "ThemeColor.TEXT_SELECTED_BACKGROUND: p.HIGHLIGHT[:3] + (105,)" in factories


def test_selector_icon_caches_are_scheme_scoped_and_pip_controls_use_palette():
    root = Path(__file__).resolve().parents[1]
    selector = (root / "WinUx/dialogs/selectors/folder_browser_style.py").read_text(encoding="utf-8")
    compact = (root / "WinUx/ui/components/compact_jobs_view.py").read_text(encoding="utf-8")
    assert "folder_selector_crisp_{scheme}_" in selector
    assert "qt_browser_symbol_v3_" in selector
    assert "QtFusionPalette.TEXT_MUTED" in selector
    assert "fill=p.TITLE_ACTIVE" in compact
    assert "p.DANGER_HOVER if action == \"close\" else p.BUTTON_HOVER" in compact


def test_plot_digitizer_retained_surfaces_are_scheme_scoped_and_refreshable():
    root = Path(__file__).resolve().parents[1]
    checklist = (root / "WinUx/plotdigitizer/ui/checklist.py").read_text(encoding="utf-8")
    ribbon = (root / "WinUx/plotdigitizer/ui/ribbon_style.py").read_text(encoding="utf-8")
    canvas = (root / "WinUx/plotdigitizer/ui/controllers/canvas.py").read_text(encoding="utf-8")
    dialog = (root / "WinUx/plotdigitizer/ui/dialog.py").read_text(encoding="utf-8")

    assert "color_scheme()" in checklist
    assert "p.SUCCESS_BG" in checklist
    assert "p.ERROR_BG" in checklist
    assert "refreshTheme" in checklist
    assert "color_scheme()" in ribbon and "refreshTheme" in ribbon
    assert "_canvas_view_theme_map" in canvas and "refresh_theme" in canvas
    assert "_status_surface_themes" in dialog and "_refresh_theme_surfaces" in dialog


def test_native_regex_editor_uses_current_palette_instead_of_white_background():
    root = Path(__file__).resolve().parents[1]
    rich = (root / "WinUx/ui/components/regex_rich_edit.py").read_text(encoding="utf-8")
    assert "_rgb(QtFusionPalette.BASE[:3])" in rich
    assert "def refreshTheme(self):" in rich
    assert "self._format_signature = None" in rich
