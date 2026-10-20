"""Transfer Center centers on WinUx when first shown, never while already active."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.dialogs.transfer_center_form import TransferCenterDialog


def _dialog(*, native=None):
    return SimpleNamespace(
        view=SimpleNamespace(primary_window_tag="winux_primary",
                             _find_main_viewport_hwnd=lambda: 123),
        tag="transfer", width=820, height=300,
        _native_window_backend=native,
    )


def test_inprocess_transfer_center_uses_main_window_bounds_not_desktop():
    dialog = _dialog()
    with patch("WinUx.dialogs.transfer_center_form.dpg", new=Mock()) as dpg:
        dpg.does_item_exist.return_value = True
        dpg.get_item_rect_min.return_value = (100, 70)
        dpg.get_item_rect_size.return_value = (1200, 800)
        dpg.get_viewport_client_width.return_value = 1600
        dpg.get_viewport_client_height.return_value = 1000
        assert TransferCenterDialog._center_over_winux(dialog)
        dpg.set_item_pos.assert_called_once_with("transfer", (290, 320))


def test_native_transfer_center_centers_over_winux_hwnd_even_when_modeless():
    native = Mock()
    native.centerBeforeShow.return_value = (300, 200)
    dialog = _dialog(native=native)
    with patch("WinUx.dialogs.transfer_center_form.dpg", new=Mock()) as dpg:
        assert TransferCenterDialog._center_over_winux(dialog)
        native.centerBeforeShow.assert_called_once_with(
            "transfer", width=820, height=300, owner_hwnd=123)
        native.centerOverOwner.assert_not_called()
        dpg.set_item_pos.assert_not_called()


def test_first_row_final_height_recenters_once_but_progress_does_not():
    dialog = SimpleNamespace(
        _window_balance_scheduled=True, _last_auto_height=240,
        _center_on_first_row=True, row_widgets={"first": object()},
        tasks=[object()], width=820, height=240,
        _target_window_height=lambda: 260,
        winfo_exists=lambda: True, isVisible=lambda: True,
        resize=Mock(), _center_over_winux=Mock(),
    )
    TransferCenterDialog._flush_window_balance(dialog)
    assert dialog.height == 260
    dialog.resize.assert_called_once_with(820, 260)
    dialog._center_over_winux.assert_called_once_with(presented=True)
    assert not dialog._center_on_first_row
    TransferCenterDialog._flush_window_balance(dialog)
    dialog._center_over_winux.assert_called_once()


def test_transfer_center_show_centers_only_on_hidden_to_visible_edge():
    dialog = object.__new__(TransferCenterDialog)
    dialog._visible_state = False
    dialog.width, dialog.height = 820, 320
    dialog.resize = Mock()
    dialog._target_window_height = Mock(return_value=260)
    dialog._center_over_winux = Mock()
    dialog._schedule_window_balance = Mock()
    with patch.object(QtDialog, "show", return_value=True):
        assert dialog.show()
        assert dialog._center_on_first_row
        dialog.resize.assert_called_once_with(820, 260)
        dialog._center_over_winux.assert_called_once_with()
        # Repeated add_task()/progress update while the dialog is visible must
        # not recenter a window moved manually by its user.
        dialog._visible_state = True
        assert dialog.show()
        dialog._center_over_winux.assert_called_once()
        assert dialog._schedule_window_balance.call_count == 2


def test_reopen_after_hide_centers_over_new_main_window_location():
    dialog = object.__new__(TransferCenterDialog)
    dialog._visible_state = True
    dialog.width, dialog.height = 820, 260
    dialog.resize = Mock()
    dialog._target_window_height = Mock(return_value=260)
    dialog._center_over_winux = Mock()
    dialog._schedule_window_balance = Mock()
    with patch.object(QtDialog, "show", return_value=True):
        dialog.show()
        dialog._center_over_winux.assert_not_called()
        dialog._visible_state = False
        dialog.show()
        dialog._center_over_winux.assert_called_once_with()
