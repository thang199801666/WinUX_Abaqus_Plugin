"""Real transformed drag overlay and Transfer Center show/hide timings."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.gui import QCursor
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.explorer_list_model import ListViewItem
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        helper = view.right.listview._drag_preview
        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.005)
        def wait_until(predicate, timeout=2):
            deadline = time.monotonic() + timeout
            frames = 0
            while not predicate() and time.monotonic() < deadline:
                pump(1)
                frames += 1
            assert predicate()
            return frames
        try:
            view._gui_runtime.show()
            pump(16)
            primary_hwnd = NativeWindowBackend().primaryWinId()
            origin = wintypes.POINT()
            if NativeWindowBackend().isEnabled():
                ctypes.windll.user32.ClientToScreen(wintypes.HWND(primary_hwnd), ctypes.byref(origin))
            def paint_point(x, y):
                return origin.x + x, origin.y + y
            with patch.object(QCursor, 'paintPos', return_value=paint_point(100, 120)) as cursor:
                helper.begin([ListViewItem('example.inp'), ListViewItem('results.odb')])
                helper.update(True, '/work/results')
                pump()
                assert helper._group.isVisible()
                assert helper._group._translation == paint_point(109, 131)
                assert tuple(dpg.get_item_configuration(helper._parts['panel'])['pmin'])[:2] == (0, 0)
                from DearUIQt.backends.shared_scrollers import update_shared_scrollers
                def late_sample(backend):
                    cursor.return_value = paint_point(450, 220)
                    update_shared_scrollers(backend)
                with patch('DearUIQt.backends.shared_scrollers.update_shared_scrollers', side_effect=late_sample):
                    view._gui_runtime.renderFrame()
                assert helper._group._translation == paint_point(459, 231), 'Preview sampled before renderer preparation'
                measure = Mock(wraps=helper._measure)
                helper._measure = measure
                start = time.perf_counter()
                for i in range(1000):
                    helper.moveToCursor(paint_point(100 + i % 400, 120 + i % 100))
                duration_ms = (time.perf_counter() - start) * 1000
                measure.assert_not_called()
                cursor.return_value = paint_point(300, 150)
                helper.moveToCursor(paint_point(300, 150))
                helper.update(True, '/work/results')
                helper.moveToCursor(paint_point(300, 150))
                measure.assert_not_called()
                pump()
                framebuffer = root / 'drag_preview_frame.png'
                if framebuffer.exists():
                    framebuffer.unlink()
                dpg.output_frame_buffer(str(framebuffer))
                pump(4)
                if framebuffer.exists():
                    from PIL import Image
                    with Image.open(framebuffer) as image:
                        accent = tuple(image.getpixel((318, 180)))[:3]
                        assert accent == tuple(helper.theme_config.get('drag_accent', (0, 120, 215, 255)))[:3], accent
                    print('FRAMEBUFFER', framebuffer)
                helper.end()
                assert not helper._group.isVisible(), 'Preview hide must not wait for another UI turn'
                assert helper._render_token is None
            # A drag-start warm-up must never hide an already-visible transfer.
            start = time.perf_counter()
            center = view._get_transfer_center()
            cold_ms = (time.perf_counter() - start) * 1000
            task = center.add_task('Upload', threading.Event(), ['example.inp'])
            wait_until(lambda: task.rows[0].row_id in center.row_widgets)
            wait_until(lambda: center.isVisible() and not getattr(center, '_native_presentation_pending', False))
            pump(2)
            assert center.isVisible()
            view._prewarm_transfer_center()
            assert center.isVisible()
            # The final completion display hold is bounded to 120ms, not 900ms.
            start = time.perf_counter()
            old_hwnd = center._native_window_backend.winId(center.tag) if center._native_window_backend is not None else 0
            task.complete()
            hide_frames = wait_until(lambda: not center.isVisible() and
                                      (not old_hwnd or not ctypes.windll.user32.IsWindowVisible(wintypes.HWND(old_hwnd))))
            hide_ms = (time.perf_counter() - start) * 1000
            assert hide_ms < 600, ('Transfer Center close latency', hide_ms)
            start = time.perf_counter()
            task = center.add_task('Download', threading.Event(), ['results.odb'])
            show_frames = wait_until(lambda: center.isVisible() and not getattr(center, '_native_presentation_pending', False))
            show_ms = (time.perf_counter() - start) * 1000
            task.fail('Simulated failure: keep this visible')
            pump(35)
            assert center.isVisible()
            center.clear_finished()
            pump()
            assert not center.isVisible()
            print('PASS: real grouped preview, immediate hide, no text layout on motion, visible-center warmup guard and fast completion cleanup')
            print('MEASURED: 1000 direct overlay translations {:.2f}ms; cold shell {:.2f}ms; warm native-ready show {:.2f}ms/{} turns; completed native hide {:.2f}ms/{} turns'.format(
                duration_ms, cold_ms, show_ms, show_frames, hide_ms, hide_frames))
        finally:
            helper.end()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
