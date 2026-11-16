import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt.widgets import QMainWindow
from WinUx.ui.behaviors.window.startup_docking import StartupDockingMixin


class _MainWindowStub:
    def __init__(self):
        self.config = None
        self.manager = SimpleNamespace(name="manager")
        self.restored = []
        self.saved = {"format": 3, "version": 1, "order": ["plot-a"], "docks": []}
        self._dock_manager = self.manager

    def configureDockManager(self, **options):
        self.config = dict(options)
        return self

    def dockManager(self):
        return self.manager

    def restoreState(self, state, version=0):
        self.restored.append((state, version))
        return True

    def saveState(self, version=0):
        value = dict(self.saved)
        value["version"] = int(version)
        return value


class _View(StartupDockingMixin):
    PLOT_DOCK_DEFAULT_RATIO = 0.5
    PLOT_DOCK_AREAS = ("left", "right", "top", "bottom")
    CONSOLE_DOCK_DEFAULT_WIDTH = 320
    CONSOLE_DOCK_DEFAULT_HEIGHT = 220

    def __init__(self):
        self.plot_dock_manager = None
        self.plot_region = "plot-region"
        self._plot_dock_area = "right"
        self._persisted_dock_state = {
            "qt_main_window": {"format": 3, "version": 1, "order": ["late"], "docks": []}
        }
        self._main_window = _MainWindowStub()
        self._job_plot_tab_activated = Mock()
        self._job_plot_tab_tearoff = Mock()
        self._plot_default_mode = "docked"
        self._plot_dock_visible = False
        self._plot_dock_scope = "inner"
        self._plot_split_ratios = {area: 0.5 for area in self.PLOT_DOCK_AREAS}
        self._plot_saved_float_geometry = {}
        self._console_dock_visible = False
        self._console_dock_mode = "docked"
        self._console_dock_area = "bottom"
        self._console_dock_scope = "inner"
        self._console_dock_width = self.CONSOLE_DOCK_DEFAULT_WIDTH
        self._console_dock_height = self.CONSOLE_DOCK_DEFAULT_HEIGHT
        self.job_plot_windows = {}
        self._empty_job_plot_window = None


class WinUxQMainWindowMigrationM4gTests(unittest.TestCase):
    def test_plot_manager_is_owned_by_qmainwindow_with_existing_plot_host(self):
        view = _View()
        manager = view._ensure_plot_dock_manager()
        self.assertIs(manager, view._main_window.manager)
        self.assertEqual(view._main_window.config["parent"], "plot-region")
        self.assertEqual(view._main_window.config["dock_area"], "right")
        self.assertEqual(view._main_window.config["tab_position"], "bottom")
        self.assertIs(view.plot_dock_manager, manager)
        self.assertEqual(len(view._main_window.restored), 1)
        self.assertEqual(view._main_window.restored[0][1], 1)

    def test_collect_state_persists_qmainwindow_state_without_losing_legacy_fields(self):
        view = _View()
        state = view._collect_dock_state()
        self.assertEqual(state["version"], 3)
        self.assertEqual(state["qt_main_window"]["version"], 1)
        self.assertIn("console", state)
        self.assertIn("plot", state)
        self.assertEqual(state["plot"]["area"], "right")

    def test_collect_state_keeps_previous_qmainwindow_state_before_lazy_manager_exists(self):
        view = _View()
        view._main_window._dock_manager = None
        old = dict(view._persisted_dock_state["qt_main_window"])
        state = view._collect_dock_state()
        self.assertEqual(state["qt_main_window"], old)


class QMainWindowDockHostConfigurationTests(unittest.TestCase):
    def test_configure_dock_manager_records_lazy_host_options(self):
        window = QMainWindow.__new__(QMainWindow)
        window._dock_manager = None
        window._dock_manager_options = {}
        window._require_ui = lambda: None
        result = window.configureDockManager(parent="dock-host", dock_area="left")
        self.assertIs(result, window)
        self.assertEqual(window._dock_manager_options,
                         {"parent": "dock-host", "dock_area": "left"})

    def test_configure_dock_manager_rejects_reconfiguration_after_materialization(self):
        window = QMainWindow.__new__(QMainWindow)
        window._dock_manager = object()
        window._dock_manager_options = {}
        window._require_ui = lambda: None
        with self.assertRaises(RuntimeError):
            window.configureDockManager(parent="other")


if __name__ == "__main__":
    unittest.main()
