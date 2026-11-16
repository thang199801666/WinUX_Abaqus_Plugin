"""Digitizer button hover presentation: abaqus python tests/test_digitizer_button_hover.py."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.backends import dpg
from DearUIQt.gui.palette import QtFusionPalette as P
from DearUIQt.themes import button_theme
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def colors(theme, enabled=True):
    for component in dpg.get_item_children(theme, 1):
        config = dpg.get_item_configuration(component)
        if config['item_type'] == dpg.mvButton and config['enabled_state'] == enabled:
            return {dpg.get_item_configuration(item)['target']: tuple(dpg.get_value(item))
                    for item in dpg.get_item_children(component, 1)
                    if dpg.get_item_type(item).endswith('mvThemeColor')}
    raise AssertionError('Missing button theme state')


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-digitizer-hover-', dir=root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)

            def pump(frames=14):
                for _ in range(frames):
                    view.update()
                    time.sleep(.01)

            try:
                dialog.show()
                pump()
                for role in ('secondary', 'primary', 'danger', 'flat'):
                    normal = colors(button_theme(role=role))
                    face, hover = (normal[key] for key in (dpg.mvThemeCol_Button, dpg.mvThemeCol_ButtonHovered))
                    assert max(abs(a - b) for a, b in zip(face[:3], hover[:3])) >= 10
                    assert normal[dpg.mvThemeCol_ButtonActive] != hover
                    disabled = colors(button_theme(role=role, disabled=True), enabled=False)
                    assert disabled[dpg.mvThemeCol_Button] == disabled[dpg.mvThemeCol_ButtonHovered]
                button = dialog.apply_calibration_button
                wrapper = dialog.control_wrapper(button)
                overlay = dialog._icon_action_canvases[button]
                wrapper.setEnabled(True)
                with patch.object(wrapper, 'underMouse', return_value=False), \
                     patch.object(overlay, 'underMouse', return_value=True):
                    dialog._sync_icon_action_hover(button)
                    hovered = colors(dpg.get_item_theme(button))
                    assert hovered[dpg.mvThemeCol_Button] == P.BUTTON_HOVER
                    assert dialog._icon_action_hovered[button]
                    wrapper.setEnabled(False)
                    dialog._sync_icon_action_hover(button)
                    disabled = colors(dpg.get_item_theme(button), enabled=False)
                    assert disabled[dpg.mvThemeCol_Button] == disabled[dpg.mvThemeCol_ButtonHovered]
                    assert not dialog._icon_action_hovered[button]
                wrapper.setEnabled(True)
                with patch.object(wrapper, 'underMouse', return_value=False), \
                     patch.object(overlay, 'underMouse', return_value=False):
                    dialog._sync_icon_action_hover(button)
                    normal = colors(dpg.get_item_theme(button))
                    assert normal[dpg.mvThemeCol_Button] != P.BUTTON_HOVER
                dialog.engine.apply_image(Image.new('RGB', (120, 90), 'white'), 'hover.png')
                dialog.engine.set_curve_color((20, 80, 130))
                dialog._show_tool('extract')
                pump()
                for rgb in ((0, 0, 0), (255, 255, 255), (20, 80, 130)):
                    dialog._sync_pick_color(rgb)
                    theme = dpg.get_item_theme(dialog.pick_curve_button)
                    normal = colors(theme)
                    disabled = colors(theme, enabled=False)
                    assert normal[dpg.mvThemeCol_Button] == (*rgb, 255)
                    assert normal[dpg.mvThemeCol_ButtonHovered] != (*rgb, 255)
                    assert disabled[dpg.mvThemeCol_Button] == disabled[dpg.mvThemeCol_ButtonHovered]
                print('PASS: clear normal/hover/pressed colors, icon-overlay hover forwarding/reset, '
                      'disabled-state suppression and light/dark color swatch feedback')
            finally:
                dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
