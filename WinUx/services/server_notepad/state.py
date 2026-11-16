from __future__ import annotations

"""Persistent session/recent-file state for the standalone Server Notepad."""

import json
import os
from pathlib import Path, PurePosixPath


class ServerNotepadStateMixin:
    @staticmethod
    def _state_path():
        """Return a per-user local state file; never writes into the plug-in tree."""
        base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "")
        if base:
            return Path(base) / "WinUx" / "server_notepad_state.json"
        return Path.home() / ".winux" / "server_notepad_state.json"

    def _load_local_state(self):
        path = self._state_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_local_state(self):
        try:
            path = self._state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if self._session_snapshot is not None:
                open_paths = list(self._session_snapshot.get("open_paths") or [])
                active_path = str(self._session_snapshot.get("active_path") or "")
            else:
                open_paths = [doc.path for doc in self._documents.values()]
                active = self._active_doc()
                active_path = active.path if active is not None else ""
            state = {
                "geometry": str(self.geometry()),
                "font_size": int(self._font_size),
                "line_numbers": bool(self._show_line_numbers.get()),
                "highlight_current_line": bool(self._highlight_current_line.get()),
                "word_wrap": bool(self._word_wrap.get()),
                "document_list": bool(self._show_document_list.get()),
                "function_list": bool(self._show_function_list.get()),
                "restore_session": bool(self._restore_session.get()),
                "open_paths": open_paths[:24],
                "active_path": active_path,
                "recent_paths": list(self._recent_paths[:self.RECENT_FILE_LIMIT]),
            }
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(temporary), str(path))
        except Exception:
            pass

    def _restore_session_tabs(self):
        if not self._restore_session.get() or self._session_restore_started:
            return
        # Never allow a timer-based session restore to beat the explicit path
        # sent by WinUx.  If the parent UI is momentarily busy, simply retry.
        if not self._explicit_open_seen:
            self.after(250, self._restore_session_tabs)
            return
        self._session_restore_started = True
        paths = [str(value) for value in (self._state.get("open_paths") or []) if str(value).strip()]
        for path in paths[:24]:
            if path not in self._documents:
                self._queue_open_ui(path, session_restore=True)

    def _schedule_state_save(self, delay=240):
        if self._state_save_after is not None:
            try:
                self.after_cancel(self._state_save_after)
            except Exception:
                pass
            self._state_save_after = None
        try:
            self._state_save_after = self.after(
                max(0, int(delay)), self._run_state_save)
        except Exception:
            pass

    def _run_state_save(self):
        self._state_save_after = None
        self._save_local_state()

    def _remember_recent_path(self, path):
        path = str(path or "").strip()
        if not path:
            return
        self._recent_paths = [value for value in self._recent_paths if value != path]
        self._recent_paths.insert(0, path)
        del self._recent_paths[self.RECENT_FILE_LIMIT:]
        self._rebuild_recent_menu()
        self._save_local_state()

    def _rebuild_recent_menu(self):
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        try:
            menu.delete(0, "end")
            if not self._recent_paths:
                menu.add_command(label="(Empty)", state="disabled")
                return
            for path in self._recent_paths[:self.RECENT_FILE_LIMIT]:
                label = PurePosixPath(path).name or path
                menu.add_command(
                    label="{}    {}".format(label, path),
                    command=lambda p=path: self._queue_open_ui(p))
            menu.add_separator()
            menu.add_command(label="Clear Recent File List", command=self._clear_recent_paths)
        except Exception:
            pass

    def _clear_recent_paths(self):
        self._recent_paths = []
        self._rebuild_recent_menu()
        self._save_local_state()

