"""Process-isolated Dear PyGui top-levels, free of the main viewport bounds.

DPG has one OS viewport per context. A separate child context is necessary for
real floating windows; creating another ``dpg.window`` cannot provide this.
Only UI state travels over authenticated localhost IPC. Application callbacks run on the
parent's existing UI queue.
"""
from __future__ import annotations

import queue
import socket
from pathlib import Path
import threading
import time
from datetime import datetime

from ..native.native_dialog_host import (
    find_process_window, _acquire_modal_owner, _release_modal_owner,
    handoff_owner_before_close, restore_owner_foreground,
)
from DearUIQt.input_gate import (
    acquire_native_modal_input, release_native_modal_input,
    register_native_pointer_surface, unregister_native_pointer_surface,
)
from ...services.floating_protocol import encode_message
from ...runtime.command_queue import LatestCommandQueue
from ..native.dialog_focus import (
    foreground_hwnd as _foreground_hwnd, window_state as _window_state,
    owner_has_keyboard_focus as _owner_has_keyboard_focus, queue_owner_focus,
    cancel_owner_focus_return, closing_dialog_hwnds,
)
from ..native.floating_viewport import set_native_window_visible, wake_native_window
from DearUIQt.core import QThreadPool
from .process import floating_dialog_command, floating_dialog_log_path
from .host import dialog_host_manager


_DIALOG_IPC_POOL = QThreadPool(maxThreadCount=32, maxPending=256, name="dialog-ipc")


def close_floating_dialogs(view):
    """Close all registered dialogs before the application's UI queue stops."""
    # Main-context QDialogs must be terminally deleted before DPG teardown.
    # Their ordinary Close buttons only hide them, matching QWidget lifetime.
    try:
        from .inprocess_dialog import close_inprocess_dialogs
        close_inprocess_dialogs(view)
    except Exception:
        pass
    view._floating_focus_suppressed = True
    manager = getattr(view, "_dialog_host_manager", None)
    if manager is not None:
        manager.close()
    else:
        pool = (getattr(view, "_dialog_host_pool", None)
                or getattr(view, "_dialog_prewarm_pool", None))
        if pool is not None:
            pool.close()
    for dialog in tuple(getattr(view, "_floating_dialogs", ())):
        dialog.destroy(wait=False)



class FloatingDialogController:
    NATIVE_WINDOW = True
    FLOATABLE = True
    STARTUP_TIMEOUT = 25.0
    WARM_STARTUP_TIMEOUT = 5.0

    def __init__(self, view, kind, title, payload=None, width=560, height=360,
                  modal=False, resizable=True, visible=True, owner_hwnd=None,
                  allow_minimize=False, allow_maximize=False, fast_startup=True,
                  retain_on_close=False, fresh_host=False):
        self.view, self.modal = view, bool(modal)
        self._kind = str(kind)
        self._ipc_retry_count = 0
        self._transport_generation = 0
        self._initial_message = None
        # Qt-style retained top-levels: close() may hide the native window while
        # the controller/widget object remains alive.  This is opt-in because
        # result/progress dialogs rely on destruction to complete their result.
        self._retain_on_close = bool(retain_on_close)
        self._resident_generation = 0
        self._requested_at = time.perf_counter()
        self.title = title
        self._closed = False
        self._finalized = False
        self._ready = False
        self._native_prepared = False
        self._hwnd = None
        self._owner_acquired = False
        if owner_hwnd is None:
            # The main view already has a robust HWND resolver/cache.  Reuse it
            # instead of independently enumerating process windows for every
            # dialog; choosing a helper top-level here breaks the owner chain
            # and is enough to leave the real WinUx viewport behind other apps.
            resolver = getattr(view, "_find_main_viewport_hwnd", None)
            resolved_owner = resolver() if callable(resolver) else None
            owner_hwnd = resolved_owner or find_process_window("WinUX") or 0
        self._owner_hwnd = int(owner_hwnd or 0)
        self._visible = bool(visible)
        self._visibility_revision = 0
        self._native_visible = False
        self._first_present_callbacks = []
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
        self._host_manager = dialog_host_manager(view)
        self._prewarm_pool = self._host_manager.pool  # compatibility facade
        self._prewarm_refill_requested = False
        self._host_lease = None
        try:
            self._host_lease = self._host_manager.acquire(
                kind, self.STARTUP_TIMEOUT, fresh=bool(fresh_host))
        except Exception:
            registry.discard(self)
            raise
        lease = self._host_lease
        # Compatibility mirrors for older integrations/tests. Process/host
        # lifecycle decisions below go through QDialogLease only.
        self._prepared_worker = lease.host
        self._from_prewarm = lease.from_prewarm
        self._from_reused_host = lease.reused
        self._lease = lease.lease
        self._reuse_host = lease.reusable
        self._host_returned = False
        self._recycle_generation = 0
        self._startup_generation = 0
        self._listener = lease.listener
        self._token = lease.token
        self._process = lease.process
        self.log_path = lease.log_path
        try:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.log_path).touch(exist_ok=True)
            self.post("init", kind=kind, title=title, payload=payload or {},
                      lease=self._lease, reuse_host=self._reuse_host,
                      fast_startup=bool(fast_startup),
                      authorized_hwnd=(lease.hwnd if self._from_prewarm and fast_startup else None),
                      width=width, height=height, resizable=resizable,
                      allow_minimize=bool(allow_minimize), allow_maximize=bool(allow_maximize),
                      owner_hwnd=self._owner_hwnd, visible=self._visible, modal=self.modal,
                      retain_on_close=self._retain_on_close)
        except Exception:
            lease.retire()
            self._finish()
            raise
        if self.modal and self._visible:
            # Logical modality starts with the request, not a later IPC event.
            # Otherwise Esc/click callbacks can close the disabled tool behind
            # a selector during its cold/prewarm startup gap. Native owner
            # disabling still waits for the staged window to avoid focus flash.
            acquire_native_modal_input(self)
        _DIALOG_IPC_POOL.start(self._read_events)
        _DIALOG_IPC_POOL.start(self._write_commands, self._transport_generation)
        self._startup_generation += 1
        generation = self._startup_generation
        self.view.after(int(self.STARTUP_TIMEOUT * 1000), self._check_startup, generation)

    def post(self, command, *args, **kwargs):
        if self._closed:
            return False
        message = {"command": command, "args": args, **kwargs}
        if command in ("activate", "hide"):
            self._visibility_revision = getattr(self, "_visibility_revision", 0) + 1
            message["visibility_revision"] = self._visibility_revision
        if getattr(self, "_lease", None) is not None:
            message["lease"] = self._lease
        if command == "init":
            # Keep an independent copy: the writer consumes the queued init
            # before a stale warm host can fail or stop responding.
            self._initial_message = dict(message)
        try:
            self._outgoing.put_nowait(message)
            return True
        except queue.Full:
            self.view.after(0, self._failed, "The floating dialog command queue is full.")
            return False

    def _write_commands(self, generation=None):
        generation = getattr(self, "_transport_generation", 0) if generation is None else generation
        ready = self._connection_ready
        ready.wait()
        connection = self._connection
        if connection is None or generation != getattr(self, "_transport_generation", 0):
            # Closing before the handshake also wakes this event. There is no
            # channel to write to, and cancellation is not another IPC failure.
            return
        outgoing = self._outgoing
        try:
            while True:
                if generation != getattr(self, "_transport_generation", 0):
                    return
                try:
                    message = outgoing.get(timeout=.2)
                except queue.Empty:
                    if self._closed:
                        return
                    continue
                if generation != getattr(self, "_transport_generation", 0):
                    return
                if self._closed and message.get("command") != "close":
                    continue
                # Encoding large ODB tables/report payloads never runs on the
                # main UI thread. Typed data stays intact across the boundary.
                connection.sendall(encode_message(message))
                if message.get("command") == "close":
                    wake_native_window(self._hwnd)
                    return
        except (OSError, ValueError, TypeError) as exc:
            self.view.after(0, self._command_failed, generation, str(exc))

    def _command_failed(self, generation, message):
        if generation == getattr(self, "_transport_generation", 0):
            self._failed("Floating dialog command failed: {}".format(message))

    def post_latest(self, command, *args, **kwargs):
        if self._closed:
            return False
        message = {"command": command, "args": args, **kwargs}
        if getattr(self, "_lease", None) is not None:
            message["lease"] = self._lease
        try:
            self._outgoing.put_latest(command, message)
            return True
        except queue.Full:
            self.view.after(0, self._failed, "The floating dialog command queue is full.")
            return False

    def _retry_startup_with_fresh_host(self, exc):
        """Replace one failed startup transport and replay its init command.

        This also isolates a native renderer process that exits before ready.
        Explicit Python/form error events are still reported, never retried.
        """
        if self._closed or self._ready or self._ipc_retry_count >= 1:
            return False
        self._ipc_retry_count += 1
        if isinstance(exc, socket.timeout):
            self._append_failure_log(
                "Warm host stopped responding; retrying once in a fresh host.",
                stage=self._ipc_stage)
        # Invalidate the old writer before closing its socket. It must neither
        # consume the replacement init nor report a late failure on the new UI.
        self._transport_generation += 1
        pending = self._outgoing
        self._outgoing = LatestCommandQueue(maxsize=256)
        self._connection_ready.set()
        self._connection_ready = threading.Event()
        old = self._host_lease
        try:
            old.close_channel()
        except Exception:
            pass
        try:
            old.retire()
        except Exception:
            pass
        if self._hwnd:
            unregister_native_pointer_surface(self._hwnd)
        if self._owner_acquired:
            self._owner_acquired = False
            _release_modal_owner(self._owner_hwnd, restore_focus=False)
        self._hwnd = None
        self._native_prepared = False
        self._native_visible = False
        try:
            lease = self._host_manager.acquire(
                self._kind, self.STARTUP_TIMEOUT, fresh=True)
        except Exception:
            return False
        self._host_lease = lease
        self._prepared_worker = lease.host
        self._from_prewarm = False
        self._from_reused_host = lease.reused
        self._lease = lease.lease
        self._reuse_host = lease.reusable
        self._listener = lease.listener
        self._token = lease.token
        self._process = lease.process
        self.log_path = lease.log_path
        self._connection = None
        self._ipc_stage = "retrying with fresh dialog host"

        def rewrite(message):
            if isinstance(message, dict):
                message["lease"] = self._lease
                if message.get("command") == "init":
                    message["authorized_hwnd"] = None
                    message["reuse_host"] = self._reuse_host
        initial = dict(self._initial_message)
        rewrite(initial)
        self._initial_message = initial
        self._outgoing.put_nowait(initial)
        while True:
            try:
                message = pending.get_nowait()
            except queue.Empty:
                break
            if message.get("command") != "init":
                rewrite(message)
                self._outgoing.put_nowait(message)
        self._startup_generation += 1
        self.view.after(int(self.STARTUP_TIMEOUT * 1000), self._check_startup, self._startup_generation)
        _DIALOG_IPC_POOL.start(self._write_commands, self._transport_generation)
        from ...diagnostics import log_event
        log_event("Dialog startup host retry title={} error={}".format(
            self.title, exc))
        return True

    def _read_events(self):
        connection = None
        returned = False
        try:
            while True:
                startup_complete = startup_error = False
                try:
                    connection, messages = self._host_lease.open_messages(self.STARTUP_TIMEOUT)
                    # A live socket does not imply a responsive graphics/UI
                    # thread. A quiet warm host is expendable; retry once with
                    # a fresh Abaqus child rather than waiting 25 seconds.
                    connection.settimeout(self.WARM_STARTUP_TIMEOUT if self._from_prewarm else None)
                    self._ipc_stage = "handshake received"
                    with self._write_lock:
                        if self._closed:
                            return
                        self._connection = connection
                        self._connection_ready.set()
                    self._ipc_stage = "connected to dialog host"
                    for message in messages:
                        if self._lease is not None and message.get("lease") != self._lease:
                            continue
                        if message.get("event") == "ready":
                            startup_complete = True
                            connection.settimeout(None)
                        elif message.get("event") == "error":
                            startup_error = True
                        if self._reuse_host and message.get("event") == "idle":
                            returned = True
                            self.view.after(0, self._return_host, message)
                            break
                        self._ipc_stage = "event received: {}".format(message.get("event"))
                        if isinstance(message, dict) and message.get("event"):
                            self.view.after(0, self._deliver_event, message)
                    if (not returned and not self._closed and not self._ready
                            and not startup_complete and not startup_error):
                        raise RuntimeError("Dialog host disconnected during startup")
                    break
                except (OSError, ValueError, RuntimeError, StopIteration) as exc:
                    if not startup_complete and not startup_error and self._retry_startup_with_fresh_host(exc):
                        connection = None
                        continue
                    raise
        except (OSError, ValueError, RuntimeError, StopIteration) as exc:
            self.view.after(0, self._failed, "Floating dialog IPC failed: {}".format(exc))
        finally:
            if not returned and self._host_lease is not None:
                self._host_lease.close_channel()
            elif self._host_lease is not None:
                self._host_lease.close_listener()
            if not returned:
                if self._host_lease is not None:
                    self._host_lease.retire()
                self.view.after(0, self._process_exited)

    def _return_host(self, message):
        if self._host_returned:
            return
        # 'closed' is queued before 'idle'. Release native modality/ownership
        # before making this HWND available to the next controller.
        self._finish()
        self._host_returned = True
        self._native_visible = False
        self._idle_item_count = int(message.get("item_count") or 0)
        self._recycle_generation += 1
        self._host_lease.release()
        self._close_completed()

    def _deliver_event(self, message):
        if self._closed:
            return
        # UI deliveries queued by the retired transport can arrive after a
        # replacement lease has connected. Never publish/close its predecessor.
        if "lease" in message and message["lease"] != getattr(self, "_lease", None):
            return
        event = message.get("event")
        if event == "startup_progress":
            self._ipc_stage = "child startup: {}".format(message.get("stage") or "unknown")
            return
        if event == "visibility" and self._visibility_event_stale(message):
            return
        if event in ("prepared", "ready") and "reuse_host" in message:
            self._reuse_host = bool(self._reuse_host and message["reuse_host"])
        if event == "prepared":
            # Register the foreign HWND while it is still DWM-cloaked and
            # reaffirm logical modality. Do not disable the native owner yet.
            # Disabling
            # the current foreground owner before a replacement HWND is active can
            # make Windows activate another desktop window for one frame.
            self._accept_native_hwnd(message)
            self._native_prepared = True
            if self._visible and self.modal:
                acquire_native_modal_input(self)
            if not message.get("publish_preauthorized", False):
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
            from ...diagnostics import log_event
            log_event("Dialog ready title={} source={} elapsed={:.1f}ms".format(
                getattr(self, "title", type(self).__name__),
                "reused" if getattr(self, "_from_reused_host", False) else
                "warm" if getattr(self, "_from_prewarm", False) else "cold", self._open_elapsed_ms))
            self._client_layout = message.get("layout") or {}
            self._startup_timings = message.get("timings") or {}
            if self._open_elapsed_ms >= 250:
                # Bounded timing-only diagnostics for slow opens on the user's
                # desktop. Never log payloads, credentials or selected paths.
                stages = [(str(name), float(value)) for name, value in self._startup_timings.items()
                          if isinstance(value, (int, float)) and value >= 0]
                slowest = sorted(stages, key=lambda pair: pair[1], reverse=True)[:3]
                log_event("Dialog startup slow stages={}".format(
                    ", ".join("{}:{:.1f}ms".format(name, value) for name, value in slowest)))
            self._startup_frames = message.get("startup_frames") or []
            self._refill_prewarm_pool()
            self._startup_layout = message.get("startup") or []
            self._initial_reveal_count = int(message.get("reveal_count") or 0)
            self._child_pid = int(message.get("pid") or 0) or getattr(self, "_child_pid", None)
            self._startup_generation += 1
            self._accept_native_hwnd(message)
            if not self._visibility_event_stale(message):
                self._confirm_visibility(
                    bool(message.get("visible", self._visible)),
                    return_focus=False,
                )
            # New runtimes have already published in response to the explicit
            # ``publish`` handshake.  Keep compatibility with an older child
            # process that may send only ``ready``.
            if not getattr(self, "_native_prepared", False):
                self.post("activate" if self._visible else "hide")
            self._flush_first_present_callbacks()
        elif event == "visibility":
            # A retained Qt-style tool can close itself (caption X/Escape)
            # without destroying its controller. Mirror QWidget::close(): the
            # object remains valid but its requested/native visibility becomes
            # false, so a later show()/activateWindow() is an instant reopen.
            if message.get("user_close") and not message.get("visible"):
                self._visible = False
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
            self._failed(
                str(message.get("message") or "Could not open floating dialog."),
                details=str(message.get("traceback") or ""),
                stage=str(message.get("stage") or ""),
            )
        else:
            # Feature events (button actions, refresh, save, submit, etc.) are
            # meaningful user activity even when the dialog lives in a child
            # process and the main Dear PyGui viewport sees no mouse/key event.
            activity = getattr(self.view, "callbacks", {}).get("user_activity")
            if callable(activity):
                try:
                    activity("floating-dialog")
                except TypeError:
                    activity()
            self.handle_event(event, message)

    def _visibility_event_stale(self, message):
        # Old runtimes omit the revision; retain their legacy handshake. New
        # hosts echo the last show/hide command they actually handled, including
        # a user-driven close. Never let an old close cancel a newer reopen.
        revision = message.get("visibility_revision")
        return type(revision) is int and revision < getattr(self, "_visibility_revision", 0)

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
        if self._host_lease is not None:
            self._host_lease.hwnd = hwnd
        # Prepared/reused hosts may be mapped under a DWM cloak while still
        # logically hidden. Register only a genuinely visible child as a
        # pointer surface; otherwise WindowFromPoint can treat an invisible
        # owned HWND as foreground input during main-window hover/startup.
        if getattr(self, "_native_visible", False):
            register_native_pointer_surface(hwnd)
        return True

    def handle_event(self, event, message):
        pass

    def _check_startup(self, generation=None):
        if generation is not None and generation != self._startup_generation:
            return
        if not self._closed and not self._ready:
            self._failed("The floating dialog did not become ready within {} seconds ({}).".format(self.STARTUP_TIMEOUT, self._ipc_stage))

    def _process_exited(self):
        if not self._closed:
            self._failed("The floating dialog process exited unexpectedly.")
        self._close_completed()

    def _close_completed(self):
        """UI-thread hook after native close and, for reuse, the idle ACK."""
        pass

    def _append_failure_log(self, message, details="", stage=""):
        """Persist the parent-visible failure even if child stderr redirection failed."""
        try:
            path = Path(self.log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("\n=== {} ===\n".format(datetime.now().isoformat(timespec="seconds")))
                if stage:
                    log.write("Stage: {}\n".format(stage))
                log.write(str(message).rstrip() + "\n")
                if details:
                    log.write(str(details).rstrip() + "\n")
            return path.is_file()
        except Exception:
            return False

    def _failed(self, message, details="", stage=""):
        if self._closed:
            return
        log_exists = self._append_failure_log(message, details, stage)
        from ...diagnostics import log_event
        log_event("Dialog failed title={} stage={}: {}".format(
            self.title, stage or getattr(self, "_ipc_stage", "startup"), message))
        # A failed host cannot provide a trustworthy idle ACK. Retire it via
        # destroy() now and complete cancellation without another five-second
        # recycle timeout that would keep Close App marked as pending.
        self._reuse_host = False
        self.destroy()
        if getattr(self, "_failure_notice", False):
            # If the error popup itself cannot start, launching another popup
            # repeats forever and consumes hosts while the app looks frozen.
            status = getattr(getattr(self.view, "right", None), "status", None)
            if status is not None:
                status.set("Dialog could not open. See WinUx logs for details.")
            return
        callback = getattr(self.view, "show_error", None)
        if callable(callback):
            text = str(message)
            if stage:
                text += "\nStage: " + stage
            # Put the actionable tail of the traceback directly in the popup.
            # This keeps diagnostics useful even on machines whose security
            # policy removes application logs immediately.
            if details:
                lines = [line for line in str(details).splitlines() if line.strip()]
                tail = "\n".join(lines[-8:])
                if tail:
                    text += "\n\nTraceback (last lines):\n" + tail
            if log_exists:
                text += "\n\nLog: " + self.log_path
            else:
                text += "\n\nLog could not be written."
            self.view.after(0, callback, self.title, text)

    def _refill_prewarm_pool(self):
        manager = getattr(self, "_host_manager", None)
        if manager is not None and not getattr(self, "_prewarm_refill_requested", False):
            self._prewarm_refill_requested = True
            manager.refill()

    def _finish(self):
        if self._finalized:
            return
        try:
            self._host_manager.forget_resident(self)
        except Exception:
            pass
        if getattr(self, "_reuse_host", False):
            self.post("close")
            self._recycle_generation += 1
            generation = self._recycle_generation
            self.view.after(5000, self._retire_unreturned_host, generation)
        self._refill_prewarm_pool()
        # Capture foreground ownership *before* hiding the child HWND. Result
        # dialogs can be finalized by the parent as soon as their IPC result
        # arrives, before the child process has time to send its final ``closed``
        # event. Once SW_HIDE runs, GetForegroundWindow may transiently report
        # the shell instead of the dialog and the information is lost.
        return_focus = bool(getattr(self, "_close_return_focus", False))
        if self._hwnd:
            try:
                return_focus = return_focus or int(_foreground_hwnd() or 0) in closing_dialog_hwnds(self)
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

        # Visual close is synchronous and independent of host recycling.  A
        # reusable child may need more time to destroy its DPG tree, drain
        # callbacks and return an idle ACK; none of that belongs on the user's
        # perceived close path.  Qt likewise removes the top-level from the
        # desktop before deferred-delete/destructor work completes.
        if (self._hwnd and getattr(self, "_native_visible", False)
                and int(self._hwnd) != int(self._owner_hwnd or 0)):
            set_native_window_visible(self._hwnd, False)
            self._native_visible = False
        self._closed = self._finalized = True
        getattr(self, "_first_present_callbacks", []).clear()
        self._startup_generation += 1
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
            if ((not preclose_handoff and not owner_already_foreground)
                    or not _owner_has_keyboard_focus(self._owner_hwnd)):
                self._queue_owner_focus(force=True)
        for child in tuple(getattr(self, "_owned_dialogs", ())):
            child.destroy()
        registry = getattr(self.view, "_floating_dialogs", None)
        if registry is not None:
            registry.discard(self)
        if hasattr(self, "_connection_ready"):
            self._connection_ready.set()
        if self._host_lease is not None:
            self._host_lease.close_channel(
                connection=not getattr(self, "_reuse_host", False), listener=True)
        if not getattr(self, "_reuse_host", False):
            self._close_completed()

    def _retire_unreturned_host(self, generation=None):
        if generation is not None and generation != self._recycle_generation:
            return
        if not self._host_returned:
            self._host_lease.retire()
            self.view.after(0, self._close_completed)

    def winfo_exists(self):
        return not self._closed

    def isVisible(self):
        """Qt-compatible requested visibility for retained floating dialogs."""
        return bool(not self._closed and self._visible)

    def isHidden(self):
        return not self.isVisible()

    def activateWindow(self):
        return self.show()

    def after_first_present(self, callback, *args):
        """Start data work after this native dialog is published, not requested."""
        if self._closed:
            return False

        def deliver():
            if not self._closed and self._visible and self._native_visible:
                callback(*args)

        self._first_present_callbacks.append(deliver)
        self._flush_first_present_callbacks()
        return True

    def _flush_first_present_callbacks(self):
        callbacks = getattr(self, "_first_present_callbacks", None)
        if not callbacks or not self._ready or not self._visible or not self._native_visible:
            return
        self._first_present_callbacks = []
        for callback in callbacks:
            self.view.after(0, callback)

    def show(self):
        if self._closed:
            return False
        if self._retain_on_close:
            self._resident_generation += 1
            self._host_manager.retained_visible(self)
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
        if self._hwnd:
            if visible:
                register_native_pointer_surface(self._hwnd)
            else:
                unregister_native_pointer_surface(self._hwnd)
        if visible:
            if self._retain_on_close:
                self._host_manager.retained_visible(self)
            if self._visible:
                # Ensure a modal cannot be visible while its owner is enabled,
                # including recovery from a late/out-of-order child event.
                self._set_visible(True)
                self._flush_first_present_callbacks()
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
        if self._retain_on_close:
            self._resident_generation += 1
            self._host_manager.retained_hidden(self)

    def _release_visibility_guards(self, queue_focus=False, force_focus=False):
        getattr(self, "_first_present_callbacks", []).clear()
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

    def _evict_retained(self, generation):
        """Recycle one stale hidden retained host when the resident cache is full."""
        if (self._closed or not self._retain_on_close or self._visible or
                int(generation) != int(getattr(self, "_resident_generation", -1))):
            return False
        self.destroy()
        return True

    def close(self):
        """Qt-style user close.

        Retained modeless tools behave like QWidget/QDialog instances without
        WA_DeleteOnClose: close hides the native top-level but keeps its object,
        widget tree and expensive graphics resources alive for an instant
        subsequent show().  ``destroy()`` remains the terminal application
        teardown path and always retires the host.
        """
        if self._closed:
            return False
        if self._retain_on_close:
            return self.hide()
        self.destroy()
        return True

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
        if getattr(self, "_reuse_host", False):
            return
        # QDialogLease owns process retirement for pooled and disposable hosts.
        if self._host_lease is not None:
            self._host_lease.retire()
