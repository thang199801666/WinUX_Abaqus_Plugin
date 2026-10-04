"""Asynchronous, process-isolated ownership of the local folder picker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

try:
    from ..runtime.child_processes import (
        register_child_process, unregister_child_process,
    )
except ImportError:  # direct-module tests/legacy embedding
    def register_child_process(process, label="helper"):
        del label
        return process

    def unregister_child_process(_process_or_pid):
        return None


class FolderChooser:
    """UI-thread owner; the reader thread only queues plain result data."""

    def __init__(self, dispatch, on_error):
        self._dispatch = dispatch
        self._on_error = on_error
        self._process = None
        self._closed = False

    def open(self, initial, on_selected):
        if self._closed or self._process is not None:
            return
        script = Path(__file__).with_name("folder_chooser_process.py")
        try:
            process = subprocess.Popen(
                [sys.executable, "-B", str(script), str(initial or os.getcwd())],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            register_child_process(process, "folder-chooser")
        except OSError as exc:
            self._on_error("Open Folder", str(exc))
            return
        self._process = process

        def read_result():
            path, error = "", None
            try:
                output, stderr = process.communicate()
                if process.returncode:
                    detail = stderr.decode("utf-8", errors="replace").strip()
                    raise RuntimeError("Folder chooser exited with code {}. {}".format(
                        process.returncode, detail[-2000:]))
                result = json.loads(output.decode("ascii"))
                if not isinstance(result, dict):
                    raise ValueError("Invalid folder chooser response")
                if "error" in result:
                    raise RuntimeError(str(result["error"]))
                path = result["path"]
                if not isinstance(path, str):
                    raise ValueError("Invalid folder path in chooser response")
            except Exception as exc:
                error = str(exc)
            self._dispatch(0, self._complete, process, path, error, on_selected)

        threading.Thread(target=read_result, name="winux-folder-chooser",
                         daemon=True).start()

    def _complete(self, process, path, error, on_selected):
        unregister_child_process(process)
        if self._closed or self._process is not process:
            return
        self._process = None
        if error:
            self._on_error("Open Folder", error)
        elif path:
            path = os.path.abspath(os.path.normpath(path))
            if os.path.isdir(path):
                on_selected(path)
            else:
                self._on_error("Open Folder", "Folder no longer exists: " + path)

    def close(self):
        self._closed = True
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass  # The dialog may have exited between poll and terminate.
        elif process is not None:
            unregister_child_process(process)
