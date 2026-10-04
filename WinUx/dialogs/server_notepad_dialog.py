from __future__ import annotations

"""Process-isolated WinUx Server Notepad window.

The Notepad UI is intentionally hosted in a dedicated Python/Tk process rather
than on WinUx's shared Tk dialog thread.  The child process owns *all* Tk
objects and a normal ``tk.Tk`` top-level window.  The parent WinUx process keeps
ownership of SSH/SFTP and sends only plain JSON messages over the child's
stdin/stdout pipes.

This separation is deliberate:
* a Tcl/Tk failure cannot terminate WinUx or block Abaqus;
* the editor can run a normal Tk mainloop like a desktop Notepad window;
* server I/O remains inside the existing WinUx controller/model;
* files are requested one-at-a-time by the child, so tabs load sequentially.
"""

import base64
import json
import os
import zlib
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

try:
    from ..runtime.child_processes import (
        register_child_process, unregister_child_process,
    )
except ImportError:  # direct-module compatibility tests / legacy embedding
    def register_child_process(process, label="helper"):
        del label
        return process

    def unregister_child_process(_process_or_pid):
        return None


_SNAPSHOT_IPC_CHARS = 256 * 1024
_SNAPSHOT_COMPRESS_MIN_CHARS = 32 * 1024


def _detect_eol(text):
    text = str(text or "")
    crlf = text.count("\r\n")
    remainder = text.replace("\r\n", "")
    lf = remainder.count("\n")
    cr = remainder.count("\r")
    if crlf >= lf and crlf >= cr and crlf:
        return "\r\n"
    if cr > lf and cr:
        return "\r"
    return "\n"


class ServerNotepadDialog:
    """Facade for the standalone Tkinter Server Notepad window process.

    The historical name is retained to avoid breaking existing View code, but
    this object is no longer a modal/native dialog controller.  It owns a child
    process and presents a small dialog-compatible API to the rest of WinUx.
    """

    NATIVE_WINDOW = True
    FLOATABLE = True
    modal = False

    def __init__(
            self, view, initial_path=None, on_load=None, on_save=None,
            on_reload=None):
        """Create the standalone editor facade.

        ``on_load`` was added when Server Notepad moved from eager snapshots
        to sequential, child-driven loading.  Keep the constructor compatible
        with the v1.4.0/v1.4.1 call shape::

            ServerNotepadDialog(view, snapshot, on_save=..., on_reload=...)

        This matters during self-update: a user may temporarily have a newer
        dialog module next to an older ``view.py`` while files are being
        replaced or when a changed-files-only patch was applied manually.
        A mixed installation must degrade to the legacy snapshot path rather
        than crashing before the editor window opens.
        """
        self.view = view
        self._on_load = on_load
        self._on_save = on_save
        self._on_reload = on_reload
        self._closed = threading.Event()
        self._write_lock = threading.Lock()
        self._process = None
        self._reader_thread = None
        self._stream_threads = set()
        self._stream_threads_lock = threading.Lock()
        self._stderr_path = None
        self._native_input_hwnd = None
        # Commands issued immediately after Popen are held until the child has
        # created and mapped its Tk window.  This removes the startup race where
        # session restore could run before the user-selected file reached the
        # editor.
        self._ready = threading.Event()
        self._window_shown = threading.Event()
        self._pending_commands = []
        self._pending_commands_lock = threading.Lock()
        self._startup_watchdog = None
        self._startup_started_at = 0.0

        # v1.4.0/v1.4.1 passed a complete snapshot as argument 2.  Newer
        # versions pass only a remote path and let the child request loading.
        legacy_snapshot = (
            dict(initial_path) if isinstance(initial_path, dict) else None)

        self._start_process()
        if legacy_snapshot is not None:
            path = str(legacy_snapshot.get("path") or "")
            if path:
                # Create the tab first, then stream the already-loaded legacy
                # snapshot through the exact same bounded IPC path used today.
                self.queue_open(path)
                self.load_succeeded(legacy_snapshot)
        else:
            self.queue_open(initial_path)

    # ------------------------------------------------------------------
    # Process lifecycle / IPC
    # ------------------------------------------------------------------
    def _start_process(self):
        script = Path(__file__).resolve().parents[1] / "services" / "server_notepad_process.py"
        log_dir = Path(tempfile.gettempdir()) / "WinUx" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._stderr_path = str(log_dir / "server_notepad.log")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        child_env = os.environ.copy()
        # A standalone child cannot discover the WinUx HWND by enumerating its
        # own process.  Pass the fixed owner HWND explicitly so the editor can
        # centre/restore itself on the same monitor as WinUx.
        try:
            from ..platform.native_dialog_host import find_process_window
            owner_hwnd = int(find_process_window("WinUX") or 0)
        except Exception:
            owner_hwnd = 0
        if owner_hwnd:
            child_env["WINUX_SERVER_NOTEPAD_OWNER_HWND"] = str(owner_hwnd)

        log_handle = None
        try:
            log_handle = open(self._stderr_path, "ab", buffering=0)
            self._process = subprocess.Popen(
                [sys.executable, "-B", str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                bufsize=0,
                creationflags=creationflags,
                cwd=str(script.parent),
                env=child_env,
            )
            register_child_process(self._process, "server-notepad")
        except Exception:
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass
            self._closed.set()
            raise
        finally:
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="winux-server-notepad-ipc",
            daemon=True,
        )
        self._reader_thread.start()
        self._startup_started_at = time.monotonic()
        self._arm_startup_watchdog()

    def _arm_startup_watchdog(self, timeout=10.0):
        """Fail a half-started child instead of leaving WinUx on Opening forever."""
        def check():
            if self._closed.is_set() or self._ready.is_set():
                return
            process = self._process
            elapsed = max(0.0, time.monotonic() - self._startup_started_at)
            if process is None or process.poll() is not None:
                detail = "Server Notepad exited before its window became ready."
            else:
                detail = (
                    "Server Notepad did not finish creating its window after "
                    "{:.1f} seconds.".format(elapsed))
                try:
                    process.terminate()
                except Exception:
                    pass
            self._closed.set()
            try:
                self.view.after(
                    0, self.view.show_error, "Server Notepad",
                    detail + "\n\nDiagnostic log: {}".format(self._stderr_path))
            except Exception:
                pass

        timer = threading.Timer(max(1.0, float(timeout)), check)
        timer.daemon = True
        self._startup_watchdog = timer
        timer.start()

    def _cancel_startup_watchdog(self):
        timer, self._startup_watchdog = self._startup_watchdog, None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _flush_pending_commands(self):
        if not self._ready.is_set() or self._closed.is_set():
            return
        with self._pending_commands_lock:
            pending = self._pending_commands
            self._pending_commands = []
        for message in pending:
            try:
                encoded = self._encode_message(message)
                with self._write_lock:
                    if not self._write_encoded_locked(encoded):
                        return
            except Exception:
                self._mark_closed(unexpected=True)
                return

    def _reader_loop(self):
        process = self._process
        stream = getattr(process, "stdout", None)
        if stream is None:
            self._mark_closed(unexpected=True)
            return
        try:
            while not self._closed.is_set():
                raw = stream.readline()
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(message, dict):
                    event = str(message.get("event") or "")
                    if event == "ready":
                        # Handshake state belongs to IPC, not to the WinUx UI
                        # event loop.  Mark/flush it here so a briefly busy main
                        # window cannot let the child's restore timer win.
                        self._ready.set()
                        self._cancel_startup_watchdog()
                        self._flush_pending_commands()
                    elif event == "window_shown":
                        self._window_shown.set()
                    elif event == "closed":
                        self._closed.set()
                    # Large saves are compressed/serialised on the child
                    # writer thread.  Expand them here on the parent reader
                    # thread so neither Tk nor the DPG/Abaqus UI thread pays
                    # the zlib/base64 cost.
                    if (event == "save_request"
                            and str(message.get("codec") or "") == "zlib+base64"):
                        try:
                            raw_payload = base64.b64decode(
                                str(message.get("data") or "").encode("ascii"))
                            message["text"] = zlib.decompress(raw_payload).decode("utf-8")
                            message.pop("data", None)
                            message.pop("codec", None)
                        except Exception as exc:
                            message = {
                                "event": "error",
                                "message": "Could not decode Server Notepad save payload: {}".format(exc),
                            }
                    try:
                        self.view.after(0, self._handle_child_message, message)
                    except Exception:
                        break
        finally:
            self._mark_closed(unexpected=not self._closed.is_set())

    def _handle_child_message(self, message):
        event = str(message.get("event") or "")
        if event == "ready":
            self._ready.set()
            self._cancel_startup_watchdog()
            self._flush_pending_commands()
            # A second activation after the native window is mapped is cheap and
            # makes Windows restore/foreground behaviour deterministic.
            self._send("activate")
            return
        if event == "window_shown":
            self._window_shown.set()
            if not self._closed.is_set():
                from ..components.interaction_gate import register_native_pointer_surface
                self._native_input_hwnd = register_native_pointer_surface(message.get("hwnd"))
            return
        if event == "load_request":
            path = str(message.get("path") or "")
            if path and callable(self._on_load):
                self._on_load(self, path)
            # A legacy eager-snapshot caller intentionally has no on_load
            # callback.  Its snapshot is already being streamed to the child,
            # so the child's load request is simply ignored.
            return
        if event == "save_request":
            if callable(self._on_save):
                self._on_save(
                    self,
                    str(message.get("path") or ""),
                    str(message.get("text") or ""),
                    str(message.get("encoding") or "utf-8"),
                    dict(message.get("signature") or {}),
                    bool(message.get("force")),
                )
            else:
                self.operation_failed(
                    "Server Notepad save callback is unavailable. "
                    "Please restart WinUx after updating.",
                    str(message.get("path") or ""),
                    operation="save",
                )
            return
        if event == "reload_request":
            path = str(message.get("path") or "")
            if path and callable(self._on_reload):
                self._on_reload(self, path)
            elif path:
                self.operation_failed(
                    "Server Notepad reload callback is unavailable. "
                    "Please restart WinUx after updating.",
                    path,
                    operation="reload",
                )
            return
        if event == "closed":
            self._closed.set()
            self._unregister_input_surface()
            return
        if event == "error":
            detail = str(message.get("message") or "Server Notepad failed")
            try:
                self.view.show_error("Server Notepad", detail)
            except Exception:
                pass

    def _mark_closed(self, unexpected=False):
        was_closed = self._closed.is_set()
        self._closed.set()
        self._cancel_startup_watchdog()
        self._unregister_input_surface()
        if unexpected and not was_closed:
            try:
                self.view.after(
                    0,
                    self.view.show_error,
                    "Server Notepad",
                    "The Server Notepad window closed unexpectedly.\n\n"
                    "Diagnostic log: {}".format(self._stderr_path),
                )
            except Exception:
                pass

    def _unregister_input_surface(self):
        hwnd = getattr(self, "_native_input_hwnd", None)
        self._native_input_hwnd = None
        if hwnd:
            from ..components.interaction_gate import unregister_native_pointer_surface
            unregister_native_pointer_surface(hwnd)

    @staticmethod
    def _encode_message(message):
        return (json.dumps(
            message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def _write_encoded_locked(self, encoded):
        process = self._process
        if (self._closed.is_set() or process is None or
                process.poll() is not None or process.stdin is None):
            self._closed.set()
            return False
        process.stdin.write(encoded)
        process.stdin.flush()
        return True

    def _send(self, command, **payload):
        if self._closed.is_set():
            return False
        message = {"command": str(command)}
        message.update(payload)
        # Do not let queue_open race the child's startup/session-restore timer.
        # Close is the only command that may bypass the ready handshake.
        if not self._ready.is_set() and str(command) != "close":
            with self._pending_commands_lock:
                if self._closed.is_set():
                    return False
                self._pending_commands.append(message)
            return True
        try:
            encoded = self._encode_message(message)
            with self._write_lock:
                return self._write_encoded_locked(encoded)
        except Exception:
            self._mark_closed(unexpected=True)
            return False

    def stream_begin(self, operation, snapshot):
        """Begin a live network-to-editor snapshot stream."""
        snap = dict(snapshot or {})
        return self._send(
            "snapshot_begin",
            operation=str(operation or "load"),
            snapshot=snap,
        )

    def stream_chunk(self, operation, path, text, source_bytes=0):
        """Forward one decoded server chunk with bounded JSON IPC frames.

        Splitting here keeps each pipe write modest and allows the child-side
        bounded queue to apply backpressure.  This prevents a fast SFTP reader
        from allocating many megabytes while Tk is busy painting.
        """
        text = str(text or "")
        path = str(path or "")
        if not text:
            return True
        total_chars = max(1, len(text))
        remaining_bytes = max(0, int(source_bytes or 0))
        for offset in range(0, len(text), _SNAPSHOT_IPC_CHARS):
            part = text[offset:offset + _SNAPSHOT_IPC_CHARS]
            if offset + len(part) >= len(text):
                part_bytes = remaining_bytes
            else:
                part_bytes = int(round(
                    max(0, int(source_bytes or 0)) * len(part) / float(total_chars)))
                part_bytes = min(remaining_bytes, max(0, part_bytes))
            remaining_bytes = max(0, remaining_bytes - part_bytes)
            payload = {
                "operation": str(operation or "load"),
                "path": path,
                "source_bytes": part_bytes,
            }
            # Large source/code chunks compress extremely well.  Compressing
            # before JSON-lines IPC cuts both pipe traffic and JSON parser work;
            # the child expands it on its background reader thread, never on
            # the Tk mainloop.
            if len(part) >= _SNAPSHOT_COMPRESS_MIN_CHARS:
                raw = part.encode("utf-8")
                compressed = zlib.compress(raw, 1)
                encoded = base64.b64encode(compressed).decode("ascii")
                if len(encoded) + 96 < len(raw):
                    payload.update(codec="zlib+base64", data=encoded)
                else:
                    payload["text"] = part
            else:
                payload["text"] = part
            if not self._send("snapshot_chunk", **payload):
                return False
        return True

    def stream_end(self, operation, snapshot):
        snap = dict(snapshot or {})
        return self._send(
            "snapshot_end",
            operation=str(operation or "load"),
            path=str(snap.get("path") or ""),
            snapshot=snap,
        )

    def _send_snapshot_stream(self, operation, snapshot):
        """Send large editor snapshots in bounded IPC chunks off the DPG thread."""
        snap = dict(snapshot or {})
        text = str(snap.pop("text", "") or "")
        path = str(snap.get("path") or "")
        snap["text_chars"] = len(text)
        snap["eol"] = _detect_eol(text)
        begin = self._encode_message({
            "command": "snapshot_begin",
            "operation": str(operation),
            "snapshot": snap,
        })
        end_message = {
            "command": "snapshot_end",
            "operation": str(operation),
            "path": path,
            "snapshot": snap,
        }
        try:
            with self._write_lock:
                if not self._write_encoded_locked(begin):
                    return
                for offset in range(0, len(text), _SNAPSHOT_IPC_CHARS):
                    chunk = text[offset:offset + _SNAPSHOT_IPC_CHARS]
                    encoded = self._encode_message({
                        "command": "snapshot_chunk",
                        "operation": str(operation),
                        "path": path,
                        "text": chunk,
                        "source_bytes": len(chunk.encode("utf-8", "replace")),
                    })
                    if not self._write_encoded_locked(encoded):
                        return
                self._write_encoded_locked(self._encode_message(end_message))
        except Exception:
            self._mark_closed(unexpected=True)

    def _queue_snapshot_stream(self, operation, snapshot):
        if self._closed.is_set():
            return False
        holder = {}

        def worker():
            try:
                self._send_snapshot_stream(operation, snapshot)
            finally:
                thread = holder.get("thread")
                if thread is not None:
                    with self._stream_threads_lock:
                        self._stream_threads.discard(thread)

        thread = threading.Thread(
            target=worker,
            name="winux-server-notepad-{}-stream".format(operation),
            daemon=True,
        )
        holder["thread"] = thread
        with self._stream_threads_lock:
            self._stream_threads.add(thread)
        thread.start()
        return True

    # ------------------------------------------------------------------
    # Public window-compatible API used by View/Controller
    # ------------------------------------------------------------------
    def winfo_exists(self):
        process = self._process
        return (
            not self._closed.is_set()
            and process is not None
            and process.poll() is None
        )

    def queue_open(self, path):
        path = str(path or "")
        if not path:
            return False
        return self._send("queue_open", path=path)

    def open_snapshot(self, snapshot):
        # Backward-compatible alias; snapshots are delivered only after the
        # child explicitly requests the next queued file.
        return self.load_succeeded(snapshot)

    def load_succeeded(self, snapshot):
        return self._queue_snapshot_stream("load", dict(snapshot or {}))

    def save_succeeded(self, snapshot):
        # The editor already contains the saved text.  Do not echo multi-MB
        # content back through IPC just to update signature/size metadata.
        compact = dict(snapshot or {})
        compact.pop("text", None)
        return self._send("save_succeeded", snapshot=compact)

    def save_conflict(self, message, path=None):
        return self._send(
            "save_conflict",
            message=str(message or ""),
            path=None if path is None else str(path),
        )

    def operation_failed(self, message, path=None, operation=None):
        return self._send(
            "operation_failed",
            message=str(message or ""),
            path=None if path is None else str(path),
            operation=None if operation is None else str(operation),
        )

    def reload_succeeded(self, snapshot):
        return self._queue_snapshot_stream("reload", dict(snapshot or {}))

    def show(self):
        return self._send("activate")

    def lift(self):
        return self._send("activate")

    def hide(self):
        return self._send("hide")

    def request_close(self, *_args):
        return self._send("close")

    def destroy(self, wait=False, timeout=1.0):
        self._cancel_startup_watchdog()
        self._unregister_input_surface()
        with self._pending_commands_lock:
            self._pending_commands = []
        process = self._process
        if process is None:
            self._closed.set()
            return
        if process.poll() is None:
            self._send("close")

            def terminate_later():
                try:
                    process.wait(timeout=max(0.15, float(timeout)))
                except Exception:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                finally:
                    unregister_child_process(process)
                    self._closed.set()

            if wait:
                terminate_later()
            else:
                threading.Thread(
                    target=terminate_later,
                    name="winux-server-notepad-close",
                    daemon=True,
                ).start()
        else:
            self._closed.set()

    close = destroy
