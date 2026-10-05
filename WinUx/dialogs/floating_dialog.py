"""Process-isolated Dear PyGui top-levels, free of the main viewport bounds.

DPG has one OS viewport per context. A separate child context is necessary for
real floating windows; creating another ``dpg.window`` cannot provide this.
Only UI state travels over authenticated localhost IPC. Application callbacks run on the
parent's existing UI queue.
"""
from __future__ import annotations

import os
import queue
from pathlib import Path
import subprocess
import secrets
import socket
import tempfile
import threading
import time

from ..platform.native_dialog_host import (
    find_process_window, _acquire_modal_owner, _release_modal_owner,
    handoff_owner_before_close, restore_owner_foreground,
)
from ..components.interaction_gate import (
    acquire_native_modal_input, release_native_modal_input,
    register_native_pointer_surface, unregister_native_pointer_surface,
)
from ..services.floating_protocol import encode_message, read_messages
from ..runtime.command_queue import LatestCommandQueue
from ..runtime.child_processes import (
    register_child_process, unregister_child_process,
)
from ..platform.dialog_focus import (
    foreground_hwnd as _foreground_hwnd, window_state as _window_state,
    owner_has_keyboard_focus as _owner_has_keyboard_focus, queue_owner_focus,
    cancel_owner_focus_return,
)
from ..platform.floating_viewport import set_native_window_visible


def close_floating_dialogs(view):
    """Close all registered dialogs before the application's UI queue stops."""
    view._floating_focus_suppressed = True
    pool = getattr(view, "_dialog_prewarm_pool", None)
    if pool is not None:
        pool.close()
    for dialog in tuple(getattr(view, "_floating_dialogs", ())):
        dialog.destroy(wait=False)


def floating_dialog_command(script):
    command = os.environ.get("WINUX_ABAQUS_COMMAND") or os.environ.get("WIXUX_ABAQUS_COMMAND") or "abaqus"
    args = [command, "python", str(script)]
    if os.name == "nt":
        # Abaqus is normally a .bat wrapper; IPC does not depend on its stdio.
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(args)]
    return args


class FloatingDialogController:
    NATIVE_WINDOW = True
    FLOATABLE = True
    STARTUP_TIMEOUT = 25.0

    def __init__(self, view, kind, title, payload=None, width=560, height=360,
                 modal=False, resizable=True, visible=True, owner_hwnd=None):
        self.view, self.modal = view, bool(modal)
        self._requested_at = time.perf_counter()
        self.title = title
        self._closed = False
        self._finalized = False
        self._ready = False
        self._native_prepared = False
        self._hwnd = None
        self._owner_acquired = False
        self._owner_hwnd = int(owner_hwnd if owner_hwnd is not None else find_process_window("WinUX") or 0)
        self._visible = bool(visible)
        self._native_visible = False
        self._owned_dialogs = []
        self._focus_return_generation = 0
        try:
            owner_live, owner_visible, _owner_enabled = _window_state(self._owner_hwnd)
            self._owner_was_visible = bool(owner_live and owner_visible)
        except Exception:
            self._owner_was_visible = False
        self._close_return_focus = False
        # Explicit owner return remains available for workflows such as a
        # successful SSH Login. Ordinary closes use the foreground state that
        # was captured immediately before their native HWND is hidden.
        self._explicit_owner_return = False
        registry = getattr(view, "_floating_dialogs", None)
        if registry is None:
            registry = view._floating_dialogs = set()
        registry.add(self)
        self._write_lock = threading.Lock()
        self._connection = None
        self._outgoing = LatestCommandQueue(maxsize=256)
        self._connection_ready = threading.Event()
        self._child_pid = None
        self._ipc_stage = "waiting for child"
        pool = getattr(view, "_dialog_prewarm_pool", None)
        # Every floating dialog, including SSH Login, uses the same Dear PyGui
        # runtime and can therefore reuse a prepared DPG viewport.
        self._prepared_worker = pool.claim() if pool is not None else None
        self._from_prewarm = self._prepared_worker is not None
        if self._from_prewarm:
            self._listener = self._prepared_worker.listener
            self._token = self._prepared_worker.token
        else:
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listener.bind(("127.0.0.1", 0))
            self._listener.listen(1)
            self._listener.settimeout(self.STARTUP_TIMEOUT)
            self._token = secrets.token_hex(32)
        self._process = None
        self._startup_timer = None
        if self.modal and self._visible:
            acquire_native_modal_input(self)
        script = Path(__file__).resolve().parents[1] / "services" / "floating_dialog_process.py"
        log_dir = Path(tempfile.gettempdir()) / "WinUx" / "logs"
        self.log_path = str(log_dir / "floating_dialog_{}.log".format(kind))
        try:
            if self._from_prewarm:
                self._process = self._prepared_worker.process
                self.log_path = self._prepared_worker.log_path
            else:
                log_dir.mkdir(parents=True, exist_ok=True)
                environment = os.environ.copy()
                environment["WINUX_FLOAT_DIALOG_PORT"] = str(self._listener.getsockname()[1])
                environment["WINUX_FLOAT_DIALOG_TOKEN"] = self._token
                environment.pop("WINUX_FLOAT_DIALOG_PREWARM", None)
                with open(self.log_path, "ab", buffering=0) as log:
                    self._process = subprocess.Popen(floating_dialog_command(script),
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        cwd=str(script.parent), env=environment,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    register_child_process(self._process, "floating-dialog")
            self.post("init", kind=kind, title=title, payload=payload or {},
                      width=width, height=height, resizable=resizable,
                      owner_hwnd=self._owner_hwnd, visible=self._visible, modal=self.modal)
        except Exception:
            self._finish()
            raise
        threading.Thread(target=self._read_events, name="winux-floating-dialog-ipc", daemon=True).start()
        threading.Thread(target=self._write_commands, name="winux-floating-dialog-writer", daemon=True).start()
        self._startup_timer = threading.Timer(self.STARTUP_TIMEOUT,
            lambda: self.view.after(0, self._check_startup))
        self._startup_timer.daemon = True
        self._startup_timer.start()

    def post(self, command, *args, **kwargs):
        if self._closed:
            return False
        message = {"command": command, "args": args, **kwargs}
        try:
            self._outgoing.put_nowait(message)
            return True
        except queue.Full:
            self.view.after(0, self._failed, "The floating dialog command queue is full.")
            return False

    def _write_commands(self):
        self._connection_ready.wait()
        try:
            while not self._closed:
                try:
                    message = self._outgoing.get(timeout=.2)
                except queue.Empty:
                    continue
                # Encoding large ODB tables/report payloads never runs on the
                # main UI thread. Typed data stays intact across the boundary.
                self._connection.sendall(encode_message(message))
        except (OSError, ValueError, TypeError) as exc:
            self.view.after(0, self._failed, "Floating dialog command failed: {}".format(exc))

    def post_latest(self, command, *args, **kwargs):
        if self._closed:
            return False
        message = {"command": command, "args": args, **kwargs}
        try:
            self._outgoing.put_latest(command, message)
            return True
        except queue.Full:
            self.view.after(0, self._failed, "The floating dialog command queue is full.")
            return False

    def _read_events(self):
        connection = None
        try:
            prepared = getattr(self, "_prepared_worker", None)
            if prepared is not None:
                connection, messages = prepared.connection, prepared.messages
            else:
                connection, _ = self._listener.accept()
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._ipc_stage = "child connected"
                connection.settimeout(self.STARTUP_TIMEOUT)
                messages = read_messages(connection)
                hello = next(messages)
                self._ipc_stage = "handshake received"
                if not secrets.compare_digest(str(hello.get("token", "")), self._token):
                    raise ValueError("Invalid floating-dialog handshake.")
                connection.settimeout(None)
            with self._write_lock:
                if self._closed:
                    return
                self._connection = connection
                self._connection_ready.set()
            self._ipc_stage = "connected to dialog host"
            for message in messages:
                self._ipc_stage = "event received: {}".format(message.get("event"))
                if isinstance(message, dict) and message.get("event"):
                    self.view.after(0, self._deliver_event, message)
        except (OSError, ValueError, StopIteration) as exc:
            self.view.after(0, self._failed, "Floating dialog IPC failed: {}".format(exc))
        finally:
            if connection:
                connection.close()
            self._listener.close()
            self.view.after(0, self._process_exited)

    def _deliver_event(self, message):
        if self._closed:
            return
        event = message.get("event")
        if event == "prepared":
            # Register the foreign HWND while it is still DWM-cloaked.  The DPG
            # application-input gate was acquired synchronously in __init__, but
            # deliberately do *not* disable the native WinUx owner yet.  Disabling
            # the current foreground owner before a replacement HWND is active can
            # make Windows activate another desktop window for one frame.
            self._accept_native_hwnd(message)
            self._native_prepared = True
            if self._visible and self.modal:
                acquire_native_modal_input(self)
            self.post("publish")
        elif event == "staged":
            # The child is now mapped/rendered/activated but still DWM-cloaked.
            # Native owner modality can be armed without an activation bounce,
            # then the child is allowed to remove its cloak atomically.
            self._accept_native_hwnd(message)
            if bool(message.get("visible", self._visible)) and self.modal:
                if self._owner_hwnd and not self._owner_acquired:
                    self._owner_acquired = _acquire_modal_owner(self._owner_hwnd)
            self.post("publish_commit")
        elif event == "ready":
            if self._ready:
                return
            self._ready = True
            self._open_elapsed_ms = max(0.0, time.perf_counter()-getattr(self, "_requested_at", time.perf_counter())) * 1000
            from ..diagnostics import log_event
            log_event("Dialog ready title={} source={} elapsed={:.1f}ms".format(
                getattr(self, "title", type(self).__name__), "warm" if getattr(self, "_from_prewarm", False) else "cold", self._open_elapsed_ms))
            self._client_layout = message.get("layout") or {}
            self._startup_layout = message.get("startup") or []
            self._initial_reveal_count = int(message.get("reveal_count") or 0)
            self._child_pid = int(message.get("pid") or 0) or self._child_pid
            if self._startup_timer:
                self._startup_timer.cancel()
            self._accept_native_hwnd(message)
            self._confirm_visibility(
                bool(message.get("visible", self._visible)),
                return_focus=False,
            )
            # New runtimes have already published in response to the explicit
            # ``publish`` handshake.  Keep compatibility with an older child
            # process that may send only ``ready``.
            if not getattr(self, "_native_prepared", False):
                self.post("activate" if self._visible else "hide")
        elif event == "visibility":
            self._confirm_visibility(
                bool(message.get("visible")),
                return_focus=bool(message.get("return_focus")),
            )
        elif event == "closing":
            # Child-driven X/Escape/form closes reach this point while the
            # foreign HWND is still visible and still owns foreground.  Make
            # the Win32 owner activation-eligible before acknowledging the
            # child; the child will not execute SW_HIDE until this ack arrives.
            # Keep the DPG modal-input gate held until the final ``closed``
            # event so interaction cannot fall through during the hand-off.
            self._close_return_focus = bool(message.get("return_focus"))
            if self._close_return_focus and self._owner_acquired:
                self._owner_acquired = False
                _release_modal_owner(self._owner_hwnd, restore_focus=False)
            self.post("owner_handoff_ready")
        elif event == "closed":
            self._close_return_focus = bool(
                self._close_return_focus or message.get("return_focus"))
            self._finish()
        elif event == "error":
            self._failed(str(message.get("message") or "Could not open floating dialog."))
        else:
            self.handle_event(event, message)

    def _accept_native_hwnd(self, message):
        hwnd = int(message.get("hwnd") or 0) or None
        child_pid = int(message.get("pid") or 0) or None
        if child_pid:
            self._child_pid = child_pid
        if not hwnd:
            return False
        # Never accept the main WinUx viewport as the floating child HWND.
        # A stale/ambiguous window lookup must not allow dialog teardown to
        # execute SW_HIDE against the application owner itself.
        if self._owner_hwnd and int(hwnd) == int(self._owner_hwnd):
            return False
        if self._hwnd == hwnd:
            return True
        if self._hwnd:
            unregister_native_pointer_surface(self._hwnd)
        self._hwnd = hwnd
        register_native_pointer_surface(hwnd)
        return True

    def handle_event(self, event, message):
        pass

    def _check_startup(self):
        if not self._closed and not self._ready:
            self._failed("The floating dialog did not become ready within {} seconds ({}).".format(self.STARTUP_TIMEOUT, self._ipc_stage))

    def _process_exited(self):
        if not self._closed:
            self._failed("The floating dialog process exited unexpectedly.")

    def _failed(self, message):
        if self._closed:
            return
        self.destroy()
        callback = getattr(self.view, "show_error", None)
        if callable(callback):
            self.view.after(0, callback, self.title, message + "\n\nLog: " + self.log_path)

    def _finish(self):
        if self._finalized:
            return
        # Capture foreground ownership *before* hiding the child HWND. Result
        # dialogs can be finalized by the parent as soon as their IPC result
        # arrives, before the child process has time to send its final ``closed``
        # event. Once SW_HIDE runs, GetForegroundWindow may transiently report
        # the shell instead of the dialog and the information is lost.
        return_focus = bool(getattr(self, "_close_return_focus", False))
        if self._hwnd:
            try:
                return_focus = return_focus or int(_foreground_hwnd() or 0) == int(self._hwnd)
            except Exception:
                pass

        # Seamless owned-window hand-off: a disabled owner is *not* eligible
        # for Win32's normal activation transfer when the foreground child is
        # hidden/destroyed.  If we hide first and enable later, Windows briefly
        # activates another desktop window and our deferred foreground repair
        # becomes visible as a one-frame flash.
        #
        # Re-enable only the native owner immediately before the child HWND
        # disappears, while keeping WinUx's DPG modal-input gate held.  The
        # dialog therefore remains logically modal, but Windows can transfer
        # foreground/Z-order directly from the owned child to its owner in the
        # same native transition.  Deferred focus repair below is only fallback.
        if return_focus and self._owner_acquired:
            self._owner_acquired = False
            _release_modal_owner(self._owner_hwnd, restore_focus=False)

        # Do the activation hand-off while the owned dialog is still visible.
        # SetForegroundWindow after SW_HIDE is inherently racy: Windows may
        # activate Explorer/Chrome/etc. for one composition frame, which is the
        # visible "blink" reported by users.  Native frameworks transfer the
        # foreground slot first and only then destroy/hide the owned dialog.
        preclose_handoff = False
        if (return_focus and self._hwnd and getattr(self, "_native_visible", False)
                and int(self._hwnd) != int(self._owner_hwnd or 0)):
            preclose_handoff = handoff_owner_before_close(
                self._owner_hwnd, self._hwnd)

        if (self._hwnd and getattr(self, "_native_visible", False)
                and int(self._hwnd) != int(self._owner_hwnd or 0)):
            set_native_window_visible(self._hwnd, False)
            self._native_visible = False
        self._closed = self._finalized = True
        if self._startup_timer:
            self._startup_timer.cancel()
        if self._hwnd:
            unregister_native_pointer_surface(self._hwnd)
        if self._owner_acquired:
            self._owner_acquired = False
            _release_modal_owner(self._owner_hwnd, restore_focus=False)
        if self.modal:
            release_native_modal_input(self)

        if return_focus:
            try:
                owner_already_foreground = (
                    int(_foreground_hwnd() or 0) == int(self._owner_hwnd or 0))
            except Exception:
                owner_already_foreground = False
            # Deferred Z-order repair is now only a failure fallback.  In the
            # normal path ``preclose_handoff`` already made the owner foreground
            # before the child disappeared, so there is no second activation.
            if not preclose_handoff and not owner_already_foreground:
                self._queue_owner_focus(force=True)
        for child in tuple(getattr(self, "_owned_dialogs", ())):
            child.destroy()
        registry = getattr(self.view, "_floating_dialogs", None)
        if registry is not None:
            registry.discard(self)
        if hasattr(self, "_connection_ready"):
            self._connection_ready.set()
        if self._connection is not None:
            try:
                self._connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._connection.close()
        self._listener.close()

    def winfo_exists(self):
        return not self._closed

    def show(self):
        if self._closed:
            return False
        self._set_visible(True)
        return self.post("activate")

    def hide(self):
        if self._closed:
            return False
        try:
            return_focus = bool(
                self._hwnd and int(_foreground_hwnd() or 0) == int(self._hwnd))
        except Exception:
            return_focus = False

        # Arm the Win32 owner for its normal owned-popup activation hand-off
        # *before* the child process executes SW_HIDE.  Keep the application
        # input gate until the child confirms hidden so no click can fall
        # through to WinUx during this very short interval.
        if return_focus and self._owner_acquired:
            self._owner_acquired = False
            _release_modal_owner(self._owner_hwnd, restore_focus=False)
        self._set_visible(False, return_focus=return_focus)
        return self.post("hide")

    def _set_visible(self, visible, return_focus=False):
        """Set requested visibility without releasing a still-visible modal.

        Hiding is asynchronous because the child viewport lives in another
        process.  The native Win32 owner may be re-enabled just before a
        foreground child is hidden so Windows can perform an atomic owned-window
        activation hand-off.  WinUx's DPG input gate remains held until
        ``_confirm_visibility(False)``, so logical modality is never released
        early and mouse input cannot fall through the disappearing dialog.
        """
        self._visible = bool(visible)
        if self._visible:
            # A newly shown sibling invalidates any deferred focus restoration
            # left behind by a dialog that just closed on the same owner.
            cancel_owner_focus_return(self._owner_hwnd)
            self._focus_return_generation = getattr(self, "_focus_return_generation", 0) + 1
            try:
                owner_live, owner_visible, _owner_enabled = _window_state(self._owner_hwnd)
                if owner_live:
                    self._owner_was_visible = bool(owner_visible)
            except Exception:
                pass
            if self.modal:
                acquire_native_modal_input(self)
                if self._hwnd and self._owner_hwnd and not self._owner_acquired:
                    self._owner_acquired = _acquire_modal_owner(self._owner_hwnd)
        else:
            # If no child HWND has ever become visible there is nothing to wait
            # for; otherwise the child ``visibility=False`` event owns release.
            if not self._hwnd or not getattr(self, "_native_visible", False):
                self._release_visibility_guards(
                    queue_focus=bool(return_focus),
                    force_focus=bool(return_focus),
                )

    def _confirm_visibility(self, visible, return_focus=False):
        """Apply child-confirmed native visibility on the parent UI thread."""
        visible = bool(visible)
        was_visible = bool(getattr(self, "_native_visible", False))
        self._native_visible = visible
        if visible:
            if self._visible:
                # Ensure a modal cannot be visible while its owner is enabled,
                # including recovery from a late/out-of-order child event.
                self._set_visible(True)
            else:
                # A stale show raced with a newer hide request. Keep modality
                # until the child acknowledges the corrective hide.
                self.post("hide")
            return

        # If a newer show request already exists, keep the owner disabled during
        # the short hidden interval and let the next visible confirmation finish
        # the transition without flashing the main window.
        if self._visible:
            return
        self._release_visibility_guards(
            queue_focus=bool(was_visible or return_focus),
            force_focus=bool(return_focus),
        )

    def _release_visibility_guards(self, queue_focus=False, force_focus=False):
        if self.modal:
            if self._owner_acquired:
                self._owner_acquired = False
                _release_modal_owner(self._owner_hwnd, restore_focus=False)
            release_native_modal_input(self)
        if queue_focus:
            self._queue_owner_focus(force=bool(force_focus))

    def _queue_owner_focus(self, force=False):
        queue_owner_focus(
            self,
            bool(force or getattr(self, "_explicit_owner_return", False)),
            _foreground_hwnd,
            _window_state,
            restore_owner_foreground,
            _owner_has_keyboard_focus,
        )

    def own_dialog(self, dialog):
        dialog._logical_parent = self
        self._owned_dialogs.append(dialog)
        return dialog

    lift = show
    activate = show
    focus = show

    def grab_release(self):
        # Balanced by _finish; do not enable the main window while still open.
        return None

    def destroy(self, **kwargs):
        if self._closed:
            return
        # A successful modal workflow may explicitly request focus to return to
        # WinUx.  Capture whether the dialog/owner still owns the user's focus
        # *before* hiding the child HWND.  This lets us repair the normal Windows
        # foreground transition after close without stealing focus when the user
        # deliberately switched to another application during a slow operation.
        if bool(kwargs.get("return_focus", False)):
            try:
                foreground = int(_foreground_hwnd() or 0)
            except Exception:
                foreground = 0
            self._explicit_owner_return = foreground in (
                0, int(self._hwnd or 0), int(self._owner_hwnd or 0)
            )
        # Socket EOF is a close request in the host. It also interrupts a writer
        # blocked on a large payload, without waiting on the main render thread.
        self._finish()
        process = self._process
        def reap():
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    process.terminate()
                process.wait(timeout=5)
            finally:
                unregister_child_process(process)
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
        if process is not None:
            threading.Thread(target=reap, name="winux-floating-dialog-cleanup", daemon=True).start()
