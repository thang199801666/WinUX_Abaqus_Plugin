"""Small Qt-like process owner used by reusable UI host services.

The wrapper intentionally mirrors the lifecycle-oriented part of ``QProcess``
without trying to emulate Qt's byte-stream API.  It keeps subprocess ownership,
child-process registration and idempotent termination in one place so dialogs
never manipulate ``subprocess.Popen`` directly.
"""
from __future__ import annotations

import os
import subprocess
import threading

from .object import QObject, Signal
from .timer import QTimer


class QProcess(QObject):
    NotRunning = 0
    Starting = 1
    Running = 2

    def __init__(self, parent=None, *, after=None, childLabel="helper"):
        super().__init__(parent, after=after)
        self.started = Signal(self)
        self.finished = Signal(self)
        self.errorOccurred = Signal(self)
        self.stateChanged = Signal(self)
        self._process = None
        self._state = self.NotRunning
        self._child_label = str(childLabel or "helper")
        self._finished_emitted = False
        self._exit_code = None
        self._poll_interval = 50
        self._monitor_timer = None

    @classmethod
    def launch(cls, program, arguments=(), *, cwd=None, env=None,
               stdin=subprocess.DEVNULL, stdout=None, stderr=None,
               creationflags=0, childLabel="helper"):
        process = cls(childLabel=childLabel)
        process.start(program, arguments, cwd=cwd, env=env, stdin=stdin,
                      stdout=stdout, stderr=stderr, creationflags=creationflags)
        return process

    def start(self, program, arguments=(), *, cwd=None, env=None,
              stdin=subprocess.DEVNULL, stdout=None, stderr=None,
              creationflags=0):
        if self.poll() is None and self._process is not None:
            raise RuntimeError("process is already running")
        self._set_state(self.Starting)
        self._finished_emitted = False
        self._exit_code = None
        try:
            self._process = subprocess.Popen(
                [program] + list(arguments), stdin=stdin, stdout=stdout,
                stderr=stderr, cwd=cwd, env=env, creationflags=creationflags,
            )
            self._set_state(self.Running)
            self.started.emit()
            self._start_monitoring()
            return self
        except Exception as exc:
            self._set_state(self.NotRunning)
            self.errorOccurred.emit(exc)
            raise

    def startCommand(self, command, *, cwd=None, env=None,
                     stdin=subprocess.DEVNULL, stdout=None, stderr=None,
                     creationflags=0):
        if not command:
            raise ValueError("process command cannot be empty")
        return self.start(command[0], command[1:], cwd=cwd, env=env,
                          stdin=stdin, stdout=stdout, stderr=stderr,
                          creationflags=creationflags)

    @property
    def pid(self):
        return int(getattr(self._process, "pid", 0) or 0)

    @property
    def stdin(self):
        return getattr(self._process, "stdin", None)

    @property
    def stdout(self):
        return getattr(self._process, "stdout", None)

    @property
    def stderr(self):
        return getattr(self._process, "stderr", None)

    def processId(self):
        return self.pid

    def state(self):
        return self._state

    def isRunning(self):
        """Return cached Qt-style running state without polling the OS process."""
        return self._state == self.Running

    def isFinished(self):
        return self._state == self.NotRunning and self._process is not None

    def pollingInterval(self):
        return self._poll_interval

    def setPollingInterval(self, milliseconds):
        if type(milliseconds) is not int or milliseconds <= 0:
            raise ValueError("process polling interval must be a positive integer")
        self._poll_interval = milliseconds
        timer = self._monitor_timer
        if timer is not None and timer.isActive():
            timer.setInterval(milliseconds)

    def isMonitoring(self):
        timer = self._monitor_timer
        return bool(timer is not None and timer.isActive())

    def startMonitoring(self):
        """Enable QApplication/QTimer-driven exit detection when available.

        Processes launched before the UI scheduler exists can opt in later.
        The method never creates a watcher thread; it returns ``False`` when
        called outside the owning UI thread or without a usable scheduler.
        """
        if threading.get_ident() != self.threadId():
            return False
        return self._start_monitoring()

    def stopMonitoring(self):
        if threading.get_ident() != self.threadId():
            return False
        was_active = self.isMonitoring()
        self._stop_monitoring()
        return was_active

    def _set_state(self, state):
        state = int(state)
        if self._state == state:
            return False
        self._state = state
        self.stateChanged.emit(state)
        return True

    def _monitor_scheduler(self):
        if callable(self._after):
            return self._after
        try:
            from .application import QCoreApplication
            application = QCoreApplication.instance()
        except Exception:
            application = None
        if application is None or application.threadId() != self.threadId():
            return None
        return application._after if callable(getattr(application, "_after", None)) else None

    def _start_monitoring(self):
        scheduler = self._monitor_scheduler()
        if scheduler is None or self._process is None or self._state != self.Running:
            return False
        timer = self._monitor_timer
        if timer is None or timer._deleted:
            timer = QTimer(self, after=scheduler)
            timer.timeout.connect(self._monitor_tick)
            self._monitor_timer = timer
        if not timer.isActive():
            timer.start(self._poll_interval)
        return True

    def _stop_monitoring(self):
        timer = self._monitor_timer
        if timer is not None and not timer._deleted:
            timer.stop()

    def _monitor_tick(self):
        process = self._process
        if process is None or self._state != self.Running:
            self._stop_monitoring()
            return
        result = process.poll()
        if result is not None:
            self._mark_finished(result)

    def nativeProcess(self):
        return self._process

    def poll(self):
        if self._process is None:
            self._set_state(self.NotRunning)
            return 0
        result = self._process.poll()
        if result is not None:
            self._mark_finished(result)
        return result

    def wait(self, timeout=None):
        if self._process is None:
            return 0
        result = self._process.wait(timeout=timeout)
        self._mark_finished(result)
        return result

    def communicate(self, input=None, timeout=None):
        """Exchange pipe data and update lifecycle state when the child exits.

        This mirrors the small part of :meth:`subprocess.Popen.communicate`
        needed by process-isolated widgets.  Keeping the operation here lets
        callers stay on the QProcess ownership surface rather than reaching
        through ``nativeProcess()`` merely to drain stdout/stderr.
        """
        if self._process is None:
            return (None, None)
        output = self._process.communicate(input=input, timeout=timeout)
        code = self._process.poll()
        if code is not None:
            self._mark_finished(code)
        return output

    def exitCode(self):
        return self._exit_code

    def _mark_finished(self, code):
        self._stop_monitoring()
        self._set_state(self.NotRunning)
        self._exit_code = int(code)
        if not self._finished_emitted:
            self._finished_emitted = True
            self.finished.emit(self._exit_code)

    def terminate(self):
        if self._process is not None and self.poll() is None:
            self._process.terminate()

    def kill(self):
        if self._process is not None and self.poll() is None:
            self._process.kill()

    def terminateTree(self):
        """Force the owned process tree down on Windows, process elsewhere."""
        if self._process is None or self.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            self.terminate()

    def close(self, timeout=0.0, *, force=False):
        """Close the owned process and reap its native handle.

        ``timeout`` is the graceful window.  When ``force`` is true a process
        still alive afterwards is terminated as a tree (important for
        ``cmd.exe -> abaqus -> SMALncMain -> SMAPython`` on Windows), then a
        short final wait reaps the Popen handle.  The method is idempotent and
        deliberately bounded so GUI close paths never block indefinitely.
        """
        if self._process is None:
            return
        try:
            if timeout and self.poll() is None:
                self.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        if force and self.poll() is None:
            self.terminateTree()
            try:
                self.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                # ``taskkill /T /F`` normally makes this unreachable.  Keep a
                # direct kill fallback for non-standard process wrappers.
                try:
                    self.kill()
                    self.wait(timeout=0.25)
                except Exception:
                    pass
        else:
            self.poll()

    def delete(self):
        # QObject deletion must not unexpectedly kill a running helper. Host
        # services own termination policy explicitly through ``close``.
        self._stop_monitoring()
        super().delete()


__all__ = ["QProcess"]
