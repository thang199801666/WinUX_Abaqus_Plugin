from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.ui.behaviors.console_docking import ConsoleDockingMixin
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin
from WinUx.dialogs import native_dock_hosts


class Host:
    def __init__(self, view, panel, on_dock, on_closed, **kwargs):
        self.on_dock, self.on_closed = on_dock, on_closed
        self.alive = True
        self.post = Mock(return_value=True)
        self.show = Mock()

    def winfo_exists(self):
        return self.alive

    def destroy(self):
        self.alive = False
        self.on_closed(self)


def console_view():
    view = ConsoleDockingMixin()
    view._console_dock_mode = "docked"
    view._console_dock_visible = True
    view.console_panel = SimpleNamespace(_hide_context_menu=Mock(), _selection_dragging=True)
    view.console_dock = SimpleNamespace(root=1, set_floating=Mock())
    view._cancel_console_float_interaction = Mock()
    view._set_console_keyboard_active = Mock()
    view.set_console_visible = Mock()
    view.hide_console = Mock()
    return view


def test_console_float_and_redock_use_native_host_and_confirm_editor_before_close(monkeypatch):
    import WinUx.ui.behaviors.console_docking as module
    backend = Mock()
    monkeypatch.setattr(module, "dpg", backend)
    monkeypatch.setattr(native_dock_hosts, "ConsoleDockHost", Host)
    view = console_view()
    assert view.undock_console()
    host = view._native_console_host
    assert view._console_dock_mode == "floating"
    view._cancel_console_float_interaction.assert_called_once()
    view._set_console_keyboard_active.assert_called_once_with(False)
    assert not view.console_panel._selection_dragging
    backend.add_window.assert_not_called()
    backend.move_item.assert_not_called()
    assert view.dock_console()
    host.post.assert_called_once_with("request_dock")
    assert host.alive and view._console_dock_mode == "floating"
    host.on_dock(host)
    assert not host.alive and view._native_console_host is None
    assert view._console_dock_mode == "docked"
    view.hide_console.assert_not_called()


def test_old_console_close_callback_cannot_hide_a_new_host(monkeypatch):
    import WinUx.ui.behaviors.console_docking as module
    monkeypatch.setattr(module, "dpg", Mock())
    monkeypatch.setattr(native_dock_hosts, "ConsoleDockHost", Host)
    view = console_view()
    view.undock_console()
    old = view._native_console_host
    view._native_console_host = object()
    old.on_closed(old)
    view.hide_console.assert_not_called()


def test_floating_console_cannot_reacquire_main_keyboard_hook():
    view = console_view()
    view._console_dock_mode = "floating"
    view._console_keyboard_panel = view.console_panel
    ConsoleDockingMixin._set_console_keyboard_active(view, True)
    assert view._console_keyboard_panel is None


def test_plot_tearoff_keeps_model_and_releases_tab_capture(monkeypatch):
    import WinUx.ui.behaviors.plot_docking as module
    backend = Mock()
    monkeypatch.setattr(module, "dpg", backend)
    monkeypatch.setattr(native_dock_hosts, "PlotDockHost", Host)
    panel = SimpleNamespace(exists=lambda: True, root=1, end_pointer_capture=Mock(), set_dock_mode=Mock())
    view = PlotDockingMixin()
    view.job_plot_windows = {"job": panel}
    view.plot_dock_manager = Mock()
    view.plot_dock_manager.has_docked.return_value = False
    view._set_plot_dock_preview = Mock()
    view._set_plot_dock_open = Mock()
    view._sync_job_plot_menu_state = Mock()
    view._apply_split_layout = Mock()
    view.close_job_plots = Mock()
    assert view.undock_job_plots("job")
    host = view._native_plot_hosts["job"]
    assert view.job_plot_windows["job"] is panel
    panel.end_pointer_capture.assert_called_once()
    view.plot_dock_manager._reset_tab_drag.assert_called_once()
    backend.add_window.assert_not_called()
    backend.move_item.assert_not_called()
    host.destroy()
    view.close_job_plots.assert_called_once_with("job")
    assert not view._native_plot_hosts
