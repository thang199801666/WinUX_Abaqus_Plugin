"""Child-side DPG lifecycle: build, warm up invisibly, center, publish, run."""
from __future__ import annotations

import heapq
import itertools
import os
from pathlib import Path
import queue
import threading
import time

from ..native.floating_viewport import (
    NativeViewport, ViewportCreationGuard, centered_position, window_rect, work_area, cloaked, set_cloaked, wake_native_window, window_dpi,
)
from ...dialogs.floating_forms import create_form, deliver_command, client_layout
from DearUIQt.themes import DialogMetrics
from DearUIQt.core import QThreadPool
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.widgets import QLabel, QMainWindow, QImageView, QRetainedItem
from DearUIQt.layouts import QHBoxLayout
from DearUIQt.gui import QCursor
from ...services.floating_protocol import read_messages, encode_message
from ...runtime.dpg_callbacks import run_callback_jobs
from ..native.message_pump import pump_native_messages, wait_native_messages
from DearUIQt.input_gate import native_background_input_blocked, release_pointer_input


PUBLISH_HANDSHAKE_TIMEOUT = 20.0


_RUNTIME_IO_POOL = QThreadPool(maxThreadCount=2, maxPending=8, name="dialog-runtime-io")


class ChildView:
    use_native_file_selectors = True
    is_standalone_ui_host = True

    def __init__(self):
        self.queue = []
        self.sequence = itertools.count()
        self.incoming = queue.Queue()
        self._native_hwnd = 0
        self._first_presented = False
        self._presentation_visible = False
        self._first_present_callbacks = []

    def _find_main_viewport_hwnd(self):
        return self._native_hwnd

    def after(self, delay, callback, *args):
        self.incoming.put((time.monotonic() + max(0, delay)/1000,
                           next(self.sequence), callback, args))

    def after_render(self, callback, *args):
        self.after(0, callback, *args)

    def after_first_present(self, callback, *args):
        """Defer data work until this lease has rendered an exposed frame."""
        if self._first_presented:
            self.after(0, callback, *args)
        else:
            self._first_present_callbacks.append((callback, args))

    def mark_presented(self):
        self._presentation_visible = True
        if self._first_presented:
            return
        self._first_presented = True
        callbacks, self._first_present_callbacks = self._first_present_callbacks, []
        for callback, args in callbacks:
            self.after(0, callback, *args)

    def drain(self):
        while True:
            try:
                heapq.heappush(self.queue, self.incoming.get_nowait())
            except queue.Empty:
                break
        for _ in range(64):
            if not self.queue or self.queue[0][0] > time.monotonic():
                break
            _, _, callback, args = heapq.heappop(self.queue)
            callback(*args)


def configure_context(view):
    from ..appearance import configure_ui_context
    configure_ui_context(view)


class PreparedViewport:
    """An idle graphics context, exclusively leased to one dialog at a time."""
    def __init__(self, connection, messages):
        self.connection, self.messages = connection, messages
        self.view = ChildView()
        self.incoming = queue.Queue(maxsize=64)
        self.native = None
        self.gui = QGuiRuntime()
        self.startup = []
        self.last_layout_spec = None

    @classmethod
    def adopt(cls, runtime):
        """Turn a clean cold runtime into the same reusable host abstraction.

        The first dialog in a process may have been created before a prewarmed
        viewport was available.  Once that dialog closes cleanly, keep its DPG
        context/native HWND and the existing IPC reader instead of destroying
        the process.  Subsequent leases then follow the normal PreparedViewport
        recycle path.
        """
        prepared = cls.__new__(cls)
        prepared.connection = runtime.connection
        prepared.messages = runtime.messages
        prepared.view = runtime.view
        prepared.incoming = runtime.incoming
        prepared.native = runtime.native
        prepared.gui = runtime.gui
        prepared.startup = []
        prepared.last_layout_spec = None
        return prepared

    def wait_for_init(self):
        def reader():
            try:
                for message in self.messages:
                    self.incoming.put(message)
                    if self.native is not None:
                        wake_native_window(self.native.hwnd)
            except (OSError, ValueError):
                pass
            finally:
                self.incoming.put({"command": "shutdown"})
                if self.native is not None:
                    wake_native_window(self.native.hwnd)
        _RUNTIME_IO_POOL.start(reader)
        # Form callbacks query/mutate retained widgets. Run them only through
        # _drain_form_callbacks on this GUI thread, never DPG's callback worker
        # concurrently with construction, rendering or lease cleanup.
        self.gui.createContext(manual_callbacks=True)
        configure_context(self.view)
        self.blank = QMainWindow("", width=1, height=1)
        QRetainedItem(self.blank.tag).configure(
            no_title_bar=True, no_move=True, no_resize=True)
        # The renderer loads fonts lazily when they are first used. Warm the
        # common faces before advertising a reusable dialog host.
        for font_name in ("body_font", "heading_font", "terminal_font"):
            font = getattr(self.view, font_name, None)
            if font is not None:
                sample = QLabel("WinUx AaBb 0123456789", parent=self.blank)
                sample.setFont(font)
        from ..appearance import viewport_icon_options
        self.gui.createViewport(title="WinUx Dialog Worker", width=480, height=300, vsync=False,
                                **viewport_icon_options())
        self.gui.setPrimaryWindow(self.blank, True)
        self.gui.setup()
        with ViewportCreationGuard(hide_taskbar=True) as guard:
            self.gui.show()
        self.startup.extend(guard.events)
        self.native = NativeViewport(guard.hwnd, True)
        self.native.configure(0, hide_taskbar=True)
        for _ in range(2):
            self.gui.renderFrame()
        # A DWM-cloaked viewport is already invisible to the desktop. Keep its
        # swap-chain mapped so the first dialog frame need not resume a hidden
        # surface. Fall back to SW_HIDE if the cloak is not active.
        # Idle workers neither render nor register modality/pointer ownership.
        if not cloaked(self.native.hwnd):
            self.native._show(False)
        # A graphics-only worker still pays shared browser/control imports on
        # the first click. Resolve only common lightweight form modules before
        # advertising readiness; no form, listing, timer or callback is created.
        from ...dialogs.floating_forms import prepare_common_form_imports
        prepare_common_form_imports()
        # Pay icon decode/Shell texture upload costs before advertising a warm
        # host. Only shared graphics are created, never a form or directory scan.
        from ...dialogs.folder_browser_style import prepare_browser_textures
        textures = prepare_browser_textures()
        warm_icons = QHBoxLayout(parent=self.blank, spacing=0)
        for texture in textures:
            QImageView(texture, parent=warm_icons, width=16, height=16)
        self.gui.renderFrame()
        self.connection.sendall(encode_message({"event": "warm_ready", "pid": os.getpid(),
                                               "hwnd": self.native.hwnd}))
        initial = self.wait_for_next_init()
        if initial is not None:
            return initial
        self.gui.destroy()
        return None

    def recycle(self, previous_view, layout_spec):
        """Keep graphics/fonts alive, but isolate the next lease's callbacks."""
        self.native.restore_close_handler()
        self.native._show(False)
        set_cloaked(self.native.hwnd, True)
        self.native.visible = False
        self.native._published = False
        self.native.reveal_count = 0
        self.last_layout_spec = layout_spec
        self.native._owner_hwnd = 0
        # Clear the previous native owner explicitly; configure(0) intentionally
        # does not guess a new owner for an idle host.
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            setter = ctypes.windll.user32.SetWindowLongPtrW
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            setter(self.native.hwnd, -8, 0)
        # SW_HIDE already excludes this host from taskbar/Alt+Tab. Preserve its
        # normal caption: toggling WS_EX_TOOLWINDOW on every lease resizes the
        # native client/swap-chain even when the dialog size did not change.
        self.view = ChildView()
        for name in ("body_font", "heading_font", "terminal_font", "ui_font_family", "ui_font_size"):
            if hasattr(previous_view, name):
                setattr(self.view, name, getattr(previous_view, name))
        # Do not execute callback jobs belonging to deleted lease widgets.
        self.gui.callbackQueue()
        self.blank = QMainWindow("", width=1, height=1)
        QRetainedItem(self.blank.tag).configure(
            no_title_bar=True, no_move=True, no_resize=True)
        QLabel("", parent=self.blank)
        self.gui.setPrimaryWindow(self.blank, True)
        self.startup = []

    def wait_for_next_init(self):
        while self.gui.isRunning():
            try:
                message = self.incoming.get_nowait()
            except queue.Empty:
                self._wait_idle_events()
                continue
            if message.get("command") == "init":
                return message
            if message.get("command") == "shutdown" or (
                    message.get("command") == "close" and message.get("lease") is None):
                return None
            # Late commands from a completed lease never execute while idle.
        return None

    def _wait_idle_events(self):
        """Block in the native dispatcher while an idle warm host has no work."""
        if not self.incoming.empty():
            return
        if not wait_native_messages(500):
            self.incoming.put({"command": "shutdown"})




def _normalize_size_pair(value, fallback):
    """Return a robust (width, height) pair from DPG configuration values.

    Dear PyGui may expose unset vector properties such as ``min_size`` as an
    empty tuple on some builds/contexts (notably prepared child viewports).
    Floating dialog startup must never index those values directly.
    """
    try:
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            width = int(value[0])
            height = int(value[1])
            if width > 0 and height > 0:
                return width, height
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return max(1, int(fallback[0])), max(1, int(fallback[1]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return 320, 180


def _publish_preauthorized(initial, prepared):
    """Only a previously authenticated host HWND/lease can skip the first ACK."""
    authorized = initial.get("authorized_hwnd")
    return bool(initial.get("fast_startup") and prepared is not None and initial.get("lease") and
                type(authorized) is int and authorized > 0 and authorized == prepared.native.hwnd and
                authorized != int(initial.get("owner_hwnd") or 0))


def _settle_frame_count(prepared, layout_spec, fast):
    if prepared is None:
        return 3
    # Unknown DPI, different form or changed size always retains two passes.
    if (fast and len(layout_spec) == 7 and layout_spec[3] > 0 and
            not layout_spec[5] and not layout_spec[6] and prepared.last_layout_spec == layout_spec):
        return 1
    return 2


class FloatingDialogRuntime:
    def __init__(self, connection, messages, initial, prepared=None):
        self.connection, self.messages, self.initial = connection, messages, initial
        self._emit_lock = threading.Lock()
        self.prepared = prepared
        self.view = prepared.view if prepared else ChildView()
        self.incoming = prepared.incoming if prepared else queue.Queue(maxsize=64)
        self.native = prepared.native if prepared else None
        self.gui = prepared.gui if prepared else QGuiRuntime()
        self.form = None
        self.desired_visible = bool(initial.get("visible", True))
        self._visibility_revision = 0
        self.owner_hwnd = int(initial.get("owner_hwnd") or 0)
        self._publish_preauthorized = _publish_preauthorized(initial, prepared)
        self._publish_requested = self._publish_preauthorized
        self._commit_requested = False
        self.startup = list(prepared.startup) if prepared else []
        self.timings = {}
        self._startup_frames = []
        self._browser_pointer_samples = 0
        self.lease = initial.get("lease")
        # Reuse is negotiated by the form, not by whether this process happened
        # to start life as a prewarm worker. A clean cold first lease can be
        # adopted into PreparedViewport after close.
        self.reusable = bool(initial.get("reuse_host"))
        self.retain_on_close = bool(initial.get("retain_on_close"))
        self._hard_destroy_form = None
        self._stage_started_at = time.perf_counter()
        self.stage = "runtime-init"

    @property
    def stage(self):
        return self._stage

    @stage.setter
    def stage(self, value):
        now = time.perf_counter()
        previous = getattr(self, "_stage", None)
        if previous is not None:
            self.timings[previous] = self.timings.get(previous, 0.0) + (now - self._stage_started_at) * 1000
        self._stage = value
        self._stage_started_at = now
        # Make a stalled prewarm/recycled graphics host distinguishable from a
        # silent IPC reader. No feature payload or user data is sent here.
        self.emit("startup_progress", stage=str(value))

    def emit(self, event, **values):
        if event in ("visibility", "prepared", "staged", "ready"):
            values["visibility_revision"] = getattr(self, "_visibility_revision", 0)
        message = encode_message({"event": event, "lease": self.lease,
                                  "reuse_host": self.reusable, **values})
        # Async form providers may emit small RPC requests while the UI thread
        # publishes lifecycle events. Keep each JSON-line write indivisible.
        with self._emit_lock:
            self.connection.sendall(message)

    def _read_commands(self):
        try:
            for message in self.messages:
                self.incoming.put(message)
                if self.native is not None:
                    wake_native_window(self.native.hwnd)
        except (OSError, ValueError):
            pass
        finally:
            self.incoming.put({"command": "close"})
            if self.native is not None:
                wake_native_window(self.native.hwnd)

    def _focus_form(self):
        focus = getattr(self.form, "_focus_initial", None) or getattr(self.form, "focus_input", None)
        if callable(focus):
            focus()

    def _start_selector_prewarm(self):
        """One bounded idle selector worker for a long-lived digitizer host."""
        if self.initial.get("kind") != "plotdigitizer" or not self.form.winfo_exists():
            return
        pool = (getattr(self.view, "_dialog_host_pool", None)
                or getattr(self.view, "_dialog_prewarm_pool", None))
        if pool is None:
            from .host import QDialogHostPool
            pool = QDialogHostPool(capacity=1, reusable=True)
            self.view._dialog_host_pool = pool
            self.view._dialog_prewarm_pool = pool

    def _browser_pointer_pressed(self, event, point):
        self._trace_browser_input(event, point)
        # Never synthesize a selection in a background/disabled HWND. Only
        # repair a genuine foreground press that ImGui could not hit-test.
        if not self.native.is_foreground() or not self.form.winfo_exists():
            return
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            if not user32.IsWindowEnabled(self.native.hwnd):
                return
        point = QCursor.pos()
        mouse = (float(point.x()), float(point.y()))
        # A merely different *valid* coordinate can mean the user moved between
        # mouse-down and dispatch. Do not replay that normal ImGui press.
        if mouse != (0.0, 0.0) and all(value >= 0 for value in mouse):
            return
        recover = getattr(self.form, "native_pointer_press", None)
        if callable(recover) and recover(point):
            self._trace_browser_input("native-pointer-recovered", point)

    def _trace_browser_input(self, event, press_point=None):
        """Bounded selector input diagnostics; never log paths/editor contents."""
        if self.initial.get("kind") not in ("local_folder", "local_file"):
            return
        if event == "mouse-down":
            if self._browser_pointer_samples >= 6:
                return
            self._browser_pointer_samples += 1
        elif event == "native-pointer-recovered" and self._browser_pointer_samples >= 6:
            return
        try:
            import ctypes
            import json
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            for name in ("GetFocus", "GetActiveWindow", "GetCapture", "GetForegroundWindow"):
                function = getattr(user32, name)
                function.argtypes = []
                function.restype = wintypes.HWND
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            cursor = wintypes.POINT()
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            native_mouse = None
            if user32.GetCursorPos(ctypes.byref(cursor)):
                if user32.ScreenToClient(self.native.hwnd, ctypes.byref(cursor)):
                    native_mouse = [cursor.x, cursor.y]
            pointer = QCursor.pos()
            point = (float(pointer.x()), float(pointer.y()))
            targets = {}
            for name, item in (("places", self.form.places), ("list", self.form.listbox.tag)):
                retained = QRetainedItem(item)
                geometry = retained.globalGeometry()
                state = retained.nativeState()
                targets[name] = {
                    "shown": retained.isVisible(),
                    "hovered": state.get("hovered"),
                    "bounds": (geometry.left(), geometry.top(), geometry.right(), geometry.bottom()),
                }
            sample = {
                "event": event, "kind": self.initial["kind"], "warm": self.prepared is not None,
                "pid": os.getpid(), "hwnd": self.native.hwnd,
                "enabled": bool(user32.IsWindowEnabled(self.native.hwnd)),
                "foreground": int(user32.GetForegroundWindow() or 0),
                "active": int(user32.GetActiveWindow() or 0),
                "focus": int(user32.GetFocus() or 0), "capture": int(user32.GetCapture() or 0),
                "mouse": point, "native_mouse": native_mouse, "targets": targets,
                "press_mouse": press_point,
                "rows": len(self.form.listbox.items),
                "selection_count": len(self.form.listbox.selected),
            }
            print("Selector input: " + json.dumps(sample), flush=True)
        except Exception:
            # Diagnostics must not interfere with native input or dialog startup.
            pass

    def _render_settled_frame(self):
        """Run queued layout callbacks before rendering one invisible frame."""
        started = time.perf_counter()
        self._drain_form_callbacks()
        self.view.drain()
        render_started = time.perf_counter()
        render_cpu_started = time.process_time()
        self.gui.renderFrame()
        from ..cursor import apply_tool_cursor
        apply_tool_cursor(self.view)
        self._startup_frames.append({"stage": self.stage,
                                     "callbacks_ms": (render_started - started) * 1000,
                                     "render_ms": (time.perf_counter() - render_started) * 1000,
                                      "render_cpu_ms": (time.process_time() - render_cpu_started) * 1000})

    def _drain_form_callbacks(self):
        """Apply the main viewport's input isolation to nested native dialogs."""
        callbacks = self.gui.callbackQueue()
        if native_background_input_blocked():
            self._drop_background_callbacks(callbacks)
            return
        for index, callback in enumerate(callbacks):
            if native_background_input_blocked():
                # Recheck each job: the preceding callback may have just opened
                # a selector. Discard the remaining batch (including stale Esc)
                # without starving the separate ChildView IPC/layout queue.
                self._drop_background_callbacks(callbacks[index:])
                return
            run_callback_jobs((callback,))

    def _drop_background_callbacks(self, callbacks):
        release_pointer_input()
        from DearUIQt.input_gate import native_modal_input_active
        if native_modal_input_active():
            return
        # Once the selector has actually closed, its mouse-up release guard
        # must not swallow a *new* Esc used to close the digitizer. This is a
        # keyboard command, not a click falling through the disappearing HWND.
        from DearUIQt.dialogs.base import _dispatch_escape
        if any(isinstance(job, (tuple, list)) and job
               and job[0] is _dispatch_escape for job in callbacks):
            self.view.after(0, _dispatch_escape)

    def show(self):
        self.desired_visible = True
        if not self.native.visible:
            self.native.set_visible(True)
        self.view._presentation_visible = bool(self.native.visible)
        from DearUIQt.input_gate import native_modal_input_active
        if not native_modal_input_active():
            if not self.native.is_foreground():
                self.native.activate()
            self._focus_form()
        self.emit("visibility", visible=True)

    def _hide_owned_dialogs(self):
        """Cancel child dialogs without shutting down this resident host's pool."""
        hwnd = getattr(self.native, "hwnd", None)
        if not hwnd:
            return
        from ..native.dialog_focus import cancel_owner_focus_return
        cancel_owner_focus_return(hwnd)
        suppressed = getattr(self.view, "_floating_focus_suppressed", False)
        self.view._floating_focus_suppressed = True
        try:
            for dialog in tuple(getattr(self.view, "_floating_dialogs", ())):
                if not dialog._closed and dialog._owner_hwnd == hwnd:
                    dialog.destroy()
        finally:
            self.view._floating_focus_suppressed = suppressed

    def hide(self, *, user_close=False):
        self.desired_visible = False
        self.view._presentation_visible = False
        # A retained parent remains alive, so its ordinary terminal destructor
        # will not clean up a selector. Do that before hiding the parent or its
        # still-visible child can orphan native modality and late focus work.
        self._hide_owned_dialogs()
        active = bool(self.native.visible and self.native.is_foreground())
        # Framework-style close ordering: when this owned viewport is the
        # foreground window, transfer activation to its already-enabled owner
        # while the dialog is still visible.  The owned HWND stays visually
        # above the owner until SW_HIDE, eliminating the desktop/other-window
        # frame that appears when focus is repaired only after the hide.
        if active and self.owner_hwnd:
            self.native.handoff_to_owner(self.owner_hwnd)
        if self.native.visible:
            self.native.set_visible(False)
        self.emit("visibility", visible=False, return_focus=active,
                  user_close=bool(user_close))

    def _resident_close(self):
        """Hide a retained modeless tool without destroying its DPG tree.

        Qt normally keeps a QWidget alive after close unless WA_DeleteOnClose
        (or deleteLater) is requested.  Keeping heavyweight tools resident
        removes process acquisition, form construction, texture upload and
        layout-settle work from every reopen.
        """
        if not self.retain_on_close or self.form is None:
            destroy = self._hard_destroy_form or getattr(self.form, "destroy", None)
            if callable(destroy):
                return destroy()
            return None
        try:
            cancel_pick = getattr(self.form, "_cancel_pick", None)
            if getattr(self.form, "_pick_mode", None) is not None and callable(cancel_pick):
                cancel_pick()
        except Exception:
            pass
        self.hide(user_close=True)
        return None

    def _drain_commands(self, preparing=False):
        for _ in range(16):
            try:
                message = self.incoming.get_nowait()
            except queue.Empty:
                break
            if not self._handle_command(message, preparing=preparing):
                return

    def _handle_command(self, message, preparing=False):
        command = message.get("command")
        if command == "shutdown":
            self.reusable = False
            destroy = self._hard_destroy_form or self.form.destroy
            destroy()
            return False
        if self.lease is not None and message.get("lease") != self.lease:
            return True
        if command in ("activate", "hide"):
            revision = message.get("visibility_revision")
            if type(revision) is int:
                if revision < getattr(self, "_visibility_revision", 0):
                    return True
                self._visibility_revision = revision
        if command == "close":
            # Parent/application teardown is terminal even for a retained tool.
            destroy = self._hard_destroy_form or self.form.destroy
            destroy()
            return False
        if command == "publish":
            self._publish_requested = True
        elif command == "publish_commit":
            self._commit_requested = True
        elif command in ("activate", "hide") and preparing:
            self.desired_visible = command == "activate"
        elif command == "activate":
            self.show()
        elif command == "hide":
            self.hide()
        elif command == "begin_dock_move" and self.initial.get("kind") in ("console_dock", "plot_dock"):
            self.native.begin_dock_move()
        else:
            deliver_command(self.form, command, message.get("args", []))
        return True

    def _wait_for_owner_handoff(self, timeout=.08):
        """Wait briefly for the parent to make the Win32 owner activatable.

        This is used only for child-driven closes (caption X/Escape/form
        self-destroy).  The native dialog remains visible while the parent
        balances its modal owner-disable reference.  Once acknowledged, SW_HIDE
        can hand foreground directly to the owner instead of briefly activating
        another desktop window.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if not pump_native_messages():
                self.reusable = False
                return False
            try:
                message = self.incoming.get(timeout=.005)
            except queue.Empty:
                continue
            command = str(message.get("command") or "")
            if self.lease is not None and message.get("lease") != self.lease:
                continue
            if command == "owner_handoff_ready":
                return True
            # The form is already closed and this process is exiting.  A second
            # close or stale UI command no longer has work to perform.
        return False

    def _wait_for_startup_flag(self, flag):
        """Wait for IPC while servicing native sends, without rendering."""
        deadline = time.monotonic() + PUBLISH_HANDSHAKE_TIMEOUT
        while self.form.winfo_exists() and not getattr(self, flag):
            if not pump_native_messages():
                self.reusable = False
                self.form.destroy()
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                message = self.incoming.get(timeout=min(.02, remaining))
            except queue.Empty:
                self.view.drain()
                continue
            if not self._handle_command(message, preparing=True):
                return False
            self.view.drain()
        return bool(getattr(self, flag) and self.form.winfo_exists())

    def _wait_for_publish(self):
        """Wait until the parent has registered the HWND/owner relationship.

        The viewport stays cloaked and non-activating during this handshake, so
        a modal dialog never becomes visible before the main WinUx owner has
        been disabled.  This removes the owner/dialog activation bounce that
        previously showed up as a one-frame main-window flash.
        """
        return self._wait_for_startup_flag("_publish_requested")

    def _wait_for_publish_commit(self):
        """Keep the staged HWND cloaked until the parent arms native modality.

        The child is already mapped, fully rendered and (for a visible dialog)
        foreground at this point.  Only now is it safe for the parent to disable
        the WinUx owner: disabling a *foreground* owner while no replacement is
        active is what caused the one-frame activation flash on dialog open.
        """
        return self._wait_for_startup_flag("_commit_requested")

    def _build(self):
        initial = self.initial
        self._lease_items_before = set(self.gui.itemSnapshot()) if self.reusable else set()
        self.stage = "configure-context"
        if self.prepared is None:
            configure_context(self.view)
        self.stage = "create-form:{}".format(initial.get("kind") or "unknown")
        self.form = create_form(initial["kind"], initial.get("payload") or {}, self.view, self.emit)
        self.reusable = bool(self.reusable and getattr(self.form, "REUSABLE_HOST", False))
        self.stage = "configure-form"
        # This form is the sole content of a dedicated native viewport.  Preserve
        # its last rendered pixels until SW_HIDE; deleting the DPG item first
        # exposes the viewport clear colour (black) during close hand-off.
        self.form._defer_visual_destroy = True
        if self.retain_on_close:
            # Preserve the real destructor for parent/application shutdown, then
            # route user-level close paths (X, Escape, form close button) to a
            # cheap hide.  The same form object is reused on the next activate.
            self._hard_destroy_form = self.form.destroy
            self.form.destroy = self._resident_close
        # One native viewport owns keyboard routing, independently of OS modality.
        self.form.modal = True
        form_item = QRetainedItem(self.form.tag)
        form_item.configure(modal=False, no_title_bar=True, no_move=True,
                            no_resize=True, no_collapse=True, pos=(0, 0), show=True)
        configured_minimum = form_item.nativeConfiguration().get("min_size")
        minimum = _normalize_size_pair(configured_minimum, (320, 180))
        default_preferred = (
            int(initial.get("width", 560)),
            max(int(initial.get("height", 360)), int(getattr(self.form, "height", 180) or 180)),
        )
        preferred = _normalize_size_pair(
            getattr(self.form, "preferred_size", None), default_preferred)
        width = max(preferred[0], minimum[0])
        height = preferred[1] + 40
        owner = int(initial.get("owner_hwnd") or 0)
        # A feature owns its window contract. Older WinUx parents can still
        # send the generic dialog defaults (no min/max buttons).
        resizable = bool(getattr(self.form, "NATIVE_RESIZABLE", initial.get("resizable", True)))
        caption_options = {
            "allow_minimize": bool(getattr(self.form, "ALLOW_MINIMIZE", initial.get("allow_minimize", False))),
            "allow_maximize": bool(getattr(self.form, "ALLOW_MAXIMIZE", initial.get("allow_maximize", False))),
        }
        self._layout_contract = (resizable, caption_options["allow_minimize"], caption_options["allow_maximize"])
        layout_spec = (initial["kind"], width, height, window_dpi(owner), *self._layout_contract)
        x, y = centered_position(window_rect(owner), (width, height), work_area(owner))
        options = dict(title=str(initial.get("title") or "WinUx Dialog"), width=width, height=height,
            x_pos=x, y_pos=y, min_width=minimum[0], min_height=minimum[1]+40,
            resizable=resizable, vsync=False)
        from ..appearance import viewport_icon_options
        if self.prepared is None:
            options.update(viewport_icon_options())
        self.stage = "create-or-configure-viewport"
        if self.prepared:
            # NativeViewport.center() supplies the final position after layout
            # settles. Avoid DPG's deferred move/mode changes here: on Windows
            # each extra SetWindowPos can trigger another swap-chain resize.
            options.pop("x_pos", None)
            options.pop("y_pos", None)
            current_viewport = self.gui.viewportSize()
            if current_viewport.width() == width:
                options.pop("width")
            if current_viewport.height() == height:
                options.pop("height")
            if options["resizable"] == self.native._resizable:
                options.pop("resizable")
            self.gui.configureViewport(**options)
            self.gui.setPrimaryWindow(self.prepared.blank, False)
        else:
            self.gui.createViewport(**options)
        self.gui.setPrimaryWindow(self.form.tag, True)
        if self.prepared:
            blank = self.prepared.blank
            if hasattr(blank, "delete"):
                blank.delete()
            else:
                QRetainedItem(blank).deleteNative()
        # DPG's primary-window preset resets scroll flags. Only the body/page
        # should scroll; the native client shell and pinned footer never do.
        form_item.configure(no_scrollbar=True, no_scroll_with_mouse=True)
        if self.prepared is None:
            self.gui.setup()
            with ViewportCreationGuard() as guard:
                self.gui.show()
            self.startup.extend(guard.events)
            self.native = NativeViewport(guard.hwnd, resizable)
        else:
            self.native._resizable = resizable
        self.native.configure(owner, **caption_options)
        self.view._native_hwnd = self.native.hwnd
        def show_error(_title, message):
            setter = getattr(self.form, "_set_status", None)
            if callable(setter):
                setter(str(message))
            else:
                self.form.status_text(str(message), error=True)
        self.view.show_error = show_error
        self.native.install_close_handler(self.view,
                                          getattr(self.form, "_close_from_native", self.form._close_from_escape),
                                          getattr(self.form, "native_character", None),
                                          dock_callback=(lambda action, position: self.emit(
                                              "dock_gesture", action=action, position=position))
                                              if initial.get("kind") in ("console_dock", "plot_dock") else None,
                                           pointer_callback=(self._browser_pointer_pressed
                                              if initial.get("kind") in ("local_folder", "local_file") else None))
        self.form.hide = self.hide
        self.form.show = self.form.lift = self.show
        # Theme/chrome, callbacks, initial RPC state and layout settle while
        # cloaked. No intermediate frame is composed on the desktop. A prewarmed
        # worker already has a live DPG context/swap-chain, so two settle frames
        # are sufficient; cold workers retain the conservative three-frame path.
        self.stage = "settle-layout"
        if self.prepared is not None and self.desired_visible:
            self.native.prepare_rendering()
        settle_frames = _settle_frame_count(self.prepared, layout_spec,
            bool(initial.get("fast_startup") and self.reusable and self.desired_visible and
                 not caption_options["allow_minimize"] and not caption_options["allow_maximize"]))
        for _ in range(settle_frames):
            self._drain_commands(preparing=True)
            if not self.form.winfo_exists():
                return
            self._render_settled_frame()
        if not resizable:
            for _ in range(3):
                overflow = QRetainedItem(self.form.content).verticalScrollMaximum()
                if overflow <= 0:
                    break
                current_height = self.gui.viewportSize().height()
                self.gui.setViewportHeight(current_height + int(overflow) + 8)
                self._render_settled_frame()
                self._render_settled_frame()
        self.stage = "center-native-window"
        anchor = (initial.get("payload") or {}).get("_dock_drag_anchor")
        if (initial.get("kind") not in ("console_dock", "plot_dock")
                or not self.native.position_for_tearoff(anchor)):
            self.native.center(owner)
        self.startup.append({"stage": "prepared", "cloaked": cloaked(self.native.hwnd),
                             "rect": window_rect(self.native.hwnd)})
        # Keep vsync disabled through the hidden preparation transaction.  The
        # viewport is not visible yet, so paying monitor intervals here only adds
        # latency and increases the window in which stale surfaces can be shown.
        self.stage = "prepared-notification" if self._publish_preauthorized else "prepared-handshake"
        self.emit("prepared", hwnd=self.native.hwnd, pid=os.getpid(),
                  publish_preauthorized=self._publish_preauthorized)
        if not self._wait_for_publish():
            if self.form.winfo_exists():
                raise RuntimeError(
                    "Timed out waiting for the parent to publish the floating dialog.")
            return
        # Consume any visibility command that raced with the publish ack while
        # still cloaked, then perform one render transaction: map under DWM cloak,
        # settle callbacks/layout, pre-activate, and only then remove the cloak.
        self._drain_commands(preparing=True)
        if not self.form.winfo_exists():
            return
        self.stage = "stage-publish"
        self.native.stage_publish(self.desired_visible)
        if self.desired_visible:
            self.stage = "publish-render"
            # ShowWindow happened while cloaked.  Render after mapping so GLFW's
            # swap chain contains the final dialog rather than its old blank frame.
            self._render_settled_frame()
            # A prewarmed swap-chain has already been presented while cloaked;
            # one mapped render is enough before the compositor barrier. Cold
            # starts keep a second render to avoid exposing an uninitialized
            # first swap on older GLFW/DPG builds.
            if self.prepared is None:
                self._render_settled_frame()
            # GLFW may apply deferred viewport style changes during the first
            # renders. Restore the feature caption contract before revealing it.
            self.stage = "publish-caption"
            self.native.configure(owner, **caption_options)
            # Transfer foreground while the WinUx owner is still enabled.  The
            # parent disables the owner only after receiving ``staged`` below, so
            # Windows never needs to activate an unrelated desktop window.
            self.stage = "publish-activate"
            self.native.activate()
            self.stage = "publish-compositor"
            self.native.flush_compositor()
        self.stage = "commit-handshake"
        self.emit("staged", hwnd=self.native.hwnd, pid=os.getpid(),
                  visible=bool(self.desired_visible),
                  foreground=bool(self.native.is_foreground()))
        if not self._wait_for_publish_commit():
            if self.form.winfo_exists():
                raise RuntimeError(
                    "Timed out waiting for the parent to commit the floating dialog.")
            return
        self.stage = "reveal-native-window"
        self.native.commit_publish(self.desired_visible)
        self.gui.configureViewport(vsync=True)
        self.startup.append({"stage": "published", "cloaked": cloaked(self.native.hwnd),
            "rect": window_rect(self.native.hwnd), "visible": self.desired_visible})
        if self.desired_visible:
            if not self.native.is_foreground():
                self.native.activate()
            self._focus_form()
        self._trace_browser_input("ready")
        self.stage = "ready-layout-diagnostics"
        self.emit(
            "ready",
            hwnd=self.native.hwnd,
            pid=os.getpid(),
            visible=bool(self.native.visible),
            layout=client_layout(self.form),
            startup=self.startup,
            reveal_count=self.native.reveal_count,
            timings=self.timings,
            startup_frames=self._startup_frames,
        )
        # Do not compete with the tool's first render/publish transaction.
        # Selector hosts never recursively prewarm children.
        if initial.get("kind") == "plotdigitizer":
            self.view.after(150, self._start_selector_prewarm)

    def run(self):
        if self.prepared is None:
            _RUNTIME_IO_POOL.start(self._read_commands)
            self.gui.createContext(manual_callbacks=True)
        clean = False
        try:
            self._build()
            while self.gui.isRunning() and self.form.winfo_exists():
                self._drain_commands()
                if not self.form.winfo_exists():
                    break
                self._drain_form_callbacks()
                self.view.drain()
                if self.native.visible:
                    self.gui.renderFrame()
                    self.view.mark_presented()
                    from ..cursor import apply_tool_cursor
                    apply_tool_cursor(self.view)
                else:
                    # Qt blocks the GUI thread in the platform event dispatcher
                    # while a hidden top-level has no paint work. IPC queues a
                    # native wake message, so activate/hide is observed
                    # immediately instead of waiting for a 12 ms polling sleep.
                    if not wait_native_messages(12):
                        break
            try:
                return_focus = bool(self.native and self.native.is_foreground())
                if return_focus and self.native and self.native.visible:
                    # Child-driven close needs a tiny two-phase hand-off because
                    # the modal owner-disable count lives in the parent process.
                    # Keep the *last rendered dialog frame* intact while waiting;
                    # never clear/delete its DPG content before SW_HIDE.
                    self.emit("closing", return_focus=True)
                    self._wait_for_owner_handoff()
                    if self.owner_hwnd:
                        self.native.handoff_to_owner(self.owner_hwnd)
                # Hide the native surface first.  All slower DPG item/context
                # teardown happens only after DWM can no longer compose it.
                if self.native and self.native.visible:
                    self.native.set_visible(False)
                finalize_visual = getattr(self.form, "_finalize_visual_destroy", None)
                if callable(finalize_visual):
                    finalize_visual()
                if self.reusable and QRetainedItem(self.form.tag).exists():
                    # A best-effort destructor may suppress a native deletion
                    # error. Never recycle a dirty widget tree.
                    self.reusable = False
                self.emit("closed", return_focus=return_focus)
                clean = True
            except OSError:
                pass
        finally:
            self.view._first_present_callbacks.clear()
            from .floating_dialog import close_floating_dialogs
            close_floating_dialogs(self.view)
            if self.reusable and clean:
                probe = getattr(self.form, "canReuseHost", None)
                try:
                    self.reusable = bool(probe()) if callable(probe) else bool(
                        getattr(self.form, "REUSABLE_HOST", False))
                except Exception:
                    self.reusable = False
            if self.reusable and clean:
                # QtDialog schedules deletion of external item-handler
                # registries on its own UI queue. Flush that closed lease's
                # immediate cleanup before replacing the scheduler.
                self.view.drain()
                from DearUIQt.input_gate import reset_pointer_input_gate
                reset_pointer_input_gate()
                # Browser/form themes are root resources, not descendants of
                # the deleted window. Keep texture/font caches, but release
                # themes allocated for this lease to prevent per-open growth.
                self.gui.releaseTopLevelItemsSince(
                    self._lease_items_before, item_type="mvAppItemType::mvTheme")
            if self.native:
                self.native.restore_close_handler()
            if self.reusable and clean:
                viewport_size = self.gui.viewportSize()
                layout_spec = (self.initial["kind"], viewport_size.width(),
                               viewport_size.height(), window_dpi(self.native.hwnd), *self._layout_contract)
                if self.prepared is None:
                    self.prepared = PreparedViewport.adopt(self)
                self.prepared.recycle(self.view, layout_spec)
                self.emit("idle", item_count=self.gui.itemCount())
            else:
                self.reusable = False
                self.gui.destroy()
