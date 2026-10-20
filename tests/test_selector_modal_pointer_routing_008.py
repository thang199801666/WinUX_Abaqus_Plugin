"""Regression tests for file/folder row input in in-process modal selectors."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.core import QEvent, QMouseEvent, Qt
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.dialogs.local_folder_form import LocalFolderDialog, FolderListView
from WinUx.dialogs.local_file_form import LocalFileDialog


def _event_dialog(dialog_class=LocalFolderDialog, *, owns_modal=True, hit=True):
    dialog = object.__new__(dialog_class)
    dialog.listbox = SimpleNamespace(current="row", selected={"row"}, _qt_bridge_click=None)
    dialog._selector_pointer_hit = Mock(return_value=hit)
    application = SimpleNamespace(activeModalWidget=lambda: dialog if owns_modal else object(),
                                  frameCount=lambda: 21)
    return dialog, application


def test_modal_qt_pointer_press_dispatches_selected_row():
    dialog, app = _event_dialog()
    event = QMouseEvent(QEvent.MouseButtonPress, (200, 125),
                        button=Qt.LeftButton, buttons=Qt.LeftButton)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=app):
        assert dialog.event(event) is True
    dialog._selector_pointer_hit.assert_called_once_with(event.globalPosition())
    assert dialog.listbox._qt_bridge_click[:2] == ("row", 21)


def test_file_selector_inherits_same_modal_row_routing():
    dialog, app = _event_dialog(LocalFileDialog)
    event = QMouseEvent(QEvent.MouseButtonPress, (120, 90),
                        button=Qt.LeftButton, buttons=Qt.LeftButton)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=app):
        assert dialog.event(event) is True
    assert dialog._selector_pointer_hit.called


def test_background_modal_does_not_select_underlying_selector():
    dialog, app = _event_dialog(owns_modal=False)
    event = QMouseEvent(QEvent.MouseButtonPress, (120, 90),
                        button=Qt.LeftButton, buttons=Qt.LeftButton)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=app), \
         patch.object(QtDialog, "event", return_value=False) as fallback:
        assert dialog.event(event) is False
    dialog._selector_pointer_hit.assert_not_called()
    fallback.assert_called_once_with(event)


def test_non_row_press_leaves_modal_dialog_controls_available():
    dialog, app = _event_dialog(hit=False)
    event = QMouseEvent(QEvent.MouseButtonPress, (120, 90),
                        button=Qt.LeftButton, buttons=Qt.LeftButton)
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=app), \
         patch.object(QtDialog, "event", return_value=False) as fallback:
        assert dialog.event(event) is False
    assert dialog.listbox._qt_bridge_click is None
    fallback.assert_called_once_with(event)


def test_native_recovery_rejects_other_modal_and_popup():
    dialog = object.__new__(LocalFolderDialog)
    dialog._selector_pointer_hit = Mock(return_value=True)
    with patch("DearUIQt.input_gate.native_background_input_blocked", return_value=False), \
         patch("WinUx.dialogs.local_folder_form.QApplication.instance",
               return_value=SimpleNamespace(activeModalWidget=lambda: object())):
        assert dialog.native_pointer_press((20, 30)) is False
    dialog._selector_pointer_hit.assert_not_called()


def test_modal_bridge_deferred_callback_does_not_trigger_false_doubleclick():
    view = object.__new__(FolderListView)
    view._deleted = False
    view.items = {"entry": 101}
    view._values = [SimpleNamespace(key="entry", enabled=True)]
    view._last_click_frame = (101, 21)
    view._qt_bridge_click = ("entry", 21, __import__("time").monotonic())
    view._last_click_key = "entry"
    view._last_click_at = __import__("time").monotonic()
    with patch("WinUx.dialogs.local_folder_form.QApplication.instance",
               return_value=SimpleNamespace(frameCount=lambda: 22)), \
         patch("WinUx.dialogs.local_folder_form.QtListView._clicked") as native:
        view._clicked(101, True, "entry")
    native.assert_not_called()


def test_popup_probe_ignores_selector_and_parent_modal_but_not_popup():
    from DearUIQt.runtime import QGuiRuntime
    backend = SimpleNamespace(
        get_windows=lambda: (11, 12, 13),
        get_item_configuration=lambda tag: {
            11: {"modal": True}, 12: {"modal": True}, 13: {"popup": True}}[tag],
        is_item_shown=lambda tag: True,
    )
    probe = QGuiRuntime(backend)
    assert probe.hasActivePopupSurface(exclude=12, include_modals=False)
    backend.get_windows = lambda: (11, 12)
    assert not probe.hasActivePopupSurface(exclude=12, include_modals=False)
    assert probe.hasActivePopupSurface(exclude=12)


def test_changing_row_selection_only_updates_two_rows():
    from DearUIQt.modelview.models import QtItemViewState
    view = object.__new__(FolderListView)
    state = QtItemViewState(multiple=False)
    state.replace(range(1000))
    state.selected = {501}
    state.current = 501
    view._state = state
    view.items = {key: key + 100 for key in range(1000)}
    view._values = [SimpleNamespace(key=key, enabled=True) for key in range(1000)]
    view._row_enabled = {key: True for key in range(1000)}
    view._row_index = {key: key for key in range(1000)}
    view.detail_texts = {key: (3 * key, 3 * key + 1, 3 * key + 2) for key in range(1000)}
    view.backend = Mock()
    view.table = 777
    view._has_focus = False
    view._visual_focus_active = False
    view._visual_selected_keys = {500}
    view._full_visual_sync = False
    view._qt_selection_themes = {False: ("selected", "selected_text")}
    with patch("WinUx.dialogs.local_folder_form.qt_item_row_theme", return_value="row"), \
         patch("WinUx.dialogs.local_folder_form.qt_item_text_theme", return_value="text"), \
         patch("WinUx.dialogs.local_folder_form.QtListView._sync_selection_visuals") as full:
        view._sync_selection_visuals()
    full.assert_not_called()
    assert view.backend.highlight_table_row.call_count == 1
    assert view.backend.unhighlight_table_row.call_count == 1
    assert view.backend.bind_item_theme.call_count <= 10
    assert view._visual_selected_keys == {501}


def test_full_row_hit_on_large_folder_uses_logarithmic_geometry_reads():
    from DearUIQt.core.object import QRect
    view = object.__new__(FolderListView)
    view._deleted = False
    view.items = {i: i + 100 for i in range(10000)}
    view.isVisible = lambda: True
    view.globalGeometry = Mock(return_value=QRect(0, 0, 600, 260000))
    view.itemGeometry = Mock(side_effect=lambda key, **kwargs:
                              QRect(80, 40 + key * 24, 160, 24))
    view.nativeItem = lambda key: key + 100
    view._clicked = Mock()
    with patch("WinUx.dialogs.local_folder_form.METRICS",
               SimpleNamespace(row_height=24)):
        assert view._row_pointer_clicked(point=(450, 40 + 8000 * 24 + 12))
    view._clicked.assert_called_once_with(8100, True, 8000)
    assert view.itemGeometry.call_count <= 15
