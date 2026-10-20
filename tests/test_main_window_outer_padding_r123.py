from unittest.mock import MagicMock, call

from DearUIQt.gui import style
from WinUx.view import WinUXView


def test_application_shell_uses_two_pixel_outer_padding():
    backend = MagicMock()
    backend.does_item_exist.return_value = False
    style.application_theme(backend)
    assert call(backend.mvStyleVar_WindowPadding, 2, 2) in backend.add_theme_style.call_args_list


def test_winux_outer_padding_contract_is_two_pixels():
    assert WinUXView.APP_PADDING == 2
