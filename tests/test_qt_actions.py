import threading
from unittest.mock import Mock

import pytest

from WinUx.ui import QAction, QObject, QSignalBlocker, QPushButton, QMenu
from test_qt_control_interactions import backend_fixture


def menu_fixture(actions):
    # Exercise the real command model/dispatch without testing pixel rendering.
    menu = object.__new__(QMenu)
    QObject.__init__(menu)
    menu._action_inputs = []
    menu._action_connections = []
    menu._parent_menu = None
    menu._context = "context"
    menu._active_action = None
    from WinUx.ui import Signal
    menu.triggered = Signal(menu)
    menu.hide = Mock()
    menu._set_active_action = Mock()
    menu._redraw_check = Mock()
    menu._items = {}

    def rebuild():
        menu._row_specs = {str(spec["id"]): spec for spec in menu._actions}
        return menu

    menu._rebuild_action_rows = rebuild
    menu.setActions(actions)
    return menu


def test_action_checkable_trigger_orders_toggle_before_command_and_guards_disabled():
    action = QAction("Pin", checkable=True)
    events = []
    action.toggled.connect(lambda value: events.append(("toggled", value)))
    action.triggered.connect(lambda value: events.append(("triggered", value)))
    assert action.trigger()
    assert events == [("toggled", True), ("triggered", True)]
    action.setDisabled(True)
    assert not action.trigger()
    assert action.isChecked()
    action.setEnabled(True)
    action.setChecked(False)
    assert events[-1] == ("toggled", False)
    assert len([event for event in events if event[0] == "triggered"]) == 1


def test_action_blocker_suppresses_notifications_without_discarding_state():
    action = QAction("Initial", checkable=True)
    changed, triggered = Mock(), Mock()
    action.changed.connect(changed)
    action.triggered.connect(triggered)
    with QSignalBlocker(action):
        action.setText("Final")
        action.trigger()
    assert action.text() == "Final" and action.isChecked()
    changed.assert_not_called()
    triggered.assert_not_called()


def test_shared_action_keeps_two_buttons_and_menu_synchronized_without_double_toggle():
    action = QAction("Pin", checkable=True)
    first = QPushButton(backend=backend_fixture())
    second = QPushButton(backend=backend_fixture())
    first.setDefaultAction(action)
    second.setDefaultAction(action)
    menu = menu_fixture([action])
    toggled, triggered, menu_triggered = Mock(), Mock(), Mock()
    first.toggled.connect(toggled)
    action.triggered.connect(triggered)
    menu.triggered.connect(menu_triggered)
    first.click()
    assert first.isChecked() and second.isChecked() and action.isChecked()
    assert menu._row_specs[action._action_key]["checked"]
    toggled.assert_called_once_with(True)
    triggered.assert_called_once_with(True)
    menu._row_clicked(user_data=action._action_key)
    assert not first.isChecked() and not second.isChecked() and not action.isChecked()
    assert triggered.call_count == 2
    menu_triggered.assert_called_once_with(action, "context")
    action.setText("Keep on top")
    assert first.text() == second.text() == "Keep on top"
    assert menu._row_specs[action._action_key]["label"] == "Keep on top"
    action.setEnabled(False)
    assert not first.isEnabled() and not second.isEnabled()
    assert not menu._row_specs[action._action_key]["enabled"]


def test_rebinding_and_action_deletion_disconnect_views_without_changing_ownership():
    owner = QObject()
    first, second = QAction("First", owner), QAction("Second", owner)
    button = QPushButton(backend=backend_fixture())
    button.setDefaultAction(first)
    button.setDefaultAction(second)
    first.setText("Unrelated")
    assert button.text() == "Second"
    menu = menu_fixture([second])
    second.delete()
    assert button.defaultAction() is None and not button.isEnabled()
    assert menu.actions() == [] and menu._action_inputs == []
    assert owner.children() == [first]


def test_deleted_button_does_not_keep_action_connections_alive():
    action = QAction("Command")
    button = QPushButton(backend=backend_fixture())
    button.setDefaultAction(action)
    assert len(action.changed._slots) == 1
    button.delete()
    assert not action.changed._slots and not action.destroyed._slots
    assert not action._deleted
    assert button.defaultAction() is None and not button._action_connections


def test_real_dpg_menu_rows_follow_action_and_release_bindings_on_delete():
    import dearpygui.dearpygui as dpg
    dpg.create_context()
    try:
        action = QAction("Shared", checkable=True)
        menu = QMenu([action], backend=dpg)
        events = []
        action.triggered.connect(events.append)
        menu._row_clicked(user_data=action._action_key)
        assert action.isChecked() and events == [True]
        action.setText("Renamed")
        assert menu._row_specs[action._action_key]["label"] == "Renamed"
        action.setVisible(False)
        assert action._action_key not in menu._rows
        action.setVisible(True)
        assert action._action_key in menu._rows
        menu.delete()
        assert not action.changed._slots and not action.destroyed._slots
        assert not menu._action_inputs and not menu._action_connections
    finally:
        dpg.destroy_context()


def test_action_refuses_worker_mutation_and_deleted_owner():
    action = QAction("Command")
    errors = []

    def mutate():
        try:
            action.setText("Worker")
        except RuntimeError:
            errors.append(True)

    worker = threading.Thread(target=mutate)
    worker.start()
    worker.join()
    assert errors == [True] and action.text() == "Command"
    action.delete()
    assert not action.trigger()
    with pytest.raises(RuntimeError):
        action.setText("Deleted")


def test_menu_keeps_legacy_ids_and_context_dispatch_unchanged():
    menu = menu_fixture([{"id": "legacy", "action": "legacy", "label": "Legacy", "checkable": True}])
    triggered = Mock()
    menu.triggered.connect(triggered)
    menu._row_clicked(user_data="legacy")
    triggered.assert_called_once_with("legacy", "context")


def test_menu_add_remove_and_visible_state_follow_shared_action():
    menu = menu_fixture([])
    action = menu.addAction("New")
    assert action.parent is menu and menu.actions() == [action]
    action.setVisible(False)
    assert menu._visible_action_ids() == []
    menu.removeAction(action)
    assert menu.actions() == [] and not action._deleted
    action.setText("Detached")
    assert not menu._actions


def test_live_action_refresh_preserves_legacy_row_mutations():
    action = QAction("Live")
    menu = menu_fixture([{"id": "legacy", "action": "legacy", "label": "Legacy",
                         "checkable": True}, action])
    menu._row_clicked(user_data="legacy")
    assert menu._row_specs["legacy"]["checked"]
    action.setText("Updated")
    assert menu._row_specs["legacy"]["checked"]
    menu.addAction("Additional")
    assert menu._row_specs["legacy"]["checked"]
    action.delete()
    assert menu._row_specs["legacy"]["checked"]


def test_cross_thread_action_is_rejected_before_menu_allocates_native_items():
    actions = []
    worker = threading.Thread(target=lambda: actions.append(QAction("Worker")))
    worker.start()
    worker.join()
    backend = Mock()
    with pytest.raises(RuntimeError):
        QMenu(actions, backend=backend)
    backend.generate_uuid.assert_not_called()
    backend.window.assert_not_called()


def test_nested_action_updates_and_deletion_preserve_other_entries():
    action = QAction("Nested")
    menu = menu_fixture([{"id": "submenu", "label": "More", "children": [action]},
                         {"id": "legacy", "label": "Legacy"}])
    action.setText("Updated")
    assert menu._actions[0]["children"][0]["label"] == "Updated"
    action.delete()
    assert menu._actions[0]["children"] == []
    assert menu._actions[1]["label"] == "Legacy"
