from __future__ import annotations

"""Standalone Tkinter direct-on-server editor for WinUx.

This module runs in its own child process and owns a normal ``tk.Tk`` desktop
window.  WinUx keeps the SSH/SFTP connection in the parent process; the editor
exchanges load/save/reload requests through JSON-lines IPC.  Tabs are queued
and loaded one at a time, and large text buffers are inserted in small Tk
chunks so opening several server files does not stall or crash the main app.

No working copy is created on the workstation.  Save continues to use the
server model's SHA-256 conflict detection, staged write, checksum verification
and atomic server-side publish.
"""

import base64
import json
import os
import queue
import re
import sys
import threading
import time
import zlib
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Dict, Optional

import tkinter as tk
from tkinter import font as font_module
from tkinter import ttk

# This module is launched as a standalone script.  Add the package root so it
# can share WinUx's modern dialog framework instead of falling back to native
# tkinter messagebox/simpledialog windows.
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))
from WinUx.components.server_notepad_tabs import _ToolTip, _EditorTabStrip
from WinUx.components.shared_scroller import (
    configure_ttk_scroller_styles, make_ttk_scroller,
)
from WinUx.dialogs.modern import (
    FixedActionButton,
    ModernDialogMetrics,
    ModernDialogPalette,
    ask_modern_choice,
    ask_modern_confirm,
    ask_modern_integer,
    ask_modern_text,
    configure_modern_ttk_styles,
    fit_and_center_toplevel,
    prepare_modern_toplevel,
    show_modern_message,
)
from WinUx.services.server_notepad_background import ServerNotepadBackgroundMixin
from WinUx.services.server_notepad_loading import (
    ServerNotepadLoadingMixin, _language_for_path,
)
from WinUx.services.server_notepad_save import ServerNotepadSaveMixin
from WinUx.services.server_notepad_state import ServerNotepadStateMixin
from WinUx.services.server_notepad_windowing import ServerNotepadWindowingMixin
from WinUx.services.server_notepad_editor import ServerNotepadEditorMixin
from WinUx.services.server_notepad_search import ServerNotepadSearchController
from WinUx.services.server_notepad_highlight import ServerNotepadHighlighter
from WinUx.services.server_notepad_layout import ServerNotepadLayout
from WinUx.services.server_notepad_commands import ServerNotepadCommandMixin
from WinUx.services.server_notepad_ipc import ServerNotepadProcessBridge as _ProcessBridge
from WinUx.services.server_notepad_types import (
    _Document, _ENCODING_LABELS, _ENCODING_VALUES, _EOL_NAMES,
)
















class ServerNotepadWindow(
        ServerNotepadWindowingMixin, ServerNotepadStateMixin,
        ServerNotepadLoadingMixin, ServerNotepadSaveMixin,
        ServerNotepadBackgroundMixin, ServerNotepadEditorMixin,
        ServerNotepadCommandMixin, tk.Tk):
    """Standalone Notepad++-style server editor window."""

    WIDTH = 1120
    HEIGHT = 760
    MIN_WIDTH = 760
    MIN_HEIGHT = 500

    # Tk's Text widget is responsive when work is sliced into short idle-time
    # batches.  Keep both IPC and rendering below a single 60 Hz frame budget.
    IPC_PUMP_BUDGET_MS = 6.0
    IPC_PUMP_MAX_MESSAGES = 4
    RENDER_BUDGET_MS = 7.0
    RENDER_SLICE_CHARS = 64 * 1024
    RENDER_SLICE_MIN_CHARS = 16 * 1024
    RENDER_SLICE_MAX_CHARS = 256 * 1024
    SAVE_EXPORT_SLICE_CHARS = 256 * 1024
    PERFORMANCE_MODE_BYTES = 2 * 1024 * 1024
    PROGRESS_UI_INTERVAL = 0.080
    RECENT_FILE_LIMIT = 10

    def __init__(self, bridge):
        super().__init__()
        self.owner = bridge
        self.root = self
        self.withdraw()
        try:
            self._owner_hwnd = int(
                os.environ.get("WINUX_SERVER_NOTEPAD_OWNER_HWND") or 0)
        except Exception:
            self._owner_hwnd = 0
        self._explicit_open_seen = False
        self._session_restore_started = False
        self._documents: Dict[str, _Document] = {}
        self._tab_to_path: Dict[str, str] = {}
        self._load_queue = deque()
        self._current_load_path = None
        self._font_size = 10
        self._show_statusbar = tk.BooleanVar(master=self, value=True)
        self._show_line_numbers = tk.BooleanVar(master=self, value=True)
        self._show_document_list = tk.BooleanVar(master=self, value=False)
        self._show_function_list = tk.BooleanVar(master=self, value=False)
        self._highlight_current_line = tk.BooleanVar(master=self, value=True)
        self._word_wrap = tk.BooleanVar(master=self, value=False)
        self._encoding_var = tk.StringVar(master=self, value="UTF-8")
        self._eol_var = tk.StringVar(master=self, value="Unix (LF)")
        self._language_var = tk.StringVar(master=self, value="Normal Text")
        self._status_var = tk.StringVar(master=self, value="Ready")
        self._position_var = tk.StringVar(master=self, value="Ln 1, Col 1")
        self._mode_var = tk.StringVar(master=self, value="INS")
        self._stats_var = tk.StringVar(master=self, value="length: 0   lines: 1")
        self._length_var = tk.StringVar(master=self, value="length: 0")
        self._lines_var = tk.StringVar(master=self, value="lines: 1")
        self._zoom_var = tk.StringVar(master=self, value="100%")
        self._format_var = tk.StringVar(master=self, value="Unix (LF)   UTF-8")
        self._find_window = None
        self._find_vars = {}
        self._function_after = None
        self._toolbar_images = {}
        self._tab_strip = None
        self._session_snapshot = None
        self._state_save_after = None
        self._restore_session = tk.BooleanVar(master=self, value=True)
        self._layout = ServerNotepadLayout(self)
        self._highlighter = ServerNotepadHighlighter(self)
        self._search = ServerNotepadSearchController(self, ask_modern_text)
        self._search_generation = 0
        self._search_results_meta = []
        self._search_state = None
        self._background_events = queue.Queue()
        self._recent_paths = []
        self._state = self._load_local_state()
        self._recent_paths = list(self._state.get("recent_paths") or [])[:self.RECENT_FILE_LIMIT]
        self._font_size = int(self._state.get("font_size") or self._font_size)
        self._show_line_numbers.set(bool(self._state.get("line_numbers", True)))
        self._highlight_current_line.set(bool(self._state.get("highlight_current_line", True)))
        self._word_wrap.set(bool(self._state.get("word_wrap", False)))
        self._show_document_list.set(bool(self._state.get("document_list", False)))
        self._show_function_list.set(bool(self._state.get("function_list", False)))
        self._restore_session.set(bool(self._state.get("restore_session", True)))
        self._load_progress_var = tk.DoubleVar(master=self, value=0.0)
        self._build_window()
        self.update_idletasks()
        width, height = self._restored_window_size()
        # Persist size, not absolute coordinates.  A saved +x+y from another
        # monitor/session can put the editor completely off-screen while the
        # child process remains alive and continues requesting server files.
        self.geometry("{}x{}".format(width, height))
        self.deiconify()
        self.update_idletasks()
        self._activate_native_window(center=True)
        self.after(20, self.owner.pump)
        self.after(35, self._pump_background_events)
        # Session tabs are restored only after the launching queue_open arrives.
        # They are lazy tabs and therefore can never pre-empt the file the user
        # just selected in WinUx.
        if self._restore_session.get():
            self.after(250, self._restore_session_tabs)

    def _show_load_progress(self, show=True, value=None):
        return self._layout._show_load_progress(show, value)

    def _build_dock_header(self, parent, title, close_command):
        return self._layout._build_dock_header(parent, title, close_command)

    def _build_window(self):
        return self._layout._build_window()

    def _build_menu(self):
        return self._layout._build_menu()

    def _build_toolbar(self):
        return self._layout._build_toolbar()


    # ------------------------------------------------------------------
    # Documents / tabs
    # ------------------------------------------------------------------
    def _open_server_path(self):
        active = self._active_doc()
        initial = str(active.path if active is not None else "")
        path = ask_modern_text(
            self.root, "Open Server Path", "Remote file path:",
            initialvalue=initial, heading="Open file from server",
            primary_text="Open", secondary_text="Cancel",
            detail="Enter an absolute remote path. The file will load into a new tab."
        )
        if path:
            self._queue_open_ui(str(path).strip())

    def _queue_open_ui(self, path, session_restore=False):
        path = str(path or "").strip()
        if not path:
            return
        if not session_restore:
            self._explicit_open_seen = True
            self._remember_recent_path(path)
        existing = self._documents.get(path)
        if existing is not None:
            # An explicit request always takes ownership away from automatic
            # session restore.  This is important when a restored file failed
            # transiently and the user selects the known-good server entry.
            if not session_restore:
                existing.session_restore = False
            self._select_doc(existing)
            self.deiconify()
            self.lift()
            if existing.loaded:
                existing.text.focus_set()
            elif existing.loading:
                # The request is already in flight.  Merely activate its tab;
                # queuing the same path twice can interleave two streams.
                self._set_doc_status(existing, "Reading from server...")
            else:
                # Previous behaviour returned here when a load had failed.
                # That left the document permanently unloaded (queued=False,
                # loading=False) so opening the same *existing* server file a
                # second time appeared to hang.  Re-arm the failed/unloaded
                # tab instead of requiring the user to close it manually.
                if not existing.queued:
                    existing.queued = True
                    existing.busy = True
                    existing.pending_operation = "load"
                    existing.status_message = "Queued for server load..."
                    existing.render_chunks.clear()
                    existing.stream_end_pending = False
                    existing.stream_end_meta = {}
                    try:
                        existing.text.configure(state="normal")
                        existing.text.delete("1.0", "end")
                        existing.text.insert("1.0", "Loading from server...\n")
                        existing.text.edit_modified(False)
                        existing.text.configure(state="disabled")
                    except Exception:
                        pass
                    if path not in self._load_queue:
                        self._load_queue.append(path)
                    self._set_doc_status(existing, "Queued for server load...")
                    self._update_tab_title(existing)
                if self._current_load_path is None:
                    self._start_next_load()
            return

        lazy_restore = bool(session_restore)
        doc = _Document(
            path=path, encoding="utf-8", signature={}, original_text="",
            original_encoding="utf-8", eol="\n", original_eol="\n",
            size=0, language=_language_for_path(path), busy=not lazy_restore,
            pending_operation="" if lazy_restore else "load",
            queued=not lazy_restore,
            session_restore=lazy_restore,
            status_message=(
                "Restored tab - select to load" if lazy_restore
                else "Queued for server load..."),
        )
        previous = self._active_doc()
        self._create_editor_tab(doc)
        self._documents[path] = doc
        self._tab_to_path[str(doc.frame)] = path
        self.notebook.add(doc.frame, text=self._tab_title(doc, include_close=False))
        if not lazy_restore or previous is None:
            self.notebook.select(doc.frame)
        elif previous.frame is not None:
            self.notebook.select(previous.frame)
        self._rebuild_tab_strip()
        self._refresh_document_list()
        doc.text.configure(state="normal")
        doc.text.insert(
            "1.0",
            ("Restored server tab. Select this tab to load the current "
             "server contents.\n") if lazy_restore
            else "Loading from server...\n")
        doc.text.edit_modified(False)
        doc.text.configure(state="disabled")
        if not lazy_restore:
            # Explicit user opens outrank any pending lazy restore work.
            self._load_queue.appendleft(path)
        self._sync_active_ui()
        self._activate_native_window(center=False)
        if not lazy_restore:
            self._start_next_load()

































    # ------------------------------------------------------------------
    # Direct server Save / Reload lifecycle
    # ------------------------------------------------------------------













    # ------------------------------------------------------------------
    # Closing / unsaved changes
    # ------------------------------------------------------------------












    # ------------------------------------------------------------------
    # Notepad++-style editing commands
    # ------------------------------------------------------------------
























    def _show_style_configurator(self):
        value = ask_modern_integer(
            self.root, "Style Configurator", "Editor font size:",
            initialvalue=self._font_size, minvalue=7, maxvalue=28,
            heading="Editor font size")
        if value is not None:
            self._set_zoom(value)

    def _show_preferences(self):
        dialog = tk.Toplevel(self.root)
        prepare_modern_toplevel(dialog, "Preferences")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=ModernDialogPalette.WINDOW)

        outer = tk.Frame(dialog, background=ModernDialogPalette.WINDOW, borderwidth=0)
        outer.pack(fill="both", expand=True)
        body = tk.Frame(outer, background=ModernDialogPalette.SURFACE, borderwidth=0)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, text="Editor preferences", style="WinUxDialog.Title.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        options = ttk.Frame(body, style="WinUxDialog.Surface.TFrame")
        options.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        ttk.Checkbutton(options, text="Show document list", variable=self._show_document_list,
                        command=self._apply_document_list_visibility).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(options, text="Show function list", variable=self._show_function_list,
                        command=self._apply_function_list_visibility).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(options, text="Highlight current line", variable=self._highlight_current_line,
                        command=self._apply_current_line_highlight).grid(row=2, column=0, sticky="w", pady=4)
        ttk.Checkbutton(options, text="Word wrap", variable=self._word_wrap,
                        command=self._apply_word_wrap).grid(row=3, column=0, sticky="w", pady=4)
        ttk.Checkbutton(options, text="Restore previous server tabs on startup",
                        variable=self._restore_session, command=self._save_local_state).grid(
                            row=4, column=0, sticky="w", pady=4)
        tk.Frame(outer, height=1, background=ModernDialogPalette.BORDER).pack(fill="x")
        footer = tk.Frame(outer, background=ModernDialogPalette.FOOTER, borderwidth=0)
        footer.pack(fill="x")
        close_button = FixedActionButton(footer, "Close", dialog.destroy, role="primary")
        close_button.pack(side="right", padx=16, pady=12)
        dialog.bind("<Escape>", lambda _e: dialog.destroy(), add="+")
        fit_and_center_toplevel(
            dialog, self.root, min_width=430, min_height=255)
        dialog.grab_set()
        close_button.focus_set()

    def _zoom_in(self):
        self._set_zoom(self._font_size + 1)

    def _zoom_out(self):
        self._set_zoom(self._font_size - 1)

    def _zoom_reset(self):
        self._set_zoom(10)

    def _set_zoom(self, size):
        self._font_size = max(7, min(28, int(size)))
        for doc in self._documents.values():
            try:
                current_font = font_module.Font(font=doc.text.cget("font"))
                current_font.configure(size=self._font_size)
                doc.text.configure(font=current_font)
            except Exception:
                doc.text.configure(font=(self._preferred_editor_font(), self._font_size))
            self._update_line_numbers(doc)
        percent = int(self._font_size / 10.0 * 100)
        self._zoom_var.set("{}%".format(percent))
        self._status_var.set("Zoom: {}%".format(percent))

    def _mouse_zoom(self, event):
        if event.delta > 0:
            self._zoom_in()
        elif event.delta < 0:
            self._zoom_out()
        return "break"

    def _copy_server_path(self):
        doc = self._active_doc()
        if doc is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(doc.path)
        self._status_var.set("Server path copied")

    def _toggle_bookmark_from_gutter(self, event, doc):
        if doc is None or doc.text is None or not doc.loaded:
            return "break"
        try:
            index = doc.text.index("@0,{}".format(int(event.y)))
            line = int(index.split(".")[0])
        except Exception:
            return "break"
        if line in doc.bookmarks:
            doc.bookmarks.discard(line)
        else:
            doc.bookmarks.add(line)
        self._update_line_numbers(doc)
        return "break"

    def _toggle_bookmark(self):
        doc = self._active_doc()
        if doc is None or not doc.loaded:
            return
        try:
            line = int(doc.text.index("insert").split(".")[0])
        except Exception:
            return
        if line in doc.bookmarks:
            doc.bookmarks.discard(line)
        else:
            doc.bookmarks.add(line)
        self._update_line_numbers(doc)

    def _goto_bookmark(self, direction=1):
        doc = self._active_doc()
        if doc is None or not doc.bookmarks:
            self._status_var.set("No bookmarks in current document")
            return
        try:
            current = int(doc.text.index("insert").split(".")[0])
        except Exception:
            current = 1
        ordered = sorted(doc.bookmarks)
        if int(direction) >= 0:
            candidates = [line for line in ordered if line > current]
            target = candidates[0] if candidates else ordered[0]
        else:
            candidates = [line for line in ordered if line < current]
            target = candidates[-1] if candidates else ordered[-1]
        index = "{}.0".format(target)
        doc.text.mark_set("insert", index)
        doc.text.see(index)
        doc.text.focus_set()
        self._on_editor_activity(doc)

    def _clear_bookmarks(self):
        doc = self._active_doc()
        if doc is None:
            return
        doc.bookmarks.clear()
        self._update_line_numbers(doc)

    def _goto_line(self):
        doc = self._active_doc()
        if doc is None:
            return
        try:
            max_line = int(doc.text.index("end-1c").split(".")[0])
        except Exception:
            max_line = 1
        line = ask_modern_integer(
            self.root, "Go to Line",
            "Line number (1 - {}):".format(max_line),
            initialvalue=1, minvalue=1, maxvalue=max_line,
            heading="Go to line")
        if line is None:
            return
        index = "{}.0".format(line)
        doc.text.mark_set("insert", index)
        doc.text.see(index)
        doc.text.focus_set()
        self._update_position(doc)

    def _about(self):
        show_modern_message(
            self.root, "About WinUx Server Notepad",
            "Tkinter direct-on-server text editor with a Notepad++-style interface.\n\n"
            "Files are read and saved through WinUx SSH/SFTP. Save uses conflict detection, "
            "checksum verification and atomic server-side replacement.",
            intent="info", heading="WinUx Server Notepad++")

    @property
    def _search_generation(self):
        return self._search._search_generation

    @_search_generation.setter
    def _search_generation(self, value):
        self._search._search_generation = value

    @property
    def _search_results_meta(self):
        return self._search._search_results_meta

    @_search_results_meta.setter
    def _search_results_meta(self, value):
        self._search._search_results_meta = value

    @property
    def _search_state(self):
        return self._search._search_state

    @_search_state.setter
    def _search_state(self, value):
        self._search._search_state = value

    def _close_search_results(self):
        return self._search._close_search_results()

    def _find_all_current(self):
        return self._search._find_all_current()

    def _find_all_step(self):
        return self._search._find_all_step()

    def _goto_search_result(self, _event=None):
        return self._search._goto_search_result(_event=_event)

    # ------------------------------------------------------------------
    # Find / Replace
    # ------------------------------------------------------------------
    def _show_find_replace(self, replace=False):
        if self._find_window is not None:
            try:
                if self._find_window.winfo_exists():
                    self._find_window.deiconify()
                    self._find_window.lift()
                    if replace:
                        self._find_vars["replace_frame"].grid()
                        self._find_vars["replace_button"].pack(side="left", padx=3)
                        self._find_vars["replace_all_button"].pack(side="left", padx=3)
                        self._find_window.title("Replace")
                    else:
                        self._find_vars["replace_frame"].grid_remove()
                        self._find_vars["replace_button"].pack_forget()
                        self._find_vars["replace_all_button"].pack_forget()
                        self._find_window.title("Find")
                    self._find_vars["find_entry"].focus_set()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._find_window = win
        prepare_modern_toplevel(win, "Replace" if replace else "Find")
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        win.configure(background=ModernDialogPalette.WINDOW)

        body = tk.Frame(win, background=ModernDialogPalette.SURFACE, padx=14, pady=12)
        body.grid(row=0, column=0, sticky="nsew")
        ttk.Label(body, text="Find what:").grid(row=0, column=0, sticky="w", pady=3)
        find_var = tk.StringVar(value=self._active_doc().last_find if self._active_doc() else "")
        find_entry = ttk.Entry(body, width=42, textvariable=find_var)
        find_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)

        replace_frame = ttk.Frame(body)
        replace_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        ttk.Label(replace_frame, text="Replace with:").grid(row=0, column=0, sticky="w", pady=3)
        replace_var = tk.StringVar()
        replace_entry = ttk.Entry(replace_frame, width=42, textvariable=replace_var)
        replace_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
        if not replace:
            replace_frame.grid_remove()

        options = ttk.Frame(body)
        options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 4))
        match_case = tk.BooleanVar(value=False)
        regex = tk.BooleanVar(value=False)
        wrap = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Match case", variable=match_case).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(options, text="Regular expression", variable=regex).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(options, text="Wrap around", variable=wrap).pack(side="left")

        actions = tk.Frame(body, background=ModernDialogPalette.SURFACE, borderwidth=0)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", pady=(10, 0))
        find_next_button = FixedActionButton(
            actions, "Find Next", lambda: self._find_from_dialog(True),
            role="primary", width=104)
        find_next_button.pack(side="left", padx=(0, 6))
        find_previous_button = FixedActionButton(
            actions, "Find Previous", lambda: self._find_from_dialog(False),
            role="secondary", width=110)
        find_previous_button.pack(side="left", padx=(0, 6))
        replace_button = FixedActionButton(
            actions, "Replace", self._replace_one, role="primary", width=94)
        replace_all_button = FixedActionButton(
            actions, "Replace All", self._replace_all, role="primary", width=100)
        replace_button.pack(side="left", padx=(0, 6))
        replace_all_button.pack(side="left", padx=(0, 6))
        close_button = FixedActionButton(
            actions, "Close", win.withdraw, role="secondary", width=86)
        close_button.pack(side="left")
        if not replace:
            replace_button.pack_forget()
            replace_all_button.pack_forget()

        fit_and_center_toplevel(
            win, self.root, min_width=580, min_height=205)

        self._find_vars = {
            "find": find_var,
            "replace": replace_var,
            "case": match_case,
            "regex": regex,
            "wrap": wrap,
            "find_entry": find_entry,
            "replace_frame": replace_frame,
            "replace_button": replace_button,
            "replace_all_button": replace_all_button,
        }
        find_entry.bind("<Return>", lambda _e: self._find_from_dialog(True))
        win.bind("<Escape>", lambda _e: win.withdraw())
        find_entry.focus_set()

    def _find_from_dialog(self, forward=True):
        return self._search._find_from_dialog(forward=forward)

    def _find_next(self, forward=True, needle=None, match_case=None, regex=None, wrap=None):
        return self._search._find_next(forward=forward, needle=needle, match_case=match_case, regex=regex, wrap=wrap)

    def _replace_one(self):
        return self._search._replace_one()

    def _replace_all(self):
        return self._search._replace_all()

    # ------------------------------------------------------------------
    # Syntax highlighting.  Deliberately lightweight and dependency-free.
    # ------------------------------------------------------------------
    def _configure_syntax_tags(self, doc):
        return self._highlighter._configure_syntax_tags(doc=doc)

    def _schedule_highlight(self, doc, immediate=False):
        return self._highlighter._schedule_highlight(doc=doc, immediate=immediate)

    def _highlight_document(self, doc):
        return self._highlighter._highlight_document(doc=doc)




def main():
    import traceback
    bridge = _ProcessBridge()
    try:
        window = ServerNotepadWindow(bridge)
        bridge.attach(window)
        window.report_callback_exception = lambda exc, value, tb: (
            traceback.print_exception(exc, value, tb, file=sys.stderr)
        )
        window.mainloop()
    except Exception as exc:
        try:
            bridge._send({"event": "error", "message": str(exc)})
        except Exception:
            pass
        raise
    finally:
        try:
            bridge.notify_closed()
        except Exception:
            pass


if __name__ == "__main__":
    main()
