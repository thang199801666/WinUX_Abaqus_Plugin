"""Launch this source tree with window-only diagnostics; no SSH data is logged.

Usage: abaqus python tools/trace_dialog_focus.py
Add --listview to trace selection/scroll mutations without recording file names.
"""
from __future__ import annotations

import ctypes
import functools
import json
import os
import sys
import time
import traceback
import weakref
from ctypes import wintypes
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # Pin the diagnostic process to the edited source, not an updater cache.
    # Changes to the environment apply to this child process only.
    os.environ['WINUX_APP_DIR'] = str(ROOT)
    os.environ['WINUX_SKIP_UPDATE'] = '1'
    os.environ['WINUX_PREFER_BUNDLED_RUNTIME'] = '1'
    os.environ['WINUX_STANDALONE_PROCESS'] = '1'
    os.environ.pop('WINUX_EXISTING_PID', None)
    import run_winux
    run_winux._configure_bundled_dependencies(str(ROOT))
    from DearUIQt.backends import native_windows as windows
    from DearUIQt.dialogs.qt_dialog import QtDialog
    from DearUIQt.runtime import QGuiRuntime

    folder = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('winux-dialog-focus-{}.jsonl'.format(os.getpid()))
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    state = {'lease': None, 'frames': 0}

    with path.open('x', encoding='utf-8') as output:
        def snapshot():
            foreground = int(user32.GetForegroundWindow() or 0)
            result = {
                'foreground': foreground,
                'foreground_pid': windows._window_process_id(user32, foreground),
                'input_tick': windows._last_input_tick(user32),
            }
            lease = state['lease']
            if lease is not None:
                result['lease'] = asdict(lease)
                for label, hwnd in (('child', lease.child_hwnd), ('owner', lease.owner_hwnd)):
                    handle = wintypes.HWND(hwnd)
                    result[label] = {
                        'live': bool(user32.IsWindow(handle)),
                        'visible': bool(user32.IsWindowVisible(handle)),
                        'enabled': bool(user32.IsWindowEnabled(handle)),
                        'iconic': bool(user32.IsIconic(handle)),
                    }
            return result

        def record(event, **fields):
            # Diagnostics must never change a close decision or swallow errors.
            try:
                data = {'time': time.time(), 'event': event, **snapshot(), **fields}
                output.write(json.dumps(data, ensure_ascii=True) + '\n')
                output.flush()
            except Exception:
                pass

        listviews = weakref.WeakSet()
        last_list_states = {}
        def list_state(view):
            from DearUIQt.backends import get_backend
            backend = get_backend()
            return {
                'view': str(view.window_tag), 'rows': len(view.items),
                'selected': sorted(view.selected), 'current': view._current_index,
                'scroll_y': round(float(backend.get_y_scroll(view.body_window)), 3),
                'scroll_max': round(float(backend.get_y_scroll_max(view.body_window)), 3),
                'focus': bool(view._has_focus), 'mouse_down': bool(view._mouse_down),
                'interaction_serial': view.interactionSerial(),
            }
        def callers():
            return [{'file': Path(frame.filename).name, 'line': frame.lineno,
                     'function': frame.name}
                    for frame in traceback.extract_stack(limit=8)[:-2]]
        def sample_lists():
            for view in tuple(listviews):
                try:
                    current = list_state(view)
                    if last_list_states.get(id(view)) != current:
                        record('list.state', list=current)
                        last_list_states[id(view)] = current
                except Exception:
                    continue

        if '--listview' in sys.argv:
            from DearUIQt.backends import get_backend
            from WinUx.ui.components.explorer.list_view import ExplorerListView
            initialize_list = ExplorerListView.__init__
            @functools.wraps(initialize_list)
            def initialize(view, *args, **kwargs):
                initialize_list(view, *args, **kwargs)
                listviews.add(view)
            ExplorerListView.__init__ = initialize

            def trace_list(name):
                original = getattr(ExplorerListView, name)
                @functools.wraps(original)
                def traced(view, *args, **kwargs):
                    try:
                        record('list.' + name + '.enter', list=list_state(view), callers=callers())
                    except Exception:
                        pass
                    result = original(view, *args, **kwargs)
                    try:
                        record('list.' + name + '.exit', list=list_state(view))
                    except Exception:
                        pass
                    return result
                setattr(ExplorerListView, name, traced)
            for name in ('set_items', '_commit_selection_state', '_set_keyboard_focus',
                         '_on_left_down', '_on_left_release'):
                trace_list(name)

            backend = get_backend()
            def trace_renderer(name):
                original = getattr(backend, name)
                @functools.wraps(original)
                def traced(item, *args, **kwargs):
                    relevant = [view for view in tuple(listviews)
                                if item in (view.window_tag, view.body_window, view.body_canvas)]
                    if relevant:
                        # Only numeric scroll requests or a focus target ID are
                        # logged, never renderer values/text or shell input.
                        fields = {'target': str(item), 'callers': callers()}
                        if name != 'focus_item':
                            value = args[0] if args else kwargs.get('value')
                            if isinstance(value, (int, float)):
                                fields['value'] = value
                        record('renderer.' + name, **fields)
                    return original(item, *args, **kwargs)
                setattr(backend, name, traced)
            for name in ('set_y_scroll', 'set_x_scroll', 'focus_item'):
                trace_renderer(name)

        def trace_backend(name):
            original = getattr(windows.NativeWindowBackend, name)
            @functools.wraps(original)
            def traced(backend, *args, **kwargs):
                if name == 'beginOwnerClose':
                    state['frames'] = 30
                elif args and isinstance(args[0], windows._OwnerCloseLease):
                    state['lease'] = args[0]
                record(name + '.enter')
                try:
                    result = original(backend, *args, **kwargs)
                except Exception as error:
                    record(name + '.error', error_type=type(error).__name__)
                    raise
                if isinstance(result, windows._OwnerCloseLease):
                    state['lease'] = result
                record(name + '.exit', result=asdict(result) if is_dataclass(result) else result)
                return result
            setattr(windows.NativeWindowBackend, name, traced)

        for name in ('beginOwnerClose', 'hideForOwnerClose', 'repairOwnerAfterHide',
                     'disarmModalBeforeHide'):
            trace_backend(name)

        def trace_dialog(name):
            original = getattr(QtDialog, name)
            @functools.wraps(original)
            def traced(dialog, *args, **kwargs):
                state['frames'] = 30
                record('dialog.' + name + '.enter', dialog_type=type(dialog).__name__)
                try:
                    return original(dialog, *args, **kwargs)
                finally:
                    record('dialog.' + name + '.exit', dialog_type=type(dialog).__name__)
            setattr(QtDialog, name, traced)

        for name in ('hide', 'destroy', '_queue_native_close_request'):
            trace_dialog(name)

        render = QGuiRuntime.renderFrame
        @functools.wraps(render)
        def render_frame(runtime, *args, **kwargs):
            if state['frames']:
                record('render.enter')
            result = render(runtime, *args, **kwargs)
            sample_lists()
            if state['frames']:
                record('render.exit')
                state['frames'] -= 1
            return result
        QGuiRuntime.renderFrame = render_frame

        record('startup', pid=os.getpid(), directory=str(ROOT),
               native_module=str(Path(windows.__file__).resolve()),
               dialog_module=str(Path(sys.modules[QtDialog.__module__].__file__).resolve()))
        print('Dialog focus log: {}'.format(path), flush=True)
        if '--self-check' in sys.argv:
            record('self_check.complete')
            return
        from WinUx import run
        try:
            run()
        finally:
            record('shutdown')


if __name__ == '__main__':
    main()
