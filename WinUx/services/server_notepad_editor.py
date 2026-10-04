from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional

import tkinter as tk
from tkinter import font as font_module
from tkinter import ttk

from WinUx.components.shared_scroller import make_ttk_scroller
from WinUx.dialogs.modern import ask_modern_choice, show_modern_message
from WinUx.services.server_notepad_types import _Document, _ENCODING_LABELS, _EOL_NAMES


class ServerNotepadEditorMixin:
    """Document tabs, editor widgets, presentation state and tab lifecycle."""

    def _create_editor_tab(self, doc):
        frame = ttk.Frame(self.notebook)
        doc.frame = frame

        editor_area = ttk.Frame(frame)
        editor_area.pack(fill="both", expand=True)
        doc.editor_frame = editor_area
        editor_area.rowconfigure(0, weight=1)
        editor_area.columnconfigure(1, weight=1)

        gutter = tk.Canvas(
            editor_area,
            width=52,
            highlightthickness=0,
            borderwidth=0,
            background="#f1f1f1",
        )
        gutter.grid(row=0, column=0, sticky="ns")
        doc.line_numbers = gutter
        gutter.bind(
            "<Button-1>",
            lambda event, d=doc: self._toggle_bookmark_from_gutter(event, d),
            add="+",
        )

        editor_font = font_module.Font(
            family=self._preferred_editor_font(), size=self._font_size)
        text = tk.Text(
            editor_area,
            wrap="none",
            undo=True,
            maxundo=-1,
            autoseparators=True,
            font=editor_font,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            padx=7,
            pady=5,
            background="#ffffff",
            foreground="#202020",
            insertbackground="#202020",
            selectbackground="#cce8ff",
            selectforeground="#000000",
            tabs=("2c",),
        )
        text.grid(row=0, column=1, sticky="nsew")
        doc.text = text

        yscroll = make_ttk_scroller(ttk, editor_area, orient="vertical")
        yscroll.grid(row=0, column=2, sticky="ns")
        doc.yscroll = yscroll

        xscroll = make_ttk_scroller(ttk, editor_area, orient="horizontal")
        xscroll.grid(row=1, column=1, sticky="ew")
        doc.xscroll = xscroll

        def yview(*args):
            text.yview(*args)
            if not doc.loading:
                self._schedule_line_numbers(doc)
                self._schedule_highlight(doc)

        def on_yscroll(first, last):
            yscroll.set(first, last)
            if not doc.loading:
                self._schedule_line_numbers(doc)
                self._schedule_highlight(doc)

        yscroll.configure(command=yview)
        text.configure(yscrollcommand=on_yscroll, xscrollcommand=xscroll.set)
        xscroll.configure(command=text.xview)

        text.bind("<<Modified>>", lambda _e, d=doc: self._on_modified(d), add="+")
        text.bind("<KeyRelease>", lambda _e, d=doc: self._on_editor_activity(d), add="+")
        text.bind("<ButtonRelease-1>", lambda _e, d=doc: self._on_editor_activity(d), add="+")
        text.bind("<Configure>", lambda _e, d=doc: self._schedule_line_numbers(d), add="+")
        text.bind("<MouseWheel>", lambda _e, d=doc: self._schedule_line_numbers(d, 8), add="+")
        text.bind("<Button-4>", lambda _e, d=doc: self._schedule_line_numbers(d, 8), add="+")
        text.bind("<Button-5>", lambda _e, d=doc: self._schedule_line_numbers(d, 8), add="+")
        text.bind("<Control-MouseWheel>", self._mouse_zoom, add="+")
        text.bind("<Tab>", self._insert_tab_spaces, add="+")
        text.bind("<Button-3>", lambda e, d=doc: self._editor_context_menu(e, d), add="+")

        self._apply_word_wrap_to_doc(doc)
        self._apply_line_number_visibility_to_doc(doc)

    @staticmethod
    def _preferred_editor_font():
        families = set(font_module.families())
        for candidate in ("Consolas", "Cascadia Mono", "Courier New"):
            if candidate in families:
                return candidate
        return "TkFixedFont"

    def _active_doc(self) -> Optional[_Document]:
        try:
            selected = self.notebook.select()
        except Exception:
            return None
        if not selected:
            return None
        path = self._tab_to_path.get(str(selected))
        return self._documents.get(path)

    def _select_doc(self, doc):
        if doc is None:
            return
        try:
            self.notebook.select(doc.frame)
            self._sync_active_ui()
            self._sync_tab_strip()
            if doc.loaded:
                doc.text.focus_set()
        except Exception:
            pass

    def _sync_tab_strip(self):
        if self._tab_strip is None:
            return
        active = self._active_doc()
        active_path = active.path if active is not None else None
        for doc in self._documents.values():
            self._tab_strip.update_doc(doc, active_path)

    def _rebuild_tab_strip(self):
        if self._tab_strip is None:
            return
        active = self._active_doc()
        active_path = active.path if active is not None else None
        docs = []
        try:
            for tab_id in self.notebook.tabs():
                path = self._tab_to_path.get(str(tab_id))
                doc = self._documents.get(path)
                if doc is not None:
                    docs.append(doc)
        except Exception:
            docs = list(self._documents.values())
        self._tab_strip.rebuild(docs, active_path)

    def _doc_for_path(self, path):
        if path is not None:
            doc = self._documents.get(str(path))
            if doc is not None:
                return doc
        return self._active_doc()

    def _tab_title(self, doc, include_close=False):
        name = PurePosixPath(doc.path).name or doc.path or "Server file"
        marker = " *" if self._is_dirty(doc) else ""
        conflict = " !" if doc.conflict else ""
        loading = "  [loading]" if (doc.loading or doc.queued) and not doc.loaded else ""
        close = "   x" if include_close else ""
        return "{}{}{}{}{}".format(name, marker, conflict, loading, close)

    def _is_dirty(self, doc):
        if doc is None or doc.text is None or not doc.loaded:
            return False
        # Do not copy the full Tk text buffer on every key release.  Tk's
        # <<Modified>> event is the save-point signal for text edits, while
        # encoding/EOL changes are tracked independently.  This keeps editing
        # multi-megabyte INP/log files responsive.
        return bool(
            doc.dirty
            or doc.encoding != doc.original_encoding
            or doc.eol != doc.original_eol
        )

    def _update_tab_title(self, doc):
        try:
            self.notebook.tab(doc.frame, text=self._tab_title(doc, include_close=False))
        except Exception:
            pass
        active = self._active_doc()
        if self._tab_strip is not None:
            self._tab_strip.update_doc(doc, active.path if active is not None else None)
        if active is doc:
            self._update_window_title(doc)
        self._refresh_document_list()

    def _update_window_title(self, doc=None):
        doc = doc or self._active_doc()
        if doc is None:
            self.root.title("WinUx Server Notepad++")
            return
        marker = " *" if self._is_dirty(doc) else ""
        name = PurePosixPath(doc.path).name or doc.path
        self.root.title("{}{} - WinUx Server Notepad++".format(name, marker))

    def _on_tab_changed(self, _event=None):
        self._sync_active_ui()
        self._sync_tab_strip()
        self._refresh_document_list()
        doc = self._active_doc()
        if doc is not None:
            self._schedule_state_save()
            if (doc.session_restore and not doc.loaded and not doc.loading
                    and not doc.queued):
                # Restored tabs are deliberately lazy.  Selecting one converts
                # it into an explicit open and queues the current server file.
                self._queue_open_ui(doc.path, session_restore=False)
            self._prioritise_queued_doc(doc)
            self._schedule_line_numbers(doc)
            self.root.after_idle(lambda: self._highlight_active_line(doc))
            self._schedule_function_refresh(doc)

    def _sync_active_ui(self):
        doc = self._active_doc()
        if doc is None:
            self._status_var.set("No server file open")
            self._position_var.set("Ln -, Col -")
            self._format_var.set("")
            self._show_load_progress(False, 0.0)
            self._update_window_title(None)
            return
        self._encoding_var.set(_ENCODING_LABELS.get(doc.encoding, doc.encoding.upper()))
        self._eol_var.set(_EOL_NAMES.get(doc.eol, "Unix (LF)"))
        self._language_var.set(doc.language)
        self._status_var.set(doc.status_message or "Ready")
        if doc.loading:
            expected = max(1, int(doc.stream_expected_bytes or doc.stream_expected_chars or 0))
            received = int(doc.stream_received_bytes if doc.stream_expected_bytes else doc.stream_received_chars)
            self._show_load_progress(True, min(99.0, received * 100.0 / expected))
        else:
            self._show_load_progress(False)
        self._update_position(doc)
        self._update_stats(doc)
        self._update_format_status(doc)
        self._update_window_title(doc)
        self._highlight_active_line(doc)

    def _on_modified(self, doc):
        try:
            modified = bool(doc.text.edit_modified())
            doc.text.edit_modified(False)
        except Exception:
            modified = True
        if not modified:
            return
        # Programmatic streaming/insertion must not mark a freshly opened file
        # dirty.  User edits after the load completes do.
        if doc.loading or not doc.loaded:
            return
        doc.dirty = True
        # The immutable load index is no longer the current document after the
        # first edit.  Drop it immediately to reclaim memory and avoid stale
        # Find All / Function List results.
        doc.snapshot_text = ""
        doc.snapshot_parts = []
        doc.line_offsets = []
        doc.function_entries = []
        doc.index_ready = False
        doc.index_generation += 1
        doc.status_message = "Modified"
        self._update_tab_title(doc)
        self._update_position(doc)
        self._update_stats(doc)
        self._schedule_highlight(doc)
        self._schedule_line_numbers(doc)
        self._schedule_function_refresh(doc)

    def _on_editor_activity(self, doc):
        self._update_position(doc)
        self._schedule_line_numbers(doc)
        self._highlight_active_line(doc)
        self._schedule_highlight(doc)

    def _schedule_line_numbers(self, doc, delay=0):
        """Coalesce gutter redraws so fast scroll/key-repeat never floods Tk."""
        if doc is None or doc.line_numbers is None:
            return
        if doc.line_numbers_after is not None:
            try:
                self.after_cancel(doc.line_numbers_after)
            except Exception:
                pass
            doc.line_numbers_after = None
        try:
            doc.line_numbers_after = self.after(
                max(0, int(delay)), lambda d=doc: self._run_line_number_update(d))
        except Exception:
            pass

    def _run_line_number_update(self, doc):
        doc.line_numbers_after = None
        self._update_line_numbers(doc)

    def _update_position(self, doc):
        if self._active_doc() is not doc:
            return
        try:
            line, col = doc.text.index("insert").split(".")
            selected = 0
            try:
                selected = len(doc.text.get("sel.first", "sel.last"))
            except tk.TclError:
                selected = 0
            extra = "   Sel: {}".format(selected) if selected else ""
            self._position_var.set("Ln {}, Col {}{}".format(line, int(col) + 1, extra))
        except Exception:
            self._position_var.set("Ln -, Col -")

    def _update_format_status(self, doc):
        if self._active_doc() is not doc:
            return
        self._format_var.set("{}   {}   {}".format(
            _EOL_NAMES.get(doc.eol, "Unix (LF)"),
            _ENCODING_LABELS.get(doc.encoding, doc.encoding.upper()),
            doc.language,
        ))

    def _update_line_numbers(self, doc):
        if doc.line_numbers is None or doc.text is None:
            return
        if not self._show_line_numbers.get():
            return
        canvas = doc.line_numbers
        text = doc.text
        try:
            canvas.delete("all")
            index = text.index("@0,0")
            visible_line = int(str(index).split(".")[0])
            max_line = max(visible_line, int(doc.line_count or 1))
            desired = max(42, 18 + 8 * len(str(max_line)))
            if abs(int(canvas.winfo_width() or desired) - desired) > 4:
                canvas.configure(width=desired)
            width = max(42, desired)
            while True:
                info = text.dlineinfo(index)
                if info is None:
                    break
                y = info[1]
                line_no = index.split(".")[0]
                if int(line_no) in doc.bookmarks:
                    canvas.create_oval(
                        4, y + 3, 12, y + 11, fill="#2b78d6", outline="")
                canvas.create_text(
                    width - 7,
                    y,
                    anchor="ne",
                    text=line_no,
                    fill="#6f6f6f",
                    font=(self._preferred_editor_font(), max(8, self._font_size - 1)),
                )
                index = text.index("{}+1line".format(index))
        except Exception:
            pass

    def _set_doc_status(self, doc, message):
        doc.status_message = str(message or "")
        if self._active_doc() is doc:
            self._status_var.set(doc.status_message)

    @staticmethod
    def _set_doc_enabled(doc, enabled):
        try:
            doc.text.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _close_active_tab(self):
        doc = self._active_doc()
        if doc is not None:
            self._close_doc(doc)

    def _close_doc(self, doc, ask=True):
        if doc.busy and doc.pending_operation not in ("load", ""):
            show_modern_message(
                self.root, "Server Notepad",
                "Wait for the current server operation to finish before closing this tab.",
                intent="info", heading="Operation still running")
            return False
        if ask and self._is_dirty(doc):
            answer = ask_modern_choice(
                self.root, "Save changes?",
                "Save changes to {} before closing?".format(PurePosixPath(doc.path).name),
                intent="question", heading="Unsaved changes",
                actions=[
                    ("Cancel", None, "secondary"),
                    ("Don't Save", False, "secondary"),
                    ("Save", True, "primary"),
                ])
            if answer is None:
                return False
            if answer:
                self._save_doc(doc)
                return False
        self._remove_doc(doc)
        return True

    def _remove_doc(self, doc):
        path = doc.path
        try:
            if doc.highlight_after is not None:
                self.root.after_cancel(doc.highlight_after)
            if doc.render_after is not None:
                self.root.after_cancel(doc.render_after)
        except Exception:
            pass
        doc.render_chunks.clear()
        doc.render_after = None
        doc.snapshot_parts = []
        doc.snapshot_text = ""
        doc.line_offsets = []
        doc.function_entries = []
        try:
            self.notebook.forget(doc.frame)
            doc.frame.destroy()
        except Exception:
            pass
        try:
            self._load_queue.remove(path)
        except ValueError:
            pass
        if self._current_load_path == path:
            # Closing a loading tab must not stall the remaining queue.  The
            # parent may still finish the in-flight SFTP read; its late result
            # is ignored because this document no longer exists.
            self._current_load_path = None
            self.after_idle(self._start_next_load)
        self._documents.pop(path, None)
        self._tab_to_path = {
            tab: existing_path for tab, existing_path in self._tab_to_path.items()
            if existing_path != path
        }
        self._rebuild_tab_strip()
        self._refresh_document_list()
        self._schedule_state_save()
        if not self._documents:
            self._status_var.set("No server file open")
            self._stats_var.set("length: 0   lines: 1")
            self._length_var.set("length: 0")
            self._lines_var.set("lines: 1")
            self._update_window_title(None)
            self._refresh_function_list(None)
        else:
            self._sync_active_ui()

    def _close_other_tabs(self):
        active = self._active_doc()
        if active is None:
            return
        for doc in list(self._documents.values()):
            if doc is active:
                continue
            if not self._close_doc(doc):
                break

    def _close_tabs_to_right(self):
        try:
            tabs = list(self.notebook.tabs())
            current = self.notebook.index(self.notebook.select())
        except Exception:
            return
        for tab_id in list(tabs[current + 1:]):
            path = self._tab_to_path.get(str(tab_id))
            doc = self._documents.get(path)
            if doc is not None and not self._close_doc(doc):
                break

    def _close_all_tabs(self):
        for doc in list(self._documents.values()):
            if not self._close_doc(doc):
                return False
        return True

    def _close_window_ui(self):
        active = self._active_doc()
        self._session_snapshot = {
            "open_paths": [doc.path for doc in self._documents.values()],
            "active_path": active.path if active is not None else "",
        }
        if not self._close_all_tabs():
            self._session_snapshot = None
            return
        self._destroy_ui()

    def _destroy_ui(self):
        self._save_local_state()
        try:
            self.owner.notify_closed()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _show_tab_context_menu(self, event, doc):
        if doc is None:
            return
        self._select_doc(doc)
        popup = tk.Menu(self.root, tearoff=False)
        popup.add_command(label="Save", command=self._save_active)
        popup.add_command(label="Reload from Server", command=self._reload_active)
        popup.add_separator()
        popup.add_command(label="Close", command=self._close_active_tab)
        popup.add_command(label="Close Other Tabs", command=self._close_other_tabs)
        popup.add_command(label="Close Tabs to the Right", command=self._close_tabs_to_right)
        popup.add_command(label="Close All", command=self._close_all_tabs)
        popup.add_separator()
        popup.add_command(label="Copy Full Server Path", command=self._copy_server_path)
        try:
            popup.tk_popup(event.x_root, event.y_root)
        finally:
            popup.grab_release()

    def _tab_left_click(self, event):
        """Treat the right edge of a tab as a Notepad++-style close button."""
        try:
            index = self.notebook.index("@{},{}".format(event.x, event.y))
            bbox = self.notebook.bbox(index)
            if not bbox:
                return None
            x, _y, width, _height = bbox
            if event.x >= x + max(0, width - 24):
                tab_id = self.notebook.tabs()[index]
                path = self._tab_to_path.get(str(tab_id))
                doc = self._documents.get(path)
                if doc is not None:
                    self._close_doc(doc)
                return "break"
        except Exception:
            pass
        return None

    def _middle_click_close(self, event):
        try:
            index = self.notebook.index("@{},{}".format(event.x, event.y))
            tab_id = self.notebook.tabs()[index]
            path = self._tab_to_path.get(str(tab_id))
            doc = self._documents.get(path)
            if doc is not None:
                self._close_doc(doc)
        except Exception:
            pass

    def _tab_context_menu(self, event):
        try:
            index = self.notebook.index("@{},{}".format(event.x, event.y))
            tab_id = self.notebook.tabs()[index]
            path = self._tab_to_path.get(str(tab_id))
            doc = self._documents.get(path)
        except Exception:
            return
        self._show_tab_context_menu(event, doc)

    def _text_event(self, virtual_event):
        doc = self._active_doc()
        if doc is None or doc.busy:
            return
        try:
            doc.text.event_generate(virtual_event)
        except tk.TclError:
            pass

    def _editor_context_menu(self, event, doc):
        if doc is None:
            return
        try:
            self.notebook.select(doc.frame)
        except Exception:
            pass
        popup = tk.Menu(self.root, tearoff=False)
        popup.add_command(label="Undo", command=lambda: self._text_event("<<Undo>>"))
        popup.add_command(label="Redo", command=lambda: self._text_event("<<Redo>>"))
        popup.add_separator()
        popup.add_command(label="Cut", command=lambda: self._text_event("<<Cut>>"))
        popup.add_command(label="Copy", command=lambda: self._text_event("<<Copy>>"))
        popup.add_command(label="Paste", command=lambda: self._text_event("<<Paste>>"))
        popup.add_command(label="Delete", command=self._delete_selection)
        popup.add_separator()
        popup.add_command(label="Duplicate Current Line", command=self._duplicate_current_line)
        popup.add_command(label="Delete Current Line", command=self._delete_current_line)
        popup.add_separator()
        popup.add_command(label="Select All", command=self._select_all)
        popup.add_separator()
        popup.add_command(label="Find...", command=lambda: self._show_find_replace(False))
        popup.add_command(label="Replace...", command=lambda: self._show_find_replace(True))
        try:
            popup.tk_popup(event.x_root, event.y_root)
        finally:
            popup.grab_release()

    def _delete_selection(self):
        doc = self._active_doc()
        if doc is None or doc.busy:
            return
        try:
            doc.text.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

    def _select_all(self):
        doc = self._active_doc()
        if doc is None:
            return
        doc.text.tag_add("sel", "1.0", "end-1c")
        doc.text.mark_set("insert", "1.0")
        doc.text.see("insert")
        return "break"

    def _duplicate_current_line(self):
        doc = self._active_doc()
        if doc is None or doc.busy or not doc.loaded:
            return
        try:
            start = doc.text.index("insert linestart")
            end = doc.text.index("insert lineend+1c")
            content = doc.text.get(start, end)
            if not content:
                content = "\n"
            doc.text.insert(end, content)
            doc.text.mark_set("insert", end)
            doc.text.see("insert")
        except tk.TclError:
            pass

    def _delete_current_line(self):
        doc = self._active_doc()
        if doc is None or doc.busy or not doc.loaded:
            return
        try:
            start = doc.text.index("insert linestart")
            end = doc.text.index("insert lineend+1c")
            if doc.text.compare(end, "==", start):
                return
            doc.text.delete(start, end)
            doc.text.mark_set("insert", start)
            doc.text.see("insert")
        except tk.TclError:
            pass

    def _insert_tab_spaces(self, _event=None):
        doc = self._active_doc()
        if doc is None or doc.busy:
            return "break"
        doc.text.insert("insert", "    ")
        return "break"

    def _set_active_encoding(self, encoding):
        doc = self._active_doc()
        if doc is None:
            return
        doc.encoding = str(encoding or "utf-8")
        doc.status_message = "Encoding changed to {}; Save to apply".format(
            _ENCODING_LABELS.get(doc.encoding, doc.encoding))
        self._update_tab_title(doc)
        self._sync_active_ui()

    def _set_active_eol(self, eol):
        doc = self._active_doc()
        if doc is None:
            return
        doc.eol = eol if eol in _EOL_NAMES else "\n"
        doc.status_message = "EOL changed to {}; Save to apply".format(
            _EOL_NAMES.get(doc.eol, "Unix (LF)"))
        self._update_tab_title(doc)
        self._sync_active_ui()

    def _set_active_language(self, language):
        doc = self._active_doc()
        if doc is None:
            return
        doc.language = str(language or "Normal Text")
        self._schedule_highlight(doc, immediate=True)
        self._sync_active_ui()

    def _apply_word_wrap(self):
        for doc in self._documents.values():
            self._apply_word_wrap_to_doc(doc)

    def _apply_word_wrap_to_doc(self, doc):
        wrap = "word" if self._word_wrap.get() else "none"
        doc.text.configure(wrap=wrap)
        if self._word_wrap.get():
            doc.xscroll.grid_remove()
        else:
            doc.xscroll.grid()

    def _apply_line_number_visibility(self):
        for doc in self._documents.values():
            self._apply_line_number_visibility_to_doc(doc)

    def _apply_line_number_visibility_to_doc(self, doc):
        if self._show_line_numbers.get():
            doc.line_numbers.grid()
            self._update_line_numbers(doc)
        else:
            doc.line_numbers.grid_remove()

    def _apply_statusbar_visibility(self):
        if self._show_statusbar.get():
            self.statusbar.pack(side="bottom", fill="x")
        else:
            self.statusbar.pack_forget()

    def _pane_visible(self, widget):
        try:
            return str(widget) in {str(value) for value in self.main_pane.panes()}
        except Exception:
            return False

    def _apply_document_list_visibility(self):
        visible = self._pane_visible(self.document_panel)
        if self._show_document_list.get() and not visible:
            try:
                self.main_pane.insert(0, self.document_panel, weight=0)
            except Exception:
                self.main_pane.add(self.document_panel, weight=0)
        elif not self._show_document_list.get() and visible:
            self.main_pane.forget(self.document_panel)

    def _apply_function_list_visibility(self):
        visible = self._pane_visible(self.function_panel)
        if self._show_function_list.get() and not visible:
            self.main_pane.add(self.function_panel, weight=0)
            self._refresh_function_list(self._active_doc())
        elif not self._show_function_list.get() and visible:
            self.main_pane.forget(self.function_panel)

    def _apply_current_line_highlight(self):
        doc = self._active_doc()
        if doc is not None:
            self._highlight_active_line(doc)

    def _refresh_document_list(self):
        widget = getattr(self, "document_list", None)
        if widget is None:
            return
        paths = list(self._documents.keys())
        active = self._active_doc()
        try:
            widget.delete(0, "end")
            active_index = None
            for index, path in enumerate(paths):
                doc = self._documents[path]
                marker = "* " if self._is_dirty(doc) else ""
                conflict = "! " if doc.conflict else ""
                loading = "[loading] " if (doc.loading or doc.queued) and not doc.loaded else ""
                widget.insert("end", "{}{}{}{}".format(
                    conflict, marker, loading, PurePosixPath(path).name or path))
                if doc is active:
                    active_index = index
            if active_index is not None:
                widget.selection_clear(0, "end")
                widget.selection_set(active_index)
                widget.see(active_index)
        except Exception:
            pass

    def _on_document_list_select(self, _event=None):
        try:
            selection = self.document_list.curselection()
            if not selection:
                return
            paths = list(self._documents.keys())
            index = int(selection[0])
            if not (0 <= index < len(paths)):
                return
            doc = self._documents.get(paths[index])
            if doc is not None:
                self.notebook.select(doc.frame)
        except Exception:
            pass

    def _highlight_active_line(self, doc):
        if doc is None or doc.text is None:
            return
        text = doc.text
        try:
            if doc.current_line_start:
                text.tag_remove("current_line", doc.current_line_start, "{} lineend+1c".format(doc.current_line_start))
            if not self._highlight_current_line.get() or self._active_doc() is not doc:
                doc.current_line_start = ""
                return
            line_start = text.index("insert linestart")
            doc.current_line_start = line_start
            text.tag_configure("current_line", background="#fffbea")
            text.tag_add("current_line", line_start, "{} lineend+1c".format(line_start))
            text.tag_lower("current_line")
        except Exception:
            pass

    def _update_stats(self, doc, approximate=False):
        if self._active_doc() is not doc:
            return
        if doc is None or doc.text is None:
            self._stats_var.set("length: 0   lines: 1")
            self._length_var.set("length: 0")
            self._lines_var.set("lines: 1")
            return
        try:
            if doc.loading:
                line_count = max(1, int(doc.line_count or 1))
                length = int(doc.rendered_chars or doc.stream_received_chars or 0)
                self._stats_var.set(
                    "length: {:,}   lines: {:,}   loading".format(length, line_count))
                self._length_var.set("length: {:,}".format(length))
                self._lines_var.set("lines: {:,}".format(line_count))
                return
            line_count = int(doc.text.index("end-1c").split(".")[0])
            if doc.performance_mode:
                # text.count across a multi-MB Tcl rope on every key release is
                # exactly the kind of hidden O(n) work that makes editors feel
                # frozen. Keep the stable loaded count and line index instead.
                length = max(int(doc.rendered_chars or 0), int(doc.size or 0))
                self._stats_var.set(
                    "length: ~{:,}   lines: {:,}   PERF".format(length, line_count))
                self._length_var.set("length: ~{:,}".format(length))
                self._lines_var.set("lines: {:,}".format(line_count))
                return
            counted = doc.text.count("1.0", "end-1c", "chars")
            length = int(counted[0] if counted else 0)
            self._stats_var.set("length: {:,}   lines: {:,}".format(length, line_count))
            self._length_var.set("length: {:,}".format(length))
            self._lines_var.set("lines: {:,}".format(line_count))
        except Exception:
            pass

    def _switch_tab(self, step):
        try:
            tabs = list(self.notebook.tabs())
            if len(tabs) < 2:
                return
            current = self.notebook.index(self.notebook.select())
            target = (current + int(step)) % len(tabs)
            self.notebook.select(tabs[target])
        except Exception:
            pass
