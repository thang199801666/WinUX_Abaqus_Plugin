from __future__ import annotations

import os
from pathlib import Path
import threading

import dearpygui.dearpygui as dpg

from .qt_dialog import QtDialog
from .theme import DialogMetrics
from ..widgets import QtListItem, QtListView


class LocalFolderDialog(QtDialog):
    """Dear ImGui/Dear PyGui local-folder browser.

    This replaces the historical external native folder-picker helper. Directory I/O
    is performed on a small worker thread owned by the dialog process while all
    widgets and selection state stay on the Dear PyGui UI thread.
    """

    def __init__(self, view, initial, on_result):
        self.on_result = on_result
        self._finished = False
        self._generation = 0
        self._current_path = self._normalize_initial(initial)
        self._entries = {}
        super().__init__(view, "Open Folder", 560, 430)
        self.preferred_size = (540, 400)

        self.header(
            "Choose local folder",
            "Select the current folder or double-click a child folder to browse into it.",
        )
        self.path_edit = self.field(
            "Folder",
            self._current_path,
            parent=self.content,
            on_enter=True,
            callback=lambda *_args: self._navigate_typed(),
        )

        with dpg.group(
            parent=self.content,
            horizontal=True,
            horizontal_spacing=DialogMetrics.BUTTON_GAP,
        ) as nav_actions:
            self.action("Up", self._go_up, "secondary", parent=nav_actions)
            self.action("Refresh", self._refresh, "secondary", parent=nav_actions)

        self.listbox = self.own_widget(
            QtListView(
                self.content,
                [],
                width=-1,
                height=-1,
                multiple=False,
                after=self.view.after,
                backend=dpg,
            )
        )
        self.listbox.activated.connect(self._enter_key)
        self.status = self.status_text("")
        self.button_box([
            ("Select Folder", self._select_folder, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ])
        self._refresh()

    @staticmethod
    def _normalize_initial(initial):
        value = str(initial or os.getcwd())
        try:
            value = os.path.abspath(os.path.normpath(value))
        except Exception:
            value = os.getcwd()
        if not os.path.isdir(value):
            value = os.getcwd()
        return value

    def _navigate_typed(self):
        value = str(dpg.get_value(self.path_edit) or "").strip()
        if not value:
            return
        try:
            candidate = os.path.abspath(os.path.normpath(value))
        except Exception:
            candidate = value
        if not os.path.isdir(candidate):
            dpg.set_value(self.status, "Folder does not exist: {}".format(candidate))
            return
        self._current_path = candidate
        dpg.set_value(self.path_edit, candidate)
        self._refresh()

    def _go_up(self):
        parent = os.path.dirname(self._current_path.rstrip("\\/")) or self._current_path
        if parent != self._current_path and os.path.isdir(parent):
            self._current_path = parent
            dpg.set_value(self.path_edit, parent)
            self._refresh()

    def _refresh(self):
        if not self.winfo_exists():
            return
        self._generation += 1
        generation = self._generation
        path = self._current_path
        dpg.set_value(self.status, "Loading...")

        def worker():
            entries, error = [], None
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                entries.append((entry.name.casefold(), entry.name, entry.path))
                        except OSError:
                            continue
                entries.sort(key=lambda item: (item[0], item[1]))
            except (OSError, ValueError) as exc:
                error = str(exc)
            self.view.after(0, self._apply_entries, generation, path, entries, error)

        threading.Thread(
            target=worker,
            name="winux-local-folder-list",
            daemon=True,
        ).start()

    def _apply_entries(self, generation, path, entries, error):
        if not self.winfo_exists() or generation != self._generation:
            return
        if path != self._current_path:
            return
        if error:
            self._entries.clear()
            self.listbox.setItems([])
            dpg.set_value(self.status, error)
            return
        self._entries = {full_path: full_path for _, _, full_path in entries}
        self.listbox.setItems([
            QtListItem(full_path, name, full_path)
            for _, name, full_path in entries
        ])
        dpg.set_value(
            self.status,
            "{} folder(s) | Current: {}".format(len(entries), self._current_path),
        )

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if path and os.path.isdir(path):
            self._current_path = os.path.abspath(path)
            dpg.set_value(self.path_edit, self._current_path)
            self._refresh()

    def _select_folder(self):
        # If the user selected a child row, select that directory; otherwise
        # select the folder shown in the path editor.  This matches the useful
        # part of a native choose-folder dialog without introducing another UI
        # toolkit into WinUx.
        selected = self.listbox.currentData()
        path = selected if selected and os.path.isdir(str(selected)) else self._current_path
        self.finish(str(path) if path else None)

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _close_from_escape = lambda self: self.finish(None)
