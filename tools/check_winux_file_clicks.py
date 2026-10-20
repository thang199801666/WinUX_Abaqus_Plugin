"""Verify real left/double clicks reach local file-list rows.

The harness builds the actual application view (native tools included),
populates the local panel with sample rows and drives the main viewport HWND
with genuine WM_LBUTTONDOWN/WM_LBUTTONUP messages so the real native input
pipeline — not an injected event — decides whether a file row is selectable.
When a click has no effect, every input gate state is printed to identify the
exact blocking layer.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-deps", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from winux_native_runtime import native_runtime_path
    runtime_path = str(args.native_deps.resolve()) if args.native_deps else native_runtime_path(str(root))
    if not runtime_path:
        raise RuntimeError("Install the native DearUIQt runtime before this acceptance test")
    if args.native_deps:
        sys.path.insert(0, runtime_path)
        import dearpygui.dearpygui
    else:
        import WinUx
    from WinUx.controllers import REQUIRED_CALLBACK_KEYS
    from WinUx.view import WinUXView
    from WinUx.ui.behaviors.plot_docking import PlotDockingMixin

    library = SimpleNamespace(snapshot=lambda: [], replace=Mock())
    callbacks = {name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS}
    errors = []
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    temp_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="winux-file-clicks-", dir=temp_root) as sample, \
            patch.object(PlotDockingMixin, "_get_reference_chart_library", lambda self: library), \
            patch("subprocess.Popen", side_effect=AssertionError("Native tools must not spawn a dialog process")):
        view = WinUXView(callbacks)
        view.show_error = lambda *values: errors.append(AssertionError(str(values)))

        rows = []
        for index in range(5):
            (Path(sample) / "sample_{}.odb".format(index)).touch()
            rows.append(SimpleNamespace(
                name="sample_{}.odb".format(index),
                path=os.path.join(sample, "sample_{}.odb".format(index)),
                is_dir=False, size=1024 * (index + 1), modified=0.0,
                type_text="ODB file", is_hidden=False))
        display_error = None
        try:
            view.left.display(sample, rows)
        except Exception:
            import traceback
            display_error = traceback.format_exc()

        listview = view.left.listview
        context = {}
        from DearUIQt.core.application import QApplication
        from DearUIQt.core import QEvent
        app = QApplication.instance()
        pointer_events = []
        dispatch_pointer = app.dispatchPointerEvent

        def trace_pointer(event):
            if event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                return dispatch_pointer(event)
            target = app._pointer_target_at(event.globalPosition())
            entry = {"type": event.type(), "button": event.button(),
                     "position": event.globalPosition(),
                     "target": target.objectName() if target else None}
            pointer_events.append(entry)
            try:
                return dispatch_pointer(event)
            except Exception as exc:
                entry["error"] = repr(exc)
                raise
            finally:
                entry["pending"] = listview._pending_click_index
                entry["mouse_down"] = listview._mouse_down
                entry["selected"] = sorted(listview.selected)

        app.dispatchPointerEvent = trace_pointer

        def gate_snapshot(point):
            from DearUIQt.core.application import QApplication
            from DearUIQt import input_gate, modal
            app = QApplication.instance()
            state = {}
            for name, call in (
                    ("legacy_blocked", lambda: app._legacy_pointer_input_blocked()),
                    ("grabber", lambda: repr(app.mouseGrabberObject())),
                    ("active_popup", lambda: repr(app.activePopupWidget())),
                    ("active_modal", lambda: repr(app.activeModalWidget())),
                    ("native_modal_active", lambda: bool(input_gate.native_modal_input_active())),
                    ("popup_input_active", lambda: bool(input_gate.popup_input_active())),
                    ("pointer_blocked", lambda: bool(input_gate.pointer_input_is_blocked(listview))),
                    ("visible_modal", lambda: bool(modal.visible_modal_window_exists())),
                    ("overlay_owns_input", lambda: bool(listview._overlay_window_owns_input())),
                    ("protected_under_pointer", lambda: repr(input_gate._protected_surface_under_pointer())),
                    ("pointer_target_at", lambda: repr(app._pointer_target_at(point))),
                    ("explorer_hit_test", lambda: bool(listview._qt_pointer_hit_test(point))),
                    ("row_at_mouse", lambda: listview._row_at_mouse()),
                    ("mouse_in_body", lambda: bool(listview._mouse_in_body())),
                    ("body_local_pos", lambda: listview._body_local_pos()),
            ):
                try:
                    state[name] = call()
                except Exception as exc:
                    state[name] = "error: {!r}".format(exc)
            state["modal_tags"] = sorted(str(tag) for tag in modal.MODAL_TAGS)
            return state

        def click(hwnd, point, count=1):
            cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            # DPG world space equals absolute screen space for the main
            # viewport (winux_primary pos == OS client-origin screen pos).
            screen = wintypes.POINT(*point)
            client_origin = wintypes.POINT()
            user32.ClientToScreen(hwnd, ctypes.byref(client_origin))
            client = (point[0] - client_origin.x, point[1] - client_origin.y)
            if (screen.x, screen.y) != (cursor.x, cursor.y):
                user32.SetCursorPos(screen.x, screen.y)
            # The automation session cannot always move the real cursor, but
            # ImGui_ImplWin32_WndProcHandler derives io.MousePos from message
            # client coordinates: WM_MOUSEMOVE transports the intended position.
            lparam = (int(client[1]) << 16) | (int(client[0]) & 0xFFFF)
            user32.PostMessageW(hwnd, 0x0200, 0x0000, lparam)  # WM_MOUSEMOVE
            for _ in range(24):
                time.sleep(0.03)
                if _dpg_mouse_pos() == (float(screen.x), float(screen.y)):
                    break
            for _ in range(count):
                user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
                user32.PostMessageW(hwnd, 0x0202, 0x0000, lparam)  # WM_LBUTTONUP
            after = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(after))
            return {
                "cursor_before": (cursor.x, cursor.y),
                "cursor_now": (after.x, after.y),
                "screen": (screen.x, screen.y),
                "client": client,
                "dpg_mouse_after": _dpg_mouse_pos(),
                "clicks": count,
            }

        def _parent_chain():
            from DearUIQt.backends import dpg
            chain = []
            parent = getattr(listview, "window_tag", None)
            guard = 0
            while parent and guard < 12:
                guard += 1
                try:
                    info = dpg.get_item_info(parent)
                    state = dpg.get_item_state(parent)
                    chain.append({
                        "tag": str(parent),
                        "type": str(info.get("type")),
                        "pos": state.get("pos"),
                        "rect_size": state.get("rect_size"),
                    })
                    parent = dpg.get_item_parent(parent)
                except Exception as exc:
                    chain.append("error: {!r}".format(exc))
                    break
            return chain

        def _cursor_snapshot():
            from DearUIQt.gui import QCursor
            cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            viewport = listview._body_viewport_rect()
            return {
                "os_cursor": (cursor.x, cursor.y),
                "qt_cursor": (QCursor.pos().x(), QCursor.pos().y()),
                "body_viewport": viewport,
                "window_rect": listview._safe_item_rect(getattr(listview, "window_tag", None)),
                "main_hwnd_rect": _hwnd_screen_rect(context.get("hwnd")),
                "dpg_mouse_pos": _dpg_mouse_pos(),
                "parent_chain": _parent_chain(),
            }

        def _hwnd_screen_rect(hwnd):
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            client = wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client))
            origin = wintypes.POINT()
            ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin))
            return {
                "window": (rect.left, rect.top,
                           rect.right - rect.left, rect.bottom - rect.top),
                "client_origin_screen": (origin.x, origin.y),
                "client_size": (client.right - client.left, client.bottom - client.top),
            }

        def _dpg_mouse_pos():
            from DearUIQt.backends import dpg
            try:
                return tuple(map(float, dpg.get_mouse_pos(local=False)))
            except Exception as exc:
                return "error: {!r}".format(exc)

        def scenario():
            hwnd = view._find_main_viewport_hwnd()
            context["hwnd"] = hwnd
            assert hwnd, "Main viewport HWND not found"
            yield "layout-ready", lambda: bool(listview.items) and listview._body_viewport_rect() is not None
            body = listview._body_viewport_rect()
            point = (round(body[0] + 10), round(body[1] + float(listview.ROW_HEIGHT) * 0.5))
            context["point"] = point

            listview.clear_selection()
            sent = click(hwnd, point)
            yield "left-select", lambda: len(listview.selected) > 0

            # Exercise rename in the real application loop, then verify that
            # the native editor has not stranded global pointer ownership.
            from DearUIQt import input_gate
            committed = []
            old_path = Path(rows[0].path)

            def commit_created(name):
                target = Path(rows[0].path).with_name(name)
                Path(rows[0].path).rename(target)
                rows[0].name, rows[0].path = target.name, str(target)
                committed.append(name)
                view.after(0, view.left.display, sample, rows)
                return target

            # Use New's actual FilePanel route, not a ListView-only callback.
            assert view.left.focus_created_item(str(old_path), commit_created)
            yield "rename-editor", lambda: listview._rename_textbox._native_editor is not None
            editor = listview._rename_textbox._native_editor
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
            user32.SetWindowTextW(editor._hwnd_edit, "renamed.odb")
            user32.PostMessageW(editor._hwnd_edit, 0x0100, 0x0D, 0)
            user32.PostMessageW(editor._hwnd_edit, 0x0101, 0x0D, 0)
            yield "rename-commit", lambda: not listview._rename_active
            assert committed == ["renamed.odb"]
            assert Path(rows[0].path).is_file() and not old_path.exists()
            assert input_gate._pointer_owner is None, "Rename stranded the global pointer gate"
            assert app.mouseGrabberObject() is None, "Rename stranded application capture"

            # Enter without editing the default name must also end rename.
            assert view.left.focus_created_item(rows[0].path, commit_created)
            yield "default-name-editor", lambda: listview._rename_textbox._native_editor is not None
            editor = listview._rename_textbox._native_editor
            user32.PostMessageW(editor._hwnd_edit, 0x0100, 0x0D, 0)
            user32.PostMessageW(editor._hwnd_edit, 0x0101, 0x0D, 0)
            yield "default-name-enter", lambda: not listview._rename_active
            assert committed == ["renamed.odb"], "Unchanged name dispatched another rename"

            view.right.display(sample, rows)
            right = view.right.listview
            yield "right-layout", lambda: right._body_viewport_rect() is not None
            right_body = right._body_viewport_rect()
            right_point = (round(right_body[0] + 10),
                           round(right_body[1] + float(right.ROW_HEIGHT) * 0.5))
            right.clear_selection()
            click(hwnd, right_point)
            yield "other-pane-click-after-rename", lambda: bool(right.selected)

            listview.clear_selection()
            callbacks["double_click"].reset_mock()
            click(hwnd, point, count=2)
            yield "double-activate", lambda: bool(callbacks["double_click"].called)

        steps = scenario()
        pending = []
        debug_frames = []

        def probe_layout():
            from DearUIQt.backends import dpg
            from DearUIQt.widgets import QRetainedItem
            canvas = getattr(listview, "body_canvas", None)
            body = getattr(listview, "body_window", None)
            overlay = getattr(listview, "_scroller_arrow_overlay", None)
            entry = {"overlay": None if overlay is None else repr(getattr(overlay, "container", None))}
            for key, tag in (("body_window", body), ("body_canvas", canvas),
                             ("window", getattr(listview, "window_tag", None)),
                             ("header", getattr(listview, "header_canvas", None)),
                             ("pinned", getattr(listview, "pinned_canvas", None))):
                item = QRetainedItem(tag)
                if not item.exists():
                    entry[key] = "missing"
                    continue
                try:
                    entry[key] = {
                        "exists": True,
                        "shown": item.isVisible(),
                        "geometry": None,
                    }
                    ge = item.globalGeometry()
                    entry[key]["geometry"] = (
                        (ge.x(), ge.y(), ge.width(), ge.height()) if ge.isValid() else None)
                    entry[key]["clipped"] = None
                    try:
                        gcd = item.globalGeometry(clipped=True)
                        entry[key]["clipped"] = (
                            (gcd.x(), gcd.y(), gcd.width(), gcd.height()) if gcd.isValid() else None)
                    except Exception:
                        pass
                    entry[key]["native_state_keys"] = sorted(
                        key for key, value in (item.nativeState() or {}).items() if value is not None)
                    state = item.nativeState() or {}
                    entry[key]["pos"] = state.get("pos")
                    entry[key]["rect_min"] = state.get("rect_min")
                    entry[key]["rect_size"] = state.get("rect_size")
                except Exception as exc:
                    entry[key] = "error: {!r}".format(exc)
            for key, tag in (("body_window", body),):
                item = QRetainedItem(tag)
                if item.exists():
                    try:
                        entry["scroll"] = (item.verticalScrollMaximum(),
                                           item.horizontalScrollMaximum())
                    except Exception as exc:
                        entry["scroll"] = "error: {!r}".format(exc)
            entry["resize_pending"] = getattr(listview, "_resize_layout_pending", None)
            debug_frames.append(entry)
            return None

        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    name, condition, deadline = pending[0]
                    if not condition():
                        if len(debug_frames) < 40:
                            probe_layout()
                        if time.monotonic() >= deadline:
                            point = context.get("point")
                            layout_state = None
                            if point is None:
                                from DearUIQt.backends import dpg
                                from DearUIQt.widgets import QRetainedItem
                                from DearUIQt.backends.dearpygui_scroller import dpg_window_rect
                                overlay = getattr(listview, "_scroller_arrow_overlay", None)
                                container = getattr(overlay, "container", None)
                                steps_state = {}
                                try:
                                    geo = QRetainedItem(container)
                                    steps_state["container_exists"] = geo.exists()
                                    steps_state["container_clipped"] = None
                                    if geo.exists():
                                        clipped = geo.globalGeometry(clipped=True)
                                        steps_state["container_clipped"] = (
                                            (clipped.x(), clipped.y(), clipped.width(), clipped.height())
                                            if clipped.isValid() else None)
                                    steps_state["container_window_rect"] = dpg_window_rect(
                                        dpg, container, clip=True)
                                except Exception as exc:
                                    steps_state["container_error"] = repr(exc)
                                try:
                                    canvas = QRetainedItem(getattr(listview, "body_canvas", None))
                                    body = QRetainedItem(getattr(listview, "body_window", None))
                                    canvas_state = canvas.nativeState() or {}
                                    canvas_rect_min = canvas_state.get("rect_min")
                                    if canvas_rect_min is None and canvas.exists():
                                        pos = canvas.globalPos()
                                        canvas_rect_min = (pos.x(), pos.y())
                                    if canvas_rect_min is not None and body.exists():
                                        scroll_x = body.horizontalScrollValue()
                                        scroll_y = body.verticalScrollValue()
                                        size = body.globalGeometry().size()
                                        vx0 = float(canvas_rect_min[0]) + scroll_x
                                        vy0 = float(canvas_rect_min[1]) + scroll_y
                                        vx1 = vx0 + float(size.width())
                                        vy1 = vy0 + float(size.height())
                                        pane = listview._safe_item_rect(listview.window_tag)
                                        if pane is not None:
                                            px0, py0, px1, py1 = pane
                                            vx0, vx1 = max(vx0, px0), min(vx1, px1)
                                            vy0, vy1 = max(vy0, py0), min(vy1, py1)
                                        steps_state["canvas_fallback"] = (
                                            vx0, vy0, vx1, vy1, bool(vx1 > vx0 and vy1 > vy0))
                                except Exception as exc:
                                    steps_state["canvas_error"] = repr(exc)
                                layout_state = {
                                    "display_error": display_error,
                                    "items": len(listview.items),
                                    "window_tag": getattr(listview, "window_tag", None),
                                    "window_exists": bool(
                                        dpg.does_item_exist(getattr(listview, "window_tag", None))),
                                    "window_rect": listview._safe_item_rect(getattr(listview, "window_tag", None)),
                                    "body_rect": listview._body_viewport_rect(),
                                    "body_window": getattr(listview, "body_window", None),
                                    "steps": steps_state,
                                }
                            raise AssertionError(
                                "File-list click stalled at " + name + " DIAGNOSTICS "
                                + json.dumps({
                                    "stage": name,
                                    "pointer_events": pointer_events,
                                    "gates": gate_snapshot(point) if point else None,
                                    "gesture": {
                                        "mouse_down": getattr(listview, "_mouse_down", None),
                                        "pending_click_index": getattr(listview, "_pending_click_index", None),
                                        "suppress_next_left_release": getattr(listview, "_suppress_next_left_release", None),
                                        "renaming": getattr(listview, "_rename_active", None),
                                    },
                                    "cursor": _cursor_snapshot(),
                                    "layout": layout_state if layout_state is not None else None,
                                    "probes": debug_frames,
                                    "selected": [item.path for item in listview.get_selected()],
                                    "double_click_called": bool(callbacks["double_click"].called),
                                }, default=str))
                        view.after(1, advance)
                        return
                    pending.clear()
                name, condition = next(steps)
                pending.append((name, condition, time.monotonic() + 3.0))
                view.after(1, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()

        view.after(300, advance)
        view.run()
    if errors:
        raise errors[-1]
    print("WINUX_FILE_CLICKS_OK", flush=True)


if __name__ == "__main__":
    main()
