"""Bounded idle DPG workers, prepared off the UI thread and leased once."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading

from .floating_dialog import floating_dialog_command, floating_dialog_log_path
from ..runtime.child_processes import (
    register_child_process, unregister_child_process,
)
from ..services.floating_protocol import read_messages


class PreparedWorker:
    def __init__(self):
        self.ready = threading.Event()
        self.closed = False
        self.process = None
        self.connection = None
        self.messages = None
        self.listener = None
        self._reap_started = False
        self.token = secrets.token_hex(32)
        self.log_path = floating_dialog_log_path("prewarm")

    def prepare(self):
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.bind(("127.0.0.1", 0))
            self.listener.listen(1)
            self.listener.settimeout(25)
            script = Path(__file__).resolve().parents[1] / "services" / "floating_dialog_process.py"
            environment = os.environ.copy()
            environment["WINUX_FLOAT_DIALOG_PORT"] = str(self.listener.getsockname()[1])
            environment["WINUX_FLOAT_DIALOG_TOKEN"] = self.token
            environment["WINUX_FLOAT_DIALOG_PREWARM"] = "1"
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "ab", buffering=0) as log:
                if self.closed:
                    return
                self.process = subprocess.Popen(floating_dialog_command(script), stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, cwd=str(script.parent), env=environment,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                register_child_process(self.process, "dialog-prewarm")
            self.connection, _ = self.listener.accept()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connection.settimeout(25)
            self.messages = read_messages(self.connection)
            hello = next(self.messages)
            if not secrets.compare_digest(str(hello.get("token", "")), self.token):
                raise ValueError("Invalid prewarm handshake")
            message = next(self.messages)
            if message.get("event") != "warm_ready":
                raise RuntimeError("Dialog worker did not finish prewarming")
            self.connection.settimeout(None)
            if self.closed:
                self.close()
            else:
                self.ready.set()
        except (OSError, ValueError, RuntimeError, StopIteration):
            self.close()
        finally:
            if self.listener:
                self.listener.close()

    def close(self):
        self.closed = True
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
        if self.listener:
            self.listener.close()
        process = self.process
        if process is None or self._reap_started:
            return
        self._reap_started = True
        def reap():
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    process.terminate()
            finally:
                unregister_child_process(process)
        threading.Thread(target=reap, name="dialog-prewarm-cleanup", daemon=True).start()


class DialogPrewarmPool:
    def __init__(self, capacity=2):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._closed = False
        self._workers = []
        self._fill()

    def _fill(self):
        with self._lock:
            if self._closed:
                return
            retired = [worker for worker in self._workers if worker.closed
                       or (worker.process is not None and worker.process.poll() is not None)]
            self._workers = [worker for worker in self._workers if worker not in retired]
            additions = [PreparedWorker() for _ in range(self.capacity - len(self._workers))]
            self._workers.extend(additions)
        for worker in retired:
            worker.close()
        for worker in additions:
            threading.Thread(target=worker.prepare, name="dialog-prewarm", daemon=True).start()

    def claim(self):
        # A user callback never waits for a worker or a preparation lock.
        if not self._lock.acquire(False):
            return None
        try:
            if self._closed:
                return None
            worker = next((worker for worker in self._workers
                if worker.ready.is_set() and not worker.closed
                and worker.process is not None and worker.process.poll() is None), None)
            if worker is not None:
                self._workers.remove(worker)
            needs_refill = worker is not None or any(other.closed
                or (other.process is not None and other.process.poll() is not None) for other in self._workers)
        finally:
            self._lock.release()
        if needs_refill:
            threading.Thread(target=self._fill, name="dialog-prewarm-refill", daemon=True).start()
        return worker

    def close(self):
        with self._lock:
            self._closed = True
            workers, self._workers = self._workers, []
        for worker in workers:
            worker.close()


def start_dialog_prewarm(view):
    if getattr(view, "_floating_focus_suppressed", False) or not view.winfo_exists():
        return
    if getattr(view, "_dialog_prewarm_pool", None) is None:
        view._dialog_prewarm_pool = DialogPrewarmPool()
