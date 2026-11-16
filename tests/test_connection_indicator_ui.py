"""Retained SSH connection dot follows lifecycle events without polling."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.controllers.connection import ConnectionController
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        try:
            view._gui_runtime.show()
            for _ in range(12):
                view.update()
                time.sleep(.005)
            def dot_color():
                color = dpg.get_item_configuration(view._server_connection_dot)['fill']
                return tuple(round(value * 255) for value in color)
            assert not view._server_connection_state
            def assert_aligned():
                dot_config = dpg.get_item_configuration(view._server_connection_dot)
                canvas_top = dpg.get_item_rect_min(view._server_connection_canvas.tag)[1]
                text_top = dpg.get_item_rect_min(view._right_items_label.tag)[1]
                text_height = dpg.get_item_rect_size(view._right_items_label.tag)[1]
                assert abs(canvas_top + dot_config['center'][1] - text_top - text_height / 2 - 1) <= .5
            assert_aligned()
            assert dpg.get_item_configuration(view._left_status_padding.tag)['width'] == 2
            assert dpg.get_item_configuration(view._right_status_padding.tag)['width'] == 2
            assert dot_color() == (210, 55, 55, 255)
            view.display_server_directory(PurePosixPath('/test'), [], 'test-host', reset_history=True)
            assert view._server_connection_state
            assert dot_color() == (35, 160, 75, 255)
            view._gui_runtime.configureViewport(width=1000, height=700)
            for _ in range(12):
                view.update()
                time.sleep(.005)
            assert_aligned()
            backend = view._gui_runtime.backend
            with patch.object(backend, 'configure_item', wraps=backend.configure_item) as configure:
                for _ in range(100):
                    view.set_server_connection_state(True)
                configure.assert_not_called()
            view.show_server_disconnected()
            assert dot_color() == (210, 55, 55, 255)
            assert view.right.status.get() == 'Not connected'

            # Delivery reads current transport state rather than applying a
            # stale disconnected result queued before a successful reconnect.
            app = SimpleNamespace(_closing=False, view=view, server=SimpleNamespace(connected=True))
            controller = ConnectionController.__new__(ConnectionController)
            controller.app = app
            controller._update_connection_indicator()
            assert dot_color() == (35, 160, 75, 255)
            app.server.connected = False
            controller._update_connection_indicator()
            assert dot_color() == (210, 55, 55, 255)
            app._closing = True
            with patch.object(view, 'set_server_connection_state') as setter:
                controller._update_connection_indicator()
                setter.assert_not_called()
            print('PASS: initial red, connected green, disconnected red, retained no-op updates, current reconnect state and shutdown guard')
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
