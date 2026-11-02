"""Shared spin-box rendering and stepping regression (no physical input)."""
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
from DearUIQt.backends import dpg
from DearUIQt.gui.style import METRICS
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        try:
            view._gui_runtime.show()
            dialog = SettingsDialog(view)
            dialog._ensure_page('general', defer_io=False)
            dialog._show_page('general')
            dialog.show()
            for _ in range(24):
                view.update()
                time.sleep(.005)
            for tag in dialog.inp_fields.values():
                spin = dialog._control_wrappers[tag]
                assert dpg.get_item_configuration(spin.container)['height'] == METRICS.control_height
                for arrow in (spin.up_button, spin.down_button):
                    assert dpg.get_item_configuration(arrow)['width'] == 14
                    children = dpg.get_item_children(arrow, 2)
                    types = [dpg.get_item_info(item)['type'] for item in children]
                    assert sum('DrawTriangle' in kind for kind in types) == 1
                    assert sum('DrawRect' in kind for kind in types) == 1
                    assert sum('DrawLine' in kind for kind in types) == (1 if arrow == spin.up_button else 2)
                for _arrow, background, _triangle in spin._arrow_surfaces:
                    assert dpg.get_item_configuration(background)['rounding'] == 2
            spin = dialog._control_wrappers[dialog.inp_fields['minimum_cores']]
            before = spin.value()
            spin.stepBy(1)
            assert spin.value() == before + 1
            spin.stepBy(-1)
            assert spin.value() == before
            arrow, background, triangle = spin._arrow_surfaces[0]
            with patch.object(spin.backend, 'get_item_state', return_value={'hovered': True}), \
                    patch.object(spin.backend, 'is_mouse_button_down', return_value=False):
                spin._refresh_arrow_feedback(arrow)
                assert spin._arrow_visual_states[arrow] == (True, True, False)
                fill = dpg.get_item_configuration(background)['fill']
                assert tuple(round(value * 255) for value in fill) == (229, 241, 251, 255)
            with patch.object(spin.backend, 'get_item_state', return_value={'hovered': True}), \
                    patch.object(spin.backend, 'is_mouse_button_down', return_value=True):
                spin._refresh_arrow_feedback(arrow)
                assert spin._arrow_visual_states[arrow] == (True, True, True)
                fill = dpg.get_item_configuration(background)['fill']
                assert tuple(round(value * 255) for value in fill) == (204, 228, 247, 255)
            spin.setEnabled(False)
            spin.stepBy(1)
            assert spin.value() == before
            assert spin._arrow_visual_states[arrow] == (False, False, False)
            decimal_tag = dialog.spin_float(1.25, parent=dialog.content,
                                             minimum=0, maximum=10, step=.25, decimals=2)
            decimal = dialog._control_wrappers[decimal_tag]
            assert dpg.get_item_configuration(decimal.up_button)['width'] == 14
            assert dpg.get_item_configuration(decimal_tag)['format'] == '%.2f'
            decimal.stepBy(1)
            assert decimal.value() == 1.5
            decimal.stepBy(-1)
            assert decimal.value() == 1.25
            print('PASS: Qt-style narrow spin strip, filled triangles, integrated dividers, shared height, stepping and disabled guards')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
