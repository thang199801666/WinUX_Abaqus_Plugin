"""Plot dock persistence regressions."""
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.ui.behaviors.plot_docking import PlotDockingMixin
from WinUx.dialogs.native_dock_hosts import PlotDockHost
from WinUx.view import WinUXView


class _Dock:
    def __init__(self):
        self.visible = False
    def set_visible(self, value, notify=False):
        self.visible = bool(value)


class _Placeholder:
    def __init__(self):
        self.dock = _Dock()
        self.dock_mode = "docked"
        self.waiting = None
        self.focused = False
    def exists(self):
        return True
    def set_waiting(self, text):
        self.waiting = text
    def focus(self):
        self.focused = True


class _View(PlotDockingMixin):
    def __init__(self):
        self._plot_dock_visible = False
        self._plot_dock_open = False
        self._empty_job_plot_window = None
        self._native_plot_hosts = {}
        self._native_plot_pending_hosts = {}
        self._plot_float_geometries = {}
        self._plot_saved_float_geometry = {}
        self.job_plot_windows = {}
        self.job_plot_float_windows = {}
        self._plot_float_last_positions = {}
        self._plot_float_dragging = set()
        self._plot_synthetic_float_drag = {}
        self._plot_float_resizers = {}
        self.persist_count = 0
        self.layout_count = 0
        self.sync_count = 0
    def _ensure_empty_job_plot_window(self):
        if self._empty_job_plot_window is None:
            self._empty_job_plot_window = _Placeholder()
        return self._empty_job_plot_window
    def _set_plot_dock_open(self, opened):
        self._plot_dock_open = bool(opened)
    def _apply_split_layout(self, force=False):
        self.layout_count += 1
    def _sync_plots_view_action(self):
        self.sync_count += 1
        return True
    def _persist_dock_state(self):
        self.persist_count += 1
        return True
    def _set_plot_dock_preview(self, *args, **kwargs):
        pass


class PlotDockPersistenceTests(unittest.TestCase):
    def test_visibility_has_console_style_persist_contract(self):
        view = _View()
        self.assertTrue(view.set_plots_visible(True, persist=False))
        self.assertTrue(view._plot_dock_visible)
        self.assertTrue(view._empty_job_plot_window.dock.visible)
        self.assertEqual(view.persist_count, 0)

        self.assertTrue(view.set_plots_visible(False, persist=True))
        self.assertFalse(view._plot_dock_visible)
        self.assertFalse(view._empty_job_plot_window.dock.visible)
        self.assertEqual(view.persist_count, 1)

    def test_hidden_resident_host_does_not_recheck_view_action(self):
        view = _View()
        view._plot_dock_visible = False
        action = SimpleNamespace(setEnabled=Mock(), setChecked=Mock())
        view.plots_menu_item = action

        @contextmanager
        def blocker(_action):
            yield _action

        with patch("DearUIQt.core.QSignalBlocker", blocker):
            self.assertTrue(PlotDockingMixin._sync_plots_view_action(view))
        action.setEnabled.assert_called_once_with(True)
        action.setChecked.assert_called_once_with(False)

    def test_hidden_docked_resident_does_not_overwrite_float_geometry(self):
        view = _View()
        panel = SimpleNamespace(dock_mode="docked", exists=lambda: True)
        view.job_plot_windows["42"] = panel
        host = SimpleNamespace(_hwnd=123, _native_visible=False)
        view._native_plot_hosts = {"42": host}
        view._plot_saved_float_geometry = {"pos": (10, 20), "size": (800, 450)}
        with patch("WinUx.ui.native.floating_viewport.window_rect",
                   return_value=(101, 202, 1001, 702)):
            self.assertIsNone(view._remember_plot_native_host_geometry("42", host))
        self.assertEqual(view._plot_saved_float_geometry,
                         {"pos": (10, 20), "size": (800, 450)})

    def test_native_float_geometry_updates_persistent_geometry(self):
        view = _View()
        host = SimpleNamespace(_hwnd=123)
        view._native_plot_hosts = {"42": host}
        with patch("WinUx.ui.native.floating_viewport.window_rect",
                   return_value=(101, 202, 1001, 702)):
            geometry = view._remember_plot_native_host_geometry("42", host)
        self.assertEqual(geometry, {"pos": (101, 202), "size": (900, 500)})
        self.assertEqual(view._plot_saved_float_geometry, geometry)
        self.assertEqual(view._plot_float_geometries["42"], geometry)

    def test_startup_restore_replays_plot_visibility_without_resaving(self):
        view = SimpleNamespace(
            _alive=True, _qapplication=None,
            _console_dock_visible=False, _console_dock_mode="docked",
            _plot_dock_visible=True, _plot_default_mode="floating",
            set_plots_visible=Mock(), _sync_plots_view_action=Mock(),
            _set_plot_dock_open=Mock(), _apply_split_layout=Mock(),
            after=Mock())
        WinUXView._restore_persisted_dock_runtime(view)
        view.set_plots_visible.assert_called_once_with(True, persist=False)

    def test_plot_host_receives_saved_geometry_for_child_viewport(self):
        panel = SimpleNamespace(
            _native_revision=1, label="Plots", job_id="42", job_name="Job",
            native_snapshot=lambda: {"series": []})
        captured = {}

        def fake_init(controller, view, kind, title, payload=None, **kwargs):
            captured.update(kind=kind, title=title, payload=payload, kwargs=kwargs)

        geometry = {"pos": (100, 120), "size": (900, 500)}
        with patch("WinUx.ui.hosting.floating_dialog.FloatingDialogController.__init__", fake_init):
            PlotDockHost(SimpleNamespace(after=Mock()), panel, Mock(), Mock(),
                         visible=False, saved_geometry=geometry)
        self.assertEqual(captured["kind"], "plot_dock")
        self.assertEqual(captured["payload"]["_saved_geometry"], geometry)
        self.assertFalse(captured["kwargs"]["visible"])


if __name__ == "__main__":
    unittest.main()
