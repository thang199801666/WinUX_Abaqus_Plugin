"""Settings is a Home ribbon command, not a digitizing workflow step."""
import ast
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class _FakeSignal:
    def connect(self, callback):
        self.callback = callback


class _FakeAction:
    def __init__(self, *args, **kwargs):
        self.triggered = _FakeSignal()
        self.changed = _FakeSignal()

    def isEnabled(self):
        return True


class _FakeRibbon:
    def __init__(self, *args, **kwargs):
        self.tabs = []
        self.groups = []
        self.buttons = {}

    def add_tab(self, key, label, **kwargs):
        self.tabs.append((key, label, kwargs))

    def add_group(self, tab, key, label, **kwargs):
        self.groups.append((tab, key, label, kwargs))

    def add_button(self, tab, group, key, label, callback, **kwargs):
        assert key not in self.buttons, "Ribbon command keys must be unique"
        self.buttons[key] = (tab, group, label, callback, kwargs)
        return key


def test_settings_button_visible_on_default_home_ribbon():
    form = object.__new__(PlotDigitizerDialog)
    form.content = object()
    form.view = SimpleNamespace(after=Mock())
    form.own_widget = lambda widget: widget
    form._refresh_history_commands = Mock()
    form._show_tool = Mock()
    with patch("WinUx.plotdigitizer.ui.dialog.RibbonBar", _FakeRibbon), patch(
        "WinUx.plotdigitizer.ui.dialog.QAction", _FakeAction
    ):
        form._build_toolbar()
    assert form.ribbon.tabs[0][0] == "home"
    assert form.ribbon.tabs[0][2].get("activate") is True
    tab, group, label, callback, kwargs = form.ribbon.buttons["settings"]
    assert (tab, group, label) == ("home", "preferences", "Settings")
    assert kwargs["image"].endswith("settings.png")
    assert any((t, k) == ("home", "preferences") for t, k, _, _ in form.ribbon.groups)
    callback()
    form._show_tool.assert_called_once_with("settings")
    assert all(key != "settings" for key, (tab, _, _, _, _) in form.ribbon.buttons.items()
               if tab == "view")


def test_workflow_contains_only_digitizing_steps():
    source = inspect.getsource(PlotDigitizerDialog._build_dataset_panel)
    tree = ast.parse(textwrap.dedent(source))
    keys = [node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "QtListItem" and node.args
            and isinstance(node.args[0], ast.Constant)]
    assert keys == ["axes", "manual", "automatic", "data"]


def test_ribbon_settings_clears_workflow_selection_and_back_navigation():
    form = object.__new__(PlotDigitizerDialog)
    form._tool_pages = {"axes": "axes-page", "data": "data-page", "settings": "settings-page"}
    form._active_tool = "axes"
    form._pick_mode = None
    form.settings_panel = "right-panel"
    form.result_grid = object()
    form.set_control_visible = Mock()
    form._refresh_point_editor = Mock()

    class _Workflow:
        current = "axes"

        def __init__(self):
            self.selected = {"axes"}
            self.selection_clears = 0

        def currentKey(self):
            return self.current

        def clearSelection(self):
            self.selection_clears += 1
            self.selected.clear()

        def setCurrentKey(self, key, select=True):
            self.current = key
            if select:
                self.selected = {key}

    form.tool_list = _Workflow()
    with patch("WinUx.plotdigitizer.ui.dialog.QRetainedItem") as retained:
        form._show_tool("settings")
        retained.assert_called_with("right-panel")
        assert form._active_tool == "settings"
        assert form.tool_list.currentKey() is None
        assert form.tool_list.selected == set()
        assert form.active_table is None
        assert form.set_control_visible.call_args_list[-1].args == ("settings-page", True)
        form._show_tool("data")
        assert form._active_tool == "data"
        assert form.tool_list.currentKey() == "data"
        assert form.tool_list.selected == {"data"}
        assert form.active_table is form.result_grid
