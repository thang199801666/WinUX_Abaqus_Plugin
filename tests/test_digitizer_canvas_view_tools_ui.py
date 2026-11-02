"""Canvas-local zoom tools: floating geometry, routing and input isolation."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.widgets import QRetainedItem
from DearUIQt.core import Qt, QEvent, QMouseEvent, QPoint
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.application.workspace_state import normalize_workspace_state


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='canvas-view-tools-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        def pump(count=18):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()
            pump(30)
            with patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(-100, -100)), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.buttons', return_value=Qt.NoButton):
                dialog._update_canvas_view_tool_states()
                pump(3)
            assert set(dialog.ribbon._tabs) == {'home', 'data'}
            assert set(dialog._canvas_view_buttons) == {'fit', 'one_to_one', 'zoom_out', 'zoom_in'}
            toolbar = dialog._canvas_view_toolbar
            backend = toolbar.backend
            assert not backend.get_item_configuration(toolbar.tag)['border']
            assert dialog.CANVAS_VIEW_TOOLS_HEIGHT == 32
            def theme_colors(widget, enabled=True):
                colors = {}
                for component in backend.get_item_children(widget.theme(), 1):
                    if backend.get_item_configuration(component).get('enabled_state', True) != enabled:
                        continue
                    for item in backend.get_item_children(component, 1):
                        if 'mvThemeColor' in backend.get_item_info(item)['type']:
                            colors[backend.get_item_configuration(item)['target']] = backend.get_value(item)
                return colors
            assert theme_colors(toolbar)[backend.mvThemeCol_ChildBg][3] == 0
            for tag in dialog._canvas_view_buttons.values():
                assert theme_colors(dialog.control_wrapper(tag))[backend.mvThemeCol_Button][3] == 0
                config = backend.get_item_configuration(tag)
                assert tuple(config['uv_min']) == (.125, .125)
                assert tuple(config['uv_max']) == (.875, .875)
                assert config['width'] == config['height'] == 24
            assert all(not dialog.control_wrapper(tag).isEnabled()
                       for tag in dialog._canvas_view_buttons.values())
            bar = toolbar.globalGeometry()
            for tag in dialog._canvas_view_buttons.values():
                actual = QRetainedItem(tag).globalGeometry()
                assert actual.x() + actual.width() <= bar.x() + bar.width(), ('disabled button clipped', bar, actual)

            image = Image.new('RGB', (800, 500), 'white')
            dialog.engine.apply_image(image, 'canvas-view.png')
            dialog._load_texture(image)
            pump(25)
            assert all(dialog.control_wrapper(tag).isEnabled()
                       for tag in dialog._canvas_view_buttons.values())
            for tag in dialog._canvas_view_buttons.values():
                colors = theme_colors(dialog.control_wrapper(tag))
                assert colors[backend.mvThemeCol_Button][3] == 0
            before = dialog.engine._snapshot()
            history = len(dialog.engine._undo_stack)
            def click(key):
                dialog.control_wrapper(dialog._canvas_view_buttons[key]).click()
                pump(3)
            click('one_to_one')
            assert dialog._fit_scale == dialog._zoom == 1
            click('zoom_in')
            assert abs(dialog._zoom - 1.15) < 1e-8
            click('zoom_out')
            assert abs(dialog._zoom - 1) < 1e-8
            click('fit')
            assert dialog._auto_fit and dialog._zoom == 1
            assert before == dialog.engine._snapshot()
            assert history == len(dialog.engine._undo_stack)

            for key, tag in dialog._canvas_view_buttons.items():
                button = dialog.control_wrapper(tag)
                for state, point, buttons in (
                        ('hover', button.globalGeometry().center(), Qt.NoButton),
                        ('pressed', button.globalGeometry().center(), Qt.LeftButton),
                        ('idle', QPoint(-100, -100), Qt.NoButton)):
                    with patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=point), \
                            patch('WinUx.plotdigitizer.ui.dialog.QCursor.buttons', return_value=buttons):
                        dialog._update_canvas_view_tool_states()
                        assert dialog._canvas_view_tool_states[key] == state
                        assert button.theme() == dialog._canvas_view_themes[state]

            # Exercise the dialog's pointer bridge, not just click(). The host
            # Explorer has its own application-level target in this embedded test.
            last = dialog.control_wrapper(dialog._canvas_view_buttons['zoom_in'])
            point = last.globalGeometry().center()
            position = point.toTuple()
            zoom = dialog._zoom
            activations = []
            last.clicked.connect(lambda: activations.append(True))
            assert dialog._route_button_pointer(QMouseEvent(
                QEvent.MouseButtonPress, position, button=Qt.LeftButton, buttons=Qt.LeftButton))
            assert last._pointer_pressed
            assert dialog._route_button_pointer(QMouseEvent(
                QEvent.MouseButtonRelease, position, button=Qt.LeftButton))
            assert not last._pointer_pressed
            assert len(activations) == 1
            assert abs(dialog._zoom - zoom * 1.15) < 1e-8

            for width in (1000, 1100, 1380):
                dialog.resize(width, 800)
                pump(30)
                canvas = dialog._canvas_widget.globalGeometry()
                bar = dialog._canvas_view_toolbar.globalGeometry()
                assert bar.height() == 32
                assert canvas.x() <= bar.x() and bar.x() + bar.width() <= canvas.x() + canvas.width()
                assert 5 <= bar.y() - canvas.y() <= 10, (bar, canvas)
                assert abs(bar.x() + bar.width() / 2 - canvas.x() - canvas.width() / 2) <= 2
                rectangles = [QRetainedItem(tag).globalGeometry() for tag in dialog._canvas_view_buttons.values()]
                for rectangle in rectangles:
                    assert bar.x() <= rectangle.x() and rectangle.x() + rectangle.width() <= bar.x() + bar.width(), (bar, rectangle)
                    assert bar.y() <= rectangle.y() and rectangle.y() + rectangle.height() <= bar.y() + bar.height(), (bar, rectangle)
                for first, second in zip(rectangles, rectangles[1:]):
                    assert first.x() + first.width() <= second.x()
                dialog._redraw()
                assert all(QRetainedItem(tag).exists() for tag in dialog._canvas_view_buttons.values())

            for minimized in (True, False):
                dialog.ribbon.set_minimized(minimized)
                pump(25)
                bar = dialog._canvas_view_toolbar.globalGeometry()
                canvas = dialog._canvas_widget.globalGeometry()
                assert 5 <= bar.y() - canvas.y() <= 10
            dialog._show_tool('data')
            pump()
            assert dialog.ribbon.active_tab() == 'data'
            assert dialog._canvas_view_toolbar.isVisible()
            dialog._show_tool('extract')
            pump()

            # Global canvas handlers must not add/select/pick/zoom through the overlay.
            point = dialog._canvas_view_toolbar.globalGeometry().center()
            with patch.object(dialog._canvas_widget, 'underMouse', return_value=True), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=point):
                assert not dialog._mouse_in_canvas()
                dialog._begin_pick('curve')
                dialog._mouse_left()
                assert dialog.engine.active_dataset.curve_rgb is None
                zoom = dialog._zoom
                dialog._mouse_wheel(None, 1)
                assert dialog._zoom == zoom
                cursor = Mock()
                with patch.object(dialog, '_canvas_cursor', cursor):
                    dialog._sync_canvas_cursor()
                cursor.update.assert_called_once_with(None)
            dialog._cancel_pick()
            assert normalize_workspace_state({'version': 1, 'ribbon_tab': 'view'})['ribbon_tab'] == 'home'
            print('PASS canvas view tools: no View tab; fit/1:1/zoom; disabled without image; '
                  'centred floating layout at 1000/1100/1380 px; no click/wheel/cursor leakage; legacy workspace')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
