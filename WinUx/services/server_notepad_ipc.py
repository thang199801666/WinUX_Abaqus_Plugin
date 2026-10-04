"""Threaded JSON-lines IPC bridge for the standalone Server Notepad process."""
from __future__ import annotations

import base64
import json
import queue
import sys
import threading
import time
import zlib


class ServerNotepadProcessBridge:
    """Bridge the Tk child process with the WinUx parent without blocking Tk."""

    def __init__(self):
        self.window = None
        self._incoming = queue.Queue(maxsize=24)
        self._outgoing = queue.Queue(maxsize=32)
        self._write_lock = threading.Lock()
        self._closed = threading.Event()
        self._writer = threading.Thread(
            target=self._writer_loop,
            name="winux-server-notepad-parent-writer",
            daemon=True,
        )
        self._reader = threading.Thread(
            target=self._reader_loop,
            name="winux-server-notepad-parent-reader",
            daemon=True,
        )
        self._writer.start()
        self._reader.start()

    def attach(self, window):
        self.window = window
        self._send({"event": "ready"})
        self._send({
            "event": "window_shown",
            "hwnd": int(window._native_hwnd() or 0),
        })

    def _reader_loop(self):
        stream = getattr(sys.stdin, "buffer", sys.stdin)
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
                    # Expand compressed snapshot payloads here on the reader
                    # thread. The Tk thread receives Unicode text and never
                    # pays zlib/base64 cost while painting the editor.
                    if (str(message.get("command") or "") == "snapshot_chunk"
                            and str(message.get("codec") or "") == "zlib+base64"):
                        try:
                            raw = base64.b64decode(
                                str(message.get("data") or "").encode("ascii"))
                            message["text"] = zlib.decompress(raw).decode("utf-8")
                            message.pop("data", None)
                            message.pop("codec", None)
                        except Exception:
                            message["text"] = ""
                    self._incoming.put(message)
                    if str(message.get("command") or "") == "close":
                        # Parent explicitly requested shutdown. Exit now rather
                        # than blocking on another readline during Tk teardown.
                        break
        finally:
            self._incoming.put({"command": "close"})

    def _writer_loop(self):
        stream = getattr(sys.stdout, "buffer", sys.stdout)
        while True:
            try:
                message = self._outgoing.get()
            except Exception:
                break
            if message is None:
                break
            try:
                payload_message = dict(message)
                # Large saves are compressed/serialized on the writer thread so
                # Tk never pays the cost during an interactive frame.
                if (str(payload_message.get("event") or "") == "save_request"
                        and len(str(payload_message.get("text") or "")) >= 32 * 1024):
                    text = str(payload_message.pop("text", "") or "")
                    raw = text.encode("utf-8")
                    compressed = zlib.compress(raw, 1)
                    encoded = base64.b64encode(compressed).decode("ascii")
                    if len(encoded) + 128 < len(raw):
                        payload_message["codec"] = "zlib+base64"
                        payload_message["data"] = encoded
                    else:
                        payload_message["text"] = text
                payload = (json.dumps(
                    payload_message,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ) + "\n").encode("utf-8")
                with self._write_lock:
                    stream.write(payload)
                    stream.flush()
            except Exception:
                self._closed.set()
                break

    def _send(self, message):
        if self._closed.is_set():
            return False
        try:
            self._outgoing.put_nowait(dict(message))
            return True
        except queue.Full:
            return False
        except Exception:
            self._closed.set()
            return False

    def pump(self):
        window = self.window
        if window is None:
            return
        started = time.perf_counter()
        processed = 0
        while (processed < window.IPC_PUMP_MAX_MESSAGES and
               (time.perf_counter() - started) * 1000.0 < window.IPC_PUMP_BUDGET_MS):
            try:
                message = self._incoming.get_nowait()
            except queue.Empty:
                break
            processed += 1
            command = str(message.get("command") or "")
            if command == "queue_open":
                window.handle_command("queue_open", str(message.get("path") or ""))
            elif command == "load_succeeded":
                window.handle_command(
                    "load_succeeded", dict(message.get("snapshot") or {}))
            elif command == "snapshot_begin":
                window._snapshot_begin_ui(
                    str(message.get("operation") or "load"),
                    dict(message.get("snapshot") or {}),
                )
            elif command == "snapshot_chunk":
                window._snapshot_chunk_ui(
                    str(message.get("operation") or "load"),
                    str(message.get("path") or ""),
                    str(message.get("text") or ""),
                    int(message.get("source_bytes") or 0),
                )
            elif command == "snapshot_end":
                window._snapshot_end_ui(
                    str(message.get("operation") or "load"),
                    str(message.get("path") or ""),
                    dict(message.get("snapshot") or {}),
                )
            elif command == "save_succeeded":
                window.handle_command(
                    "save_succeeded", dict(message.get("snapshot") or {}))
            elif command == "save_conflict":
                window.handle_command(
                    "save_conflict", str(message.get("message") or ""),
                    message.get("path"))
            elif command == "operation_failed":
                window.handle_command(
                    "operation_failed", str(message.get("message") or ""),
                    message.get("path"), message.get("operation"))
            elif command == "reload_succeeded":
                window.handle_command(
                    "reload_succeeded", dict(message.get("snapshot") or {}))
            elif command in ("activate", "show"):
                window.handle_command("activate")
            elif command == "hide":
                window.handle_command("hide")
            elif command == "close":
                window.handle_command("close")
        if not self._closed.is_set():
            try:
                # Drain quickly while data is pending, otherwise back off.
                window.after(1 if not self._incoming.empty() else 16, self.pump)
            except Exception:
                pass

    def request_load(self, path):
        return self._send({"event": "load_request", "path": str(path)})

    def request_save(self, path, text, encoding, expected_signature, force=False):
        return self._send({
            "event": "save_request",
            "path": str(path),
            "text": str(text),
            "encoding": str(encoding),
            "signature": dict(expected_signature or {}),
            "force": bool(force),
        })

    def request_reload(self, path):
        return self._send({"event": "reload_request", "path": str(path)})

    def notify_closed(self):
        if not self._closed.is_set():
            self._send({"event": "closed"})
        self._closed.set()
        try:
            self._outgoing.put_nowait(None)
        except Exception:
            pass
