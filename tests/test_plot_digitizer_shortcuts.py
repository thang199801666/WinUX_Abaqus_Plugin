"""Project-specific command scope; no generic/global shortcut framework."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from WinUx.plotdigitizer.ui import dialog as module


@pytest.fixture
def editor(monkeypatch):
    keys = ("Z", "Y", "Delete", "A", "S", "D", "N", "P", "Left", "Right", "Up", "Down",
            "LControl", "RControl", "LShift", "RShift", "LAlt", "RAlt", "LWin", "RWin")
    backend = SimpleNamespace(**{"mvKey_" + name: index for index, name in enumerate(keys, 1)})
    backend.is_item_shown = Mock(return_value=True)
    backend.get_focused_item = Mock(return_value=0)
    backend.get_item_info = Mock(return_value={"type": "mvAppItemType::mvDrawlist"})
    backend.get_item_parent = Mock(return_value=0)
    down = set()
    backend.is_key_down = lambda key: key in down
    monkeypatch.setattr(module, "dpg", backend)
    import DearUIQt.input_gate as gate
    monkeypatch.setattr(gate, "native_modal_input_active", lambda: False)
    dialog = object.__new__(module.PlotDigitizerDialog)
    dialog.tag = 1
    dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 0)
    dialog.winfo_exists = Mock(return_value=True)
    dialog._file_dialog = None
    dialog.dataset_menu = None
    dialog._active_tool = "axes"
    dialog._selected_point = None
    dialog._mouse_in_canvas = Mock(return_value=False)
    dialog.result_grid = SimpleNamespace(hasFocus=lambda: False)
    dialog._trigger_history_command = Mock()
    dialog._delete_points = Mock()
    return dialog, backend, down


@pytest.mark.parametrize("key,shift,command", [("Z", False, "undo"), ("Y", False, "redo"), ("Z", True, "redo")])
def test_history_accelerators_dispatch_one_shared_command(editor, key, shift, command):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    if shift:
        down.add(backend.mvKey_LShift)
    dialog._edit_key(None, getattr(backend, "mvKey_" + key))
    dialog._trigger_history_command.assert_called_once_with(command)


@pytest.mark.parametrize("item_type", ["mvInputText", "mvInputInt", "mvCombo", "mvSliderFloat", "mvDragInt", "mvColorEdit"])
def test_text_and_value_editors_keep_their_own_keys(editor, item_type):
    dialog, backend, down = editor
    backend.get_focused_item.return_value = 10
    backend.get_item_info.return_value = {"type": "mvAppItemType::" + item_type}
    down.add(backend.mvKey_LControl)
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()


def test_opening_file_selector_and_dataset_menu_block_document_shortcuts(editor):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    dialog._file_dialog = SimpleNamespace(dialog=SimpleNamespace(winfo_exists=lambda: True))
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._file_dialog = None
    dialog.dataset_menu = SimpleNamespace(_deleted=False, tag=20)
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()


def test_native_modal_and_other_foreground_do_not_edit_document(editor, monkeypatch):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    import DearUIQt.input_gate as gate
    monkeypatch.setattr(gate, "native_modal_input_active", lambda: True)
    dialog._edit_key(None, backend.mvKey_Z)
    monkeypatch.setattr(gate, "native_modal_input_active", lambda: False)
    import WinUx.ui.native.dialog_focus as focus
    dialog.view._find_main_viewport_hwnd = lambda: 200
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 999)
    monkeypatch.setattr(focus, "window_state", lambda hwnd: (True, True, True))
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()


def test_alt_modified_keys_and_ctrl_delete_do_not_edit_canvas(editor):
    dialog, backend, down = editor
    down.update((backend.mvKey_LControl, backend.mvKey_LAlt))
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()
    down.remove(backend.mvKey_LAlt)
    dialog._mouse_in_canvas.return_value = True
    dialog._edit_key(None, backend.mvKey_Delete)
    dialog._delete_points.assert_not_called()


def test_hidden_or_closed_dialog_rejects_shortcuts(editor):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    backend.is_item_shown.return_value = False
    dialog._edit_key(None, backend.mvKey_Z)
    backend.is_item_shown.return_value = True
    dialog.winfo_exists.return_value = False
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()


def test_foreign_widget_focus_and_stale_focus_ids_do_not_route_history(editor):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    backend.get_focused_item.return_value = 10
    dialog._edit_key(None, backend.mvKey_Z)
    backend.get_item_info.side_effect = RuntimeError("deleted item")
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_not_called()


def test_canvas_descendant_focus_routes_history_to_its_document(editor):
    dialog, backend, down = editor
    down.add(backend.mvKey_LControl)
    backend.get_focused_item.return_value = 10
    backend.get_item_parent.side_effect = lambda item: {10: 5, 5: dialog.tag}[item]
    dialog._edit_key(None, backend.mvKey_Z)
    dialog._trigger_history_command.assert_called_once_with("undo")
