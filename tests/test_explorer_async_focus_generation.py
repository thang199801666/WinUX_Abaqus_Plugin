from types import SimpleNamespace

from WinUx.controllers.explorer.navigation import NavigationController


class ListView:
    def __init__(self):
        self.serial = 0
    def interactionSerial(self):
        return self.serial


class Panel:
    panel_id = 'local'
    def __init__(self):
        self.listview = ListView()
        self.current_path = None
        self.focus_calls = 0
        self.display_calls = 0
    def display(self, path, items, record_history=True):
        self.current_path = path
        self.display_calls += 1
    def focus(self):
        self.focus_calls += 1


class Prefs:
    def save_local(self, path):
        pass
    def save_server(self, *args):
        pass


class App:
    def __init__(self):
        self._closing = False
        self._initial_load_pending = True
        self._local_nav_generation = 1
        self._server_nav_generation = 1
        self.navigation_preferences = Prefs()
        self.view = SimpleNamespace(winfo_exists=lambda: True, left=Panel())
        self.model = SimpleNamespace()
        self.server = SimpleNamespace(connected=True)
        self.watch_calls = 0
    def _watch_local_path(self, path):
        self.watch_calls += 1


def test_initial_async_result_does_not_steal_focus_after_user_interaction():
    app = App()
    nav = NavigationController(app)
    nav._initial_focus_serial = app.view.left.listview.interactionSerial()
    app.view.left.listview.serial += 1
    nav.initial_loaded('C:/work', [])
    assert app.view.left.display_calls == 1
    assert app.view.left.focus_calls == 0


def test_initial_async_result_can_focus_when_user_did_not_interact():
    app = App()
    nav = NavigationController(app)
    nav._initial_focus_serial = app.view.left.listview.interactionSerial()
    nav.initial_loaded('C:/work', [])
    assert app.view.left.focus_calls == 1


def test_local_navigation_result_does_not_restore_stale_focus():
    app = App()
    nav = NavigationController(app)
    panel = app.view.left
    nav._focus_serial_by_request[('local', 1)] = panel.listview.interactionSerial()
    panel.listview.serial += 1
    nav.local_loaded(panel, 'C:/next', [], True, 1)
    assert panel.display_calls == 1
    assert panel.focus_calls == 0


def test_local_navigation_result_restores_focus_without_intervening_input():
    app = App()
    nav = NavigationController(app)
    panel = app.view.left
    nav._focus_serial_by_request[('local', 1)] = panel.listview.interactionSerial()
    nav.local_loaded(panel, 'C:/next', [], True, 1)
    assert panel.focus_calls == 1
