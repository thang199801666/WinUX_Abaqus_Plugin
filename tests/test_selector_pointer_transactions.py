"""Selector navigation cannot delete ImGui's still-active pointer target."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import WinUx.dialogs.local_folder_form as module


@pytest.fixture
def browser():
    """Drive LocalFolderDialog pointer-transactions with a fake QApplication.

    Note: pytestlite leaks builtin-fixture arguments (monkeypatch) into tests
    when the fixture itself depends on them, so attribute patching and restore
    happen here with try/finally.
    """
    state = SimpleNamespace(frame=10, down=True)
    old_application, old_cursor = module.QApplication, module.QCursor
    module.QApplication = SimpleNamespace(
        instance=lambda: SimpleNamespace(frameCount=lambda: state.frame))
    module.QCursor = SimpleNamespace(
        buttons=lambda: (module.Qt.LeftButton if state.down else module.Qt.NoButton))
    try:
        dialog = object.__new__(module.LocalFolderDialog)
        dialog._generation = 1
        dialog._pending_place_path = dialog._place_transaction = None
        dialog._place_navigation_scheduled = False
        dialog._pending_row_activation = None
        dialog._row_activation_scheduled = False
        dialog.winfo_exists = Mock(return_value=True)
        dialog.view = SimpleNamespace(after=Mock())
        dialog.listbox = SimpleNamespace(items={"entry": 100}, _row_generation=2, current="entry")
        dialog._navigate = Mock()
        dialog._enter_key = Mock()
        yield dialog, state
    finally:
        module.QApplication, module.QCursor = old_application, old_cursor


@pytest.mark.parametrize("surface", ["sidebar", "row"])
def test_navigation_waits_for_physical_release_and_a_render_after_release(browser, surface):
    dialog, state = browser
    if surface == "sidebar":
        dialog._place_clicked(None, None, "entry")
        commit, action = dialog._commit_place_navigation, dialog._navigate
    else:
        dialog._queue_row_activation("entry")
        commit, action = dialog._commit_row_activation, dialog._enter_key
    for _ in range(3):
        commit()
        state.frame += 1
        action.assert_not_called()
    state.down = False
    commit()
    commit()  # same scheduler drain is not a rendered frame
    action.assert_not_called()
    state.frame += 1
    commit()
    action.assert_called_once_with("entry")
    commit()
    action.assert_called_once()


@pytest.mark.parametrize("surface", ["sidebar", "row"])
def test_pending_navigation_is_dropped_after_close_or_another_directory(browser, surface):
    dialog, state = browser
    if surface == "sidebar":
        dialog._place_clicked(None, None, "entry")
        commit, action = dialog._commit_place_navigation, dialog._navigate
    else:
        dialog._queue_row_activation("entry")
        commit, action = dialog._commit_row_activation, dialog._enter_key
    dialog._generation += 1
    commit()
    state.down = False
    state.frame += 10
    commit()
    action.assert_not_called()


def test_row_rebuild_cancels_pending_double_click_even_if_same_key_is_present(browser):
    dialog, state = browser
    dialog._queue_row_activation("entry")
    dialog.listbox._row_generation += 1
    dialog._commit_row_activation()
    assert dialog._pending_row_activation is None
    dialog._enter_key.assert_not_called()


def test_closing_selector_stops_held_pointer_retry(browser):
    dialog, state = browser
    dialog._queue_row_activation("entry")
    dialog.winfo_exists.return_value = False
    dialog.view.after.reset_mock()
    dialog._commit_row_activation()
    assert not dialog._row_activation_scheduled
    dialog.view.after.assert_not_called()


def test_selecting_another_row_cancels_pending_navigation(browser):
    dialog, state = browser
    dialog._queue_row_activation("entry")
    dialog.listbox.current = "other"
    dialog._commit_row_activation()
    assert dialog._pending_row_activation is None
    dialog._enter_key.assert_not_called()


def test_duplicate_cell_callbacks_do_not_count_as_two_clicks(monkeypatch):
    state = SimpleNamespace(frame=10)
    monkeypatch.setattr(module, "QApplication", SimpleNamespace(
        instance=lambda: SimpleNamespace(frameCount=lambda: state.frame)))
    dispatch = Mock()
    monkeypatch.setattr(module.QtListView, "_clicked", dispatch)
    view = object.__new__(module.FolderListView)
    view._deleted = False
    view.items = {"entry": 100}
    view._values = [SimpleNamespace(key="entry", enabled=True)]
    view._last_click_frame = view._last_click_key = None
    view._last_click_at = 0
    view._double_click_interval = .5
    view._last_click_at = 0.0
    view.doubleClicked = Mock()
    view.activated = Mock()
    view._clicked(100, True, "entry")
    view._clicked(100, True, "entry")  # duplicate visual-cell + selectable notification
    dispatch.assert_called_once()
    view.doubleClicked.emit.assert_not_called()
    state.frame += 1
    view._clicked(100, True, "entry")  # genuine second click on the same row
    view.doubleClicked.emit.assert_called_once_with("entry")
    view.activated.emit.assert_called_once_with("entry")
    dispatch.reset_mock()
    view._clicked(99, True, "entry")  # old row sender, same path
    dispatch.assert_not_called()
