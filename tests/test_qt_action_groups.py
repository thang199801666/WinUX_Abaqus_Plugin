from unittest.mock import Mock

import pytest

from WinUx.ui import QAction, QActionGroup, QObject, QPushButton
from test_qt_actions import menu_fixture
from test_qt_control_interactions import backend_fixture


def members():
    group = QActionGroup()
    first, second = QAction("Select", checkable=True), QAction("Pan", checkable=True)
    group.addAction(first)
    group.addAction(second)
    return group, first, second


def test_exclusive_group_commits_selection_before_any_observer_runs():
    group, first, second = members()
    first.setChecked(True)
    snapshots = []
    for action in (first, second):
        action.changed.connect(lambda: snapshots.append((first.isChecked(), second.isChecked())))
    second.setChecked(True)
    assert group.checkedAction() is second
    assert snapshots and all(snapshot == (False, True) for snapshot in snapshots)


def test_triggering_current_exclusive_member_does_not_uncheck_it():
    group, first, second = members()
    events, toggled = [], []
    group.triggered.connect(events.append)
    first.toggled.connect(toggled.append)
    first.trigger()
    first.trigger()
    assert first.isChecked() and group.checkedAction() is first
    assert events == [first, first] and toggled == [True]
    first.setChecked(False)
    assert group.checkedAction() is None


def test_nonexclusive_mode_and_return_to_exclusive_are_deterministic():
    group, first, second = members()
    group.setExclusive(False)
    first.setChecked(True)
    second.setChecked(True)
    assert first.isChecked() and second.isChecked()
    group.setExclusive(True)
    assert group.checkedAction() is first and not second.isChecked()


def test_group_enabled_visible_preserve_individual_overrides():
    group, first, second = members()
    first.setEnabled(False)
    first.setVisible(False)
    group.setEnabled(False)
    group.setVisible(False)
    assert not second.trigger()
    group.setEnabled(True)
    group.setVisible(True)
    assert second.isEnabled() and second.isVisible()
    assert not first.isEnabled() and not first.isVisible()


def test_group_drives_shared_buttons_and_menu():
    group, first, second = members()
    buttons = [QPushButton(backend=backend_fixture()), QPushButton(backend=backend_fixture())]
    buttons[0].setDefaultAction(first)
    buttons[1].setDefaultAction(second)
    menu = menu_fixture([first, second])
    buttons[0].click()
    menu._row_clicked(user_data=second._action_key)
    assert not buttons[0].isChecked() and buttons[1].isChecked()
    assert not menu._row_specs[first._action_key]["checked"]
    assert menu._row_specs[second._action_key]["checked"]
    group.setEnabled(False)
    assert not any(button.isEnabled() for button in buttons)
    assert not any(spec["enabled"] for spec in menu._actions)


def test_transfer_removes_old_group_connections_and_retains_object_parent():
    owner = QObject()
    first_group, second_group = QActionGroup(), QActionGroup()
    action = QAction("Command", owner)
    first_group.addAction(action)
    old, new = Mock(), Mock()
    first_group.triggered.connect(old)
    second_group.triggered.connect(new)
    second_group.addAction(action)
    assert first_group.actions() == [] and action.parent is owner
    action.trigger()
    old.assert_not_called()
    new.assert_called_once_with(action)
    action.delete()
    assert second_group.actions() == [] and not second_group._bindings


def test_adding_checked_action_exclusively_selects_it():
    group, first, second = members()
    first.setChecked(True)
    third = QAction("Zoom", checkable=True, checked=True)
    group.addAction(third)
    assert group.checkedAction() is third
    assert not first.isChecked() and not second.isChecked()


def test_group_delete_detaches_external_actions_and_deletes_owned_actions():
    group, first, second = members()
    owned = group.addAction("Owned")
    group.setEnabled(False)
    button = QPushButton(backend=backend_fixture())
    button.setDefaultAction(first)
    assert not button.isEnabled()
    group.delete()
    assert owned._deleted
    assert not first._deleted and not second._deleted
    assert first.actionGroup() is None and button.isEnabled()
    assert not group._bindings
    with pytest.raises(RuntimeError):
        group.addAction(first)


def test_removal_and_set_action_group_none_do_not_delete_action():
    group, first, second = members()
    group.setEnabled(False)
    first.setActionGroup(None)
    assert first.isEnabled() and not first._deleted
    assert group.actions() == [second]
    assert first.actionGroup() is None
