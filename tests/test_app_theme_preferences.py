"""Regression coverage for Settings > General > Appearance Light/Dark theme."""
from __future__ import annotations

from pathlib import Path

from DearUIQt.gui.palette import QtFusionPalette, color_scheme, set_color_scheme
from WinUx.preferences.appearance import DEFAULT_UI_THEME, normalize_ui_theme
from WinUx.preferences.general import GeneralPreferences


def test_general_preferences_persist_ui_theme(tmp_path):
    prefs = GeneralPreferences(root=tmp_path)
    prefs.save(auto_login=False, ui_theme="Dark")
    assert prefs.load()["ui_theme"] == "Dark"
    prefs.save(auto_login=False, ui_theme="Light")
    assert prefs.load()["ui_theme"] == "Light"


def test_ui_theme_normalization_is_light_or_dark_only():
    assert normalize_ui_theme("dark") == "Dark"
    assert normalize_ui_theme(" DARK ") == "Dark"
    assert normalize_ui_theme("light") == "Light"
    assert normalize_ui_theme("unknown") == DEFAULT_UI_THEME
    assert normalize_ui_theme(None) == DEFAULT_UI_THEME


def test_qt_fusion_palette_switches_without_changing_metrics():
    try:
        set_color_scheme("Light")
        light_window = QtFusionPalette.WINDOW
        light_text = QtFusionPalette.TEXT
        set_color_scheme("Dark")
        assert color_scheme() == "Dark"
        assert QtFusionPalette.WINDOW != light_window
        assert QtFusionPalette.TEXT != light_text
        assert sum(QtFusionPalette.WINDOW[:3]) < sum(QtFusionPalette.TEXT[:3])
    finally:
        set_color_scheme("Light")


def test_settings_and_main_window_are_wired_to_ui_theme():
    root = Path(__file__).resolve().parents[1]
    form = (root / "WinUx/dialogs/settings/settings_form.py").read_text(encoding="utf-8")
    main = (root / "WinUx/ui/main_window.py").read_text(encoding="utf-8")
    lifecycle = (root / "WinUx/ui/behaviors/window/lifecycle.py").read_text(encoding="utf-8")

    assert 'appearance_form, "Theme"' in form
    assert '"ui_theme"' in form
    assert "AVAILABLE_UI_THEMES" in form
    assert "configure_color_scheme(self, general_values, apply_runtime=False)" in main
    assert "configure_color_scheme(self, values, apply_runtime=True)" in lifecycle


def test_theme_change_is_broadcast_to_all_dialog_hosts_and_live_dialogs():
    root = Path(__file__).resolve().parents[1]
    appearance = (root / "WinUx/ui/appearance.py").read_text(encoding="utf-8")
    controller = (root / "WinUx/ui/hosting/floating_dialog.py").read_text(encoding="utf-8")
    runtime = (root / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
    dialog = (root / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")

    assert 'dialog.post_latest("set_theme", scheme)' in appearance
    assert "refresh_open_dialog_themes()" in appearance
    assert 'ui_theme=getattr(view, "ui_theme", "Light")' in controller
    assert 'command == "set_theme"' in runtime
    assert 'initial.get("ui_theme", "Light")' in runtime
    assert "def refresh_open_dialog_themes" in dialog
    assert "def refreshTheme(self)" in dialog


def test_dialog_specific_palette_surfaces_refresh_in_place():
    root = Path(__file__).resolve().parents[1]
    selector = (root / "WinUx/dialogs/selectors/local_folder_form.py").read_text(encoding="utf-8")
    transfer = (root / "WinUx/dialogs/transfer/transfer_center_form.py").read_text(encoding="utf-8")
    reference = (root / "WinUx/dialogs/reference/reference_chart_form.py").read_text(encoding="utf-8")
    console = (root / "WinUx/dialogs/console/console_form.py").read_text(encoding="utf-8")
    tooltip = (root / "DearUIQt/tooltip.py").read_text(encoding="utf-8")
    native = (root / "WinUx/ui/native/native_dialog_host.py").read_text(encoding="utf-8")
    lifecycle = (root / "WinUx/ui/behaviors/window/lifecycle.py").read_text(encoding="utf-8")

    assert "def _refresh_theme_surfaces(self)" in selector
    assert "BrowserListPalette.refresh_application_palette(color_scheme())" in selector
    assert "def _refresh_theme_surfaces(self)" in transfer
    assert "def _refresh_theme_surfaces(self)" in reference
    assert "def _refresh_theme_surfaces(self)" in console
    assert "def invalidate_tooltip_theme_cache" in tooltip
    assert "def apply_native_theme_chrome" in native
    assert "DWMWA_USE_IMMERSIVE_DARK_MODE" in native
    assert "apply_native_theme_chrome(hwnd)" in lifecycle


def test_live_dark_switch_rebinds_dialog_raw_surfaces_and_retained_lists():
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    containers = (root / "DearUIQt/widgets/containers.py").read_text(encoding="utf-8")
    list_view = (root / "DearUIQt/modelview/list.py").read_text(encoding="utf-8")
    style = (root / "DearUIQt/gui/style.py").read_text(encoding="utf-8")

    # Raw DPG helpers must retain their theme factory so a live theme switch
    # can rebind label cells, notes/status text, navigation panes and tables.
    assert "self._palette_theme_bindings = {}" in dialog
    assert "def _bind_palette_theme(self, item, provider)" in dialog
    assert "self._refresh_palette_theme_bindings()" in dialog
    assert "self._bind_palette_theme(panel, navigation_theme)" in dialog
    assert "self._bind_palette_theme(label_cell, lambda: form_label_cell_theme(dpg))" in dialog

    # Retained containers/item views must also repaint resources that were
    # materialized while the previous palette was active.
    assert "class ImGuiGroupBox" in containers
    assert "def refreshTheme(self):" in containers
    assert "def refreshTheme(self):" in list_view
    assert "self._row_visual_full_sync = True" in list_view

    # QPushButton faces must not remain hard-coded white in Dark mode.
    assert 'dark = color_scheme() == "Dark"' in style
    assert "raised_face = p.BUTTON if dark" in style
    assert "backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)" in style


def test_native_dialog_caption_forces_live_non_client_repaint():
    root = Path(__file__).resolve().parents[1]
    native = (root / "WinUx/ui/native/native_dialog_host.py").read_text(encoding="utf-8")
    assert "set_dwm(19, 1 if dark else 0)" in native
    assert "SWP_FRAMECHANGED" in native
    assert "RDW_FRAME" in native
    assert "RedrawWindow" in native


def test_live_theme_refresh_reaches_retained_menus_and_dock_chrome():
    root = Path(__file__).resolve().parents[1]
    menu_bar = (root / "DearUIQt/widgets/menu_bar.py").read_text(encoding="utf-8")
    menu = (root / "DearUIQt/widgets/menu.py").read_text(encoding="utf-8")
    dock = (root / "DearUIQt/docking/dock_widget.py").read_text(encoding="utf-8")
    appearance = (root / "WinUx/ui/appearance.py").read_text(encoding="utf-8")
    plots = (root / "WinUx/ui/components/job_plots.py").read_text(encoding="utf-8")

    # Top-level File/Bookmarks/... menus must refresh their popup surfaces, not
    # only the menu-bar buttons. Retained context menus also self-heal before
    # opening if they were created under the previous palette.
    assert "menu.refreshTheme()" in menu_bar
    assert 'color_scheme() != getattr(self, "_palette_scheme", None)' in menu

    # QDockWidget owns retained title/content/control resources and therefore
    # needs an explicit live refresh path for the SSH Console/Plots headers.
    assert "def refreshTheme(self):" in dock
    assert "self._title_theme = dock_title_theme(dpg, active=True)" in dock
    assert "def _ensure_theme_current(self):" in dock
    assert "self._ensure_theme_current()" in dock
    assert "QtFusionPalette.TITLE_ACTIVE" in dock
    assert "dpg.configure_item(self.title_text, color=self.TEXT_COLOR)" in dock
    assert "console_dock.refreshTheme()" in appearance

    # Lazy Job Plot docks use the same retained refresh contract.
    assert "def refreshTheme(self):" in plots
    assert 'if color_scheme() == "Light" else QtFusionPalette.TEXT' in plots
