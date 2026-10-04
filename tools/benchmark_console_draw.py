"""Native-item microbenchmark without opening a viewport or rendering GPU frames."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-deps', required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.native_deps)
    import dearpygui.dearpygui as dpg
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.test_console_renderer import fixture
    samples, counts = {}, {}
    dpg.create_context()
    try:
        for mode in ('repaint_on_blink', 'caret_only'):
            durations = []
            for repeat in range(5):
                view, _, renderer = fixture()
                renderer.backend = dpg
                window = dpg.add_window()
                view.content = dpg.add_child_window(parent=window, width=640, height=240)
                view.canvas = dpg.add_drawlist(parent=view.content, width=640, height=240)
                view._current_line_fill = dpg.draw_rectangle((0, 0), (10, 10), parent=view.canvas)
                view._caret = dpg.draw_rectangle((0, 0), (10, 2), parent=view.canvas)
                view.buffer.set_output('\n'.join('Row {}'.format(n) for n in range(100)))
                with patch.object(dpg, 'get_item_state', return_value={'rect_size': (640, 240)}), \
                     patch('WinUx.components.console_renderer.time.monotonic') as clock:
                    clock.return_value = 0
                    renderer.paint()
                    with patch.object(dpg, 'draw_text', wraps=dpg.draw_text) as draws, \
                         patch.object(dpg, 'delete_item', wraps=dpg.delete_item) as deletes:
                        started = time.perf_counter()
                        for i in range(60):
                            clock.return_value = (i + 1) * .5
                            if mode == 'repaint_on_blink':
                                view._last_paint = None
                            renderer.paint()
                        durations.append((time.perf_counter() - started) * 1000)
                        counts[mode] = dict(text_creations=draws.call_count, deletions=deletes.call_count)
                dpg.delete_item(window)
            samples[mode] = statistics.median(durations)
    finally:
        dpg.destroy_context()
    report = dict(scope='native DPG item dispatch with injected viewport metrics; no GPU frames or SSH',
        updates=60, transcript_lines=100, repeats=5, median_ms=samples, calls=counts,
        speedup=samples['repaint_on_blink'] / samples['caret_only'])
    Path(__file__).with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
