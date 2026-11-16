"""Discoverable color picking, balanced Extract Data layout and actual sampling."""
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
from DearUIQt.core import QPoint
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='pick-color-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'pick-color-logs')}):
        view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        try:
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()

            def pump(count=16):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            def rect(tag):
                return QRetainedItem(tag).globalGeometry()

            def button_colors():
                button = dialog.control_wrapper(dialog.pick_color_button)
                backend = button.backend
                theme = backend.get_item_theme(button.tag)
                colors = {}
                for component in backend.get_item_children(theme, 1):
                    for item in backend.get_item_children(component, 1):
                        if backend.get_item_type(item).endswith('mvThemeColor'):
                            colors[backend.get_item_configuration(item)['target']] = tuple(
                                round(v) for v in backend.get_value(item))
                return backend, theme, colors

            dialog._show_tool('extract')
            pump(30)
            for tag in (dialog.pick_color_button, dialog.extract_button):
                assert not dialog.control_wrapper(tag).isEnabled()
            assert 'Pick Color' in dialog.control_wrapper(dialog.pick_color_button).text()
            for size in ((1100, 720), (1240, 800), (1380, 880)):
                dialog.resize(*size)
                pump()
                label, extract = [rect(tag) for tag in (dialog.pick_color_button, dialog.extract_button)]
                assert label.height() == extract.height() == 28
                assert 6 <= extract.y() - label.bottom() <= 24
                assert abs(extract.x() - label.x()) <= 2
                assert abs(extract.width() - label.width()) <= 2
                assert not hasattr(dialog, 'pick_curve_button')
                assert not hasattr(dialog, 'delete_point_button')
                assert not hasattr(dialog, '_auto_pick_hint')

            image = Image.new('RGB', (100, 80), 'white')
            image.putpixel((20, 30), (20, 80, 130))
            dialog.engine.apply_image(image, 'colors.png')
            pump()
            assert dialog.control_wrapper(dialog.pick_color_button).isEnabled()
            dialog.ribbon._button_clicked('edit')
            assert dialog._edit_enabled
            assert dialog.control_wrapper(dialog.pick_color_button).click()
            assert dialog._pick_mode == 'curve' and not dialog._edit_enabled
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=(20, 30)), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(10, 10)):
                dialog._mouse_left()
            pump()
            assert dialog.engine.active_dataset.curve_rgb == (20, 80, 130)
            assert dialog._pick_color_rgb == (20, 80, 130)
            assert dialog._pick_mode is None
            assert not dialog.engine.active_dataset.manual_points
            assert '#145082' in dialog.control_value(dialog._pick_color_button_help)
            backend, theme, colors = button_colors()
            assert colors[backend.mvThemeCol_Button] == (20, 80, 130, 255)
            assert colors[backend.mvThemeCol_Text] == (255, 255, 255, 255)
            dialog._refresh_all()
            pump()
            assert button_colors()[1] == theme, 'Unchanged color recreated its theme'
            dialog.engine.set_curve_color((255, 240, 0))
            pump()
            backend, yellow_theme, colors = button_colors()
            assert colors[backend.mvThemeCol_Button] == (255, 240, 0, 255)
            assert colors[backend.mvThemeCol_Text] == (0, 0, 0, 255)
            assert not backend.does_item_exist(theme), 'Replaced color theme leaked'
            dialog.engine.add_dataset()
            pump()
            assert dialog._pick_color_rgb is None
            assert not backend.does_item_exist(yellow_theme)
            dialog.engine.set_active_dataset(0)
            pump()
            assert button_colors()[2][backend.mvThemeCol_Button] == (255, 240, 0, 255)
            assert dialog.control_wrapper(dialog.pick_color_button).click()
            assert dialog._pick_mode == 'curve'
            dialog._cancel_pick()
            with patch.object(dialog, '_start_extraction') as extract:
                dialog.control_wrapper(dialog.extract_button).click()
                extract.assert_called_once_with(auto_detect=False)
            dialog.engine.update_dataset(locked=True)
            pump()
            for tag in (dialog.pick_color_button, dialog.extract_button):
                assert not dialog.control_wrapper(tag).isEnabled()
            assert button_colors()[2][backend.mvThemeCol_Button] != (255, 240, 0, 255)
            dialog.engine.update_dataset(locked=False)
            pump()
            assert button_colors()[2][backend.mvThemeCol_Button] == (255, 240, 0, 255)
            print('PASS: only Pick Color / Extract Points, aligned/full-width actions '
                  'at three sizes, real pixel sampling, extraction routing and lock guards', flush=True)
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
