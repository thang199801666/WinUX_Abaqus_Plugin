"""Native input activation must accompany floating-window publication."""
import os
from unittest.mock import MagicMock, patch

import pytest

from WinUx.platform.floating_viewport import NativeViewport


@pytest.mark.skipif(os.name != "nt", reason="Windows native activation")
@pytest.mark.parametrize("foreground", [0, 123, 456])
def test_activation_sets_thread_input_focus_without_stealing_from_other_apps(foreground):
    user32 = MagicMock()
    user32.IsIconic.return_value = False
    user32.GetForegroundWindow.return_value = foreground
    viewport = NativeViewport(123, True)
    with patch("WinUx.platform.floating_viewport.ctypes.windll.user32", user32):
        viewport.activate()
    user32.SetForegroundWindow.assert_called_once_with(123)
    if foreground in (0, 123):
        user32.SetActiveWindow.assert_called_once_with(123)
        user32.SetFocus.assert_called_once_with(123)
    else:
        user32.SetActiveWindow.assert_not_called()
        user32.SetFocus.assert_not_called()
