from types import SimpleNamespace
from unittest.mock import Mock, patch

import WinUx.dialogs.local_folder_form as module


class _Backend:
    mvKey_Spacebar = 32
    mvKey_Return = 13

    def __init__(self, host_scroll=0.0, table_scroll=0.0):
        self.scroll = {100: float(host_scroll), 500: float(table_scroll)}
        self.writes = []

    def get_y_scroll(self, tag):
        return self.scroll.get(tag, 0.0)

    def set_y_scroll(self, tag, value):
        value = float(value)
        self.scroll[tag] = value
        self.writes.append((tag, value))

    def is_key_down(self, _key):
        return False


class _Table:
    tag = 500
    _deleted = False


def _view(host_scroll=0.0, table_scroll=0.0):
    view = object.__new__(module.FolderListView)
    view.tag = 100
    view.backend = _Backend(host_scroll, table_scroll)
    view._details_table = _Table()
    view._deleted = False
    view._qt_bridge_click = None
    return view


def test_selector_has_exactly_one_vertical_scroll_owner():
    view = _view(host_scroll=84.0, table_scroll=615.0)
    assert view.verticalScrollValue() == 615.0
    assert view.backend.scroll[100] == 0.0
    assert (100, 0.0) in view.backend.writes


def test_selector_scroll_writes_only_the_details_table():
    view = _view(host_scroll=37.0, table_scroll=10.0)
    view.backend.writes.clear()
    assert view.setVerticalScrollValue(240.0) is view
    assert view.backend.scroll[100] == 0.0
    assert view.backend.scroll[500] == 240.0
    assert (500, 240.0) in view.backend.writes


def test_hit_test_route_arms_bridge_for_non_qt_pointer_paths():
    view = _view()
    view.items = {"deep-row": 1234}
    view.nativeItem = lambda key: view.items.get(key)
    view._clicked = Mock()
    app = SimpleNamespace(frameCount=lambda: 77)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=app):
        assert view._route_pointer_key("deep-row") is True
    view._clicked.assert_called_once_with(1234, True, "deep-row")
    assert view._qt_bridge_click[:2] == ("deep-row", 77)


def test_delayed_native_callback_cannot_retarget_first_row_after_routed_click():
    view = _view()
    view.items = {"deep-row": 1234, "first-row": 1000}
    view._values = [
        SimpleNamespace(key="first-row", enabled=True),
        SimpleNamespace(key="deep-row", enabled=True),
    ]
    view._last_click_frame = None
    view._last_click_key = "deep-row"
    view._last_click_at = 0.0
    view._qt_bridge_click = ("deep-row", 77, 0.0)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance",
               return_value=SimpleNamespace(frameCount=lambda: 78)), \
         patch("WinUx.dialogs.local_folder_form.QtListView._clicked") as base_clicked:
        view._clicked(1000, True, "first-row")
    base_clicked.assert_not_called()
