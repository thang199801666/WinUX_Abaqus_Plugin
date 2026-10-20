"""Regression coverage for the embedded/persistent SSH Console dock."""
from pathlib import Path
import tempfile

from WinUx.preferences.general import GeneralPreferences


ROOT = Path(__file__).resolve().parents[1]
VIEW_SOURCE = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
SPLITTER_SOURCE = (ROOT / "WinUx" / "ui" / "behaviors" / "splitter_behavior.py").read_text(encoding="utf-8")
CONSOLE_DOCK_SOURCE = (ROOT / "WinUx" / "ui" / "behaviors" / "console_docking.py").read_text(encoding="utf-8")
PLOT_DOCK_SOURCE = (ROOT / "WinUx" / "ui" / "behaviors" / "plot_docking.py").read_text(encoding="utf-8")
VIEW_RUNTIME_SOURCE = "\n".join((VIEW_SOURCE, SPLITTER_SOURCE, PLOT_DOCK_SOURCE, CONSOLE_DOCK_SOURCE))
CONSOLE_SOURCE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")


def test_console_visibility_defaults_hidden_and_persists():
    with tempfile.TemporaryDirectory() as root:
        prefs = GeneralPreferences(root=root)
        assert prefs.load_console_visible() is False
        prefs.save_console_visible(True)
        assert GeneralPreferences(root=root).load_console_visible() is True
        prefs.save_console_visible(False)
        assert GeneralPreferences(root=root).load_console_visible() is False


def test_console_visibility_save_preserves_other_general_settings():
    with tempfile.TemporaryDirectory() as root:
        prefs = GeneralPreferences(root=root)
        prefs.save_auto_login(True)
        prefs.save_console_visible(True)
        loaded = prefs.load()
        assert loaded["auto_login"] is True
        assert loaded["console_visible"] is True


def test_console_is_embedded_in_bottom_dock_instead_of_floating_dialog():
    assert "self.console_dock = DockWidget(" in VIEW_SOURCE
    assert '"SSH Console"' in VIEW_SOURCE
    assert 'dock_area="bottom"' in VIEW_SOURCE
    assert "allowed_areas=DockWidget.BottomDockWidgetArea" in VIEW_SOURCE
    assert "self.console_panel = ConsoleDockPanel(" in VIEW_SOURCE
    show_start = CONSOLE_DOCK_SOURCE.index("    def show_console(self):")
    show_block = CONSOLE_DOCK_SOURCE[show_start:]
    assert '_dialog_type("ConsoleDialog")' not in show_block
    assert "set_console_visible(" in show_block


def test_console_sits_below_job_and_plot_workspace_when_visible():
    assert "workspace_height = bottom_height" in VIEW_RUNTIME_SOURCE
    assert "console_y = (" in VIEW_RUNTIME_SOURCE
    assert "bottom_y + workspace_height" in VIEW_RUNTIME_SOURCE
    assert "self.console_region," in VIEW_SOURCE
    assert "pos=(0, console_y)" in VIEW_RUNTIME_SOURCE


def test_console_view_action_tracks_and_persists_visibility():
    assert "console_action = self.console_dock.toggleViewAction()" in VIEW_SOURCE
    assert "self.console_menu_item = console_action" in VIEW_SOURCE
    assert "self._general_preferences.save_console_visible(visible)" in VIEW_RUNTIME_SOURCE
    assert "on_close=self.hide_console" in VIEW_SOURCE
    assert "dock.set_visible(visible, notify=False)" in VIEW_RUNTIME_SOURCE


def test_embedded_console_reuses_terminal_engine_and_main_view_keyboard_hook():
    assert "class ConsoleDockPanel(ConsoleDialog):" in CONSOLE_SOURCE
    assert "def keyboard_active(self):" in CONSOLE_SOURCE
    assert "def _install_console_character_hook(self):" in VIEW_SOURCE
    assert "WM_CHAR = 0x0102" in VIEW_SOURCE
    assert "panel.native_character" in VIEW_SOURCE


def test_console_dock_has_qt_like_resizable_splitter():
    # The console splitter is a shared QSplitterHandle widget: one painted
    # line plus a full-width transparent grab gutter (its hitbox tag), and the
    # drag/input interaction runs through the per-frame splitter behavior.
    assert "self._console_splitter_handle = QSplitterHandle(" in VIEW_SOURCE
    assert "self.console_separator = self._console_splitter_handle.lineTag()" in VIEW_SOURCE
    assert "self.console_separator_hitbox = self._console_splitter_handle.hitBoxTag()" in VIEW_SOURCE
    assert "def _drag_console_splitter(self):" in VIEW_RUNTIME_SOURCE
    assert "self._console_dock_height" in VIEW_SOURCE
    assert "self._update_console_splitter_input)" in VIEW_RUNTIME_SOURCE


def test_console_dock_default_is_hidden_but_restored_from_preferences():
    assert "DEFAULT_CONSOLE_VISIBLE = False" in (ROOT / "WinUx" / "preferences" / "general.py").read_text(encoding="utf-8")
    assert "self._console_dock_visible = bool(" in VIEW_SOURCE
    assert "load_console_visible()" in VIEW_SOURCE


def test_console_dock_can_be_torn_off_and_docked_back_like_qdockwidget():
    assert "features=DockWidget.AllDockWidgetFeatures" in VIEW_SOURCE
    assert "on_float_change=self._console_float_requested" in VIEW_SOURCE
    assert "def _on_console_dock_header_drag(" in VIEW_RUNTIME_SOURCE
    assert "self.console_dock.dragHandleWidget().isActive()" in VIEW_RUNTIME_SOURCE
    assert "def undock_console(" in VIEW_RUNTIME_SOURCE
    assert "host = ConsoleDockHost(self, self.console_panel, dock, closed, drag_anchor=drag_anchor)" in CONSOLE_DOCK_SOURCE
    assert "dpg.add_window(" not in CONSOLE_DOCK_SOURCE
    assert "self.console_dock.set_floating(True)" in VIEW_RUNTIME_SOURCE
    assert "def dock_console(self, *, _native_confirmed=False):" in VIEW_RUNTIME_SOURCE
    assert 'return host.post("request_dock")' in CONSOLE_DOCK_SOURCE
    assert "self.console_dock.set_floating(False)" in VIEW_RUNTIME_SOURCE


def test_console_float_uses_native_resize_instead_of_overlay_resize_controller():
    assert "self._dock_drop_preview = DockDropPreview()" in VIEW_SOURCE
    assert "def _console_dock_target_at_pointer(self):" in VIEW_RUNTIME_SOURCE
    assert "def _set_console_dock_preview(self, visible):" in VIEW_RUNTIME_SOURCE
    assert "DOCK_SNAP_DISTANCE = 56" in VIEW_SOURCE
    assert "self._point_near_rect(" in VIEW_RUNTIME_SOURCE
    hosts = (ROOT / "WinUx" / "dialogs" / "native_dock_hosts.py").read_text(encoding="utf-8")
    assert "modal=False, resizable=True" in hosts
    assert "self._update_floating_console_resize_interaction)" in VIEW_RUNTIME_SOURCE
    assert "self._update_floating_console_docking)" in VIEW_RUNTIME_SOURCE


def test_floating_console_does_not_reserve_bottom_dock_space():
    assert 'and self._console_dock_mode == "docked")' in VIEW_RUNTIME_SOURCE
    assert 'docked_visible = bool(' in VIEW_RUNTIME_SOURCE
    assert 'self._console_dock_mode == "docked")' in VIEW_RUNTIME_SOURCE


def test_embedded_console_initializes_qobject_receiver_lifecycle():
    # ConsoleDockPanel deliberately skips QtDialog.__init__ because it is an
    # embedded dock, but it is still a QObject subclass. QTimer signal binding
    # therefore requires the QObject receiver state to exist.
    start = CONSOLE_SOURCE.index("class ConsoleDockPanel(ConsoleDialog):")
    block = CONSOLE_SOURCE[start:]
    assert "QObject.__init__(self, after=view.after)" in block
    assert "self._refresh_timer = QTimer(self)" in block
    assert "self._paint_timer = QTimer(self)" in block
    assert "QObject.delete(self)" in block
