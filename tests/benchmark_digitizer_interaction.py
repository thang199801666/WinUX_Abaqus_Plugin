"""abaqus python tests/benchmark_digitizer_interaction.py [--profile].

Controlled image/1200-marker fixture; reports UI-thread costs, not hardware FPS.
"""
import cProfile
import ctypes
import io
import json
import math
import os
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.backends import dpg, get_backend
from DearUIQt.core import QPoint
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-interaction-', dir=temp) as folder, \
            patch.dict(os.environ, {'APPDATA': folder}):
        image = Path(folder) / 'chart.png'
        Image.new('RGB', (1200, 800), 'white').save(image)
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        view._gui_runtime.show()
        dialog = PlotDigitizerDialog(view)
        def pump(count):
            for _ in range(count):
                view.update()
                time.sleep(.005)
        try:
            dialog.show()
            pump(20)
            dialog._open_image(str(image))
            deadline = time.monotonic() + 10
            while dialog.engine.image is None and time.monotonic() < deadline:
                pump(1)
            pump(20)
            dialog.engine.active_dataset.extracted_pixels = [
                (float(i), 400 + 100 * math.sin(i / 80)) for i in range(1200)]
            dialog._redraw()
            pump(8)
            (x, y), (width, height) = dialog._canvas_rect()
            point = [int(x + width / 2), int(y + height / 3)]
            profiler = cProfile.Profile()
            backend = get_backend()
            counts = {'draws': 0, 'deletes': 0, 'configures': 0}
            originals = {name: getattr(backend, name) for name in
                         ('draw_circle', 'draw_line', 'draw_image', 'draw_text',
                          'draw_rectangle', 'delete_item', 'configure_item')}
            def count(name):
                def call(*args, **kwargs):
                    key = 'deletes' if name == 'delete_item' else 'configures' if name == 'configure_item' else 'draws'
                    counts[key] += 1
                    return originals[name](*args, **kwargs)
                return call
            from contextlib import ExitStack
            with ExitStack() as stack:
                for name in originals:
                    stack.enter_context(patch.object(backend, name, count(name)))
                stack.enter_context(patch('WinUx.plotdigitizer.ui.controllers.canvas.QCursor.pos',
                                          side_effect=lambda *a, **k: QPoint(*point)))
                # Hit-test fixture is controlled; retain the real paint/layout
                # and renderer calls but don't depend on another desktop app.
                stack.enter_context(patch.object(dialog, '_mouse_in_canvas', return_value=True))
                if '--profile' in sys.argv:
                    profiler.enable()
                results = {}
                for phase in ('idle', 'hover', 'pan', 'zoom', 'zoom_burst'):
                    timings = []
                    for key in counts:
                        counts[key] = 0
                    dialog._middle_drag = phase == 'pan'
                    dialog._last_mouse = tuple(point)
                    for index in range(24):
                        if phase != 'idle':
                            point[0] += 2
                        started = time.perf_counter()
                        if phase in ('zoom', 'zoom_burst'):
                            for _ in range(6 if phase == 'zoom_burst' else 1):
                                dialog._zoom_at(1.01 if index % 2 == 0 else 1 / 1.01, mouse=tuple(point))
                        else:
                            dialog._mouse_move()
                        view.update()
                        timings.append((time.perf_counter() - started) * 1000)
                    results[phase] = {'median_ms': round(statistics.median(timings), 2),
                                      'p95_ms': round(sorted(timings)[22], 2), **counts}
                profiler.disable()
                dialog._middle_drag = False
            print(json.dumps(results, indent=2), flush=True)
            if '--profile' in sys.argv:
                report = io.StringIO()
                pstats.Stats(profiler, stream=report).strip_dirs().sort_stats('cumtime').print_stats(45)
                print(report.getvalue(), flush=True)
        finally:
            dialog._middle_drag = False
            dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
