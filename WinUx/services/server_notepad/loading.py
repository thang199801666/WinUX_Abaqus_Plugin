from __future__ import annotations

"""Queued document loading and streamed render pipeline for Server Notepad."""

import time
from pathlib import PurePosixPath

from WinUx.dialogs.modern import show_modern_message


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


def _normalise_eol(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _language_for_path(path):
    name = PurePosixPath(str(path or "")).name.casefold()
    suffix = PurePosixPath(name).suffix.casefold()
    if suffix == ".py":
        return "Python"
    if suffix in {".inp", ".inc"}:
        return "Abaqus INP"
    if suffix == ".json":
        return "JSON"
    if suffix in {".xml", ".html", ".htm"}:
        return "XML/HTML"
    if suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
        return "C/C++"
    if suffix in {".f", ".for", ".f77", ".f90", ".f95"}:
        return "Fortran"
    if suffix in {".sh", ".bash", ".ksh"}:
        return "Shell"
    if suffix in {".yaml", ".yml"}:
        return "YAML"
    return "Normal Text"


class ServerNotepadLoadingMixin:
    def _prioritise_queued_doc(self, doc):
        if doc is None or not doc.queued or doc.loading:
            return
        try:
            self._load_queue.remove(doc.path)
        except ValueError:
            pass
        self._load_queue.appendleft(doc.path)
        if self._current_load_path is None:
            self._start_next_load()

    def _start_next_load(self):
        if self._current_load_path is not None:
            return
        while self._load_queue:
            path = self._load_queue.popleft()
            doc = self._documents.get(path)
            if doc is None or not doc.queued or doc.loaded:
                continue
            self._current_load_path = path
            doc.queued = False
            doc.loading = True
            doc.busy = True
            doc.pending_operation = "load"
            self._set_doc_status(doc, "Reading from server...")
            self._update_tab_title(doc)
            if not self.owner.request_load(path):
                self._load_failed_ui("Could not queue server load request", path)
            return

    def _load_succeeded_ui(self, snapshot):
        # Legacy one-message snapshot path retained for compatibility with old
        # parents.  Current WinUx sends snapshot_begin/chunk/end messages.
        path = str((snapshot or {}).get("path") or "")
        doc = self._documents.get(path)
        if doc is None:
            if self._current_load_path == path:
                self._current_load_path = None
                self.after_idle(self._start_next_load)
            return
        self._begin_snapshot_insert(doc, snapshot, label="Loaded from server")

    def _snapshot_begin_ui(self, operation, snapshot):
        snapshot = dict(snapshot or {})
        path = str(snapshot.get("path") or "")
        doc = self._documents.get(path)
        if doc is None:
            return
        doc.encoding = str(snapshot.get("encoding") or "utf-8")
        doc.original_encoding = doc.encoding
        doc.eol = str(snapshot.get("eol") or "\n")
        doc.original_eol = doc.eol
        doc.signature = dict(snapshot.get("signature") or {})
        doc.size = int(snapshot.get("size") or snapshot.get("bytes_total") or 0)
        doc.load_seconds = float(snapshot.get("load_seconds") or 0.0)
        doc.language = _language_for_path(doc.path)
        doc.conflict = False
        doc.dirty = False
        doc.stream_expected_chars = int(snapshot.get("text_chars") or 0)
        doc.stream_received_chars = 0
        doc.stream_expected_bytes = int(snapshot.get("bytes_total") or doc.size or 0)
        doc.stream_received_bytes = 0
        doc.rendered_chars = 0
        doc.stream_pending_cr = ""
        doc.stream_operation = str(operation or "load")
        doc.loading = True
        doc.loaded = False
        doc.busy = True
        doc.pending_operation = doc.stream_operation
        doc.line_count = 1
        doc.performance_mode = bool(doc.size >= self.PERFORMANCE_MODE_BYTES)
        doc.stream_end_pending = False
        doc.stream_end_meta = {}
        doc.last_progress_ui = 0.0
        doc.render_chunks.clear()
        doc.snapshot_parts = []
        doc.snapshot_text = ""
        doc.line_offsets = []
        doc.function_entries = []
        doc.index_ready = False
        doc.index_generation += 1
        doc.render_slice_chars = self.RENDER_SLICE_CHARS
        doc.last_render_ms = 0.0
        if doc.render_after is not None:
            try:
                self.after_cancel(doc.render_after)
            except Exception:
                pass
            doc.render_after = None
        try:
            # Undo bookkeeping is surprisingly expensive during a multi-MB
            # insert.  Re-enable it only after the load reaches a save point.
            doc.text.configure(state="normal", undo=False, autoseparators=False)
            doc.text.delete("1.0", "end")
            doc.text.edit_modified(False)
        except Exception:
            pass
        label = "Reloading" if doc.stream_operation == "reload" else "Opening"
        suffix = "  [Performance mode]" if doc.performance_mode else ""
        self._show_load_progress(True, 0.0)
        self._set_doc_status(doc, "{} from server... 0%{}".format(label, suffix))
        self._update_tab_title(doc)

    def _snapshot_chunk_ui(self, operation, path, chunk, source_bytes=0):
        del operation
        path = str(path or "")
        doc = self._documents.get(path)
        if doc is None or not doc.loading:
            return
        raw = doc.stream_pending_cr + str(chunk or "")
        doc.stream_pending_cr = ""
        if raw.endswith("\r"):
            raw = raw[:-1]
            doc.stream_pending_cr = "\r"
        normalised = raw.replace("\r\n", "\n").replace("\r", "\n")
        if normalised:
            doc.render_chunks.append(normalised)
            doc.snapshot_parts.append(normalised)
        doc.stream_received_chars += len(str(chunk or ""))
        doc.stream_received_bytes += max(0, int(source_bytes or 0))
        if doc.render_after is None:
            doc.render_after = self.after_idle(
                lambda d=doc: self._render_pending_chunks(d))
        expected = max(1, int(doc.stream_expected_bytes or doc.stream_expected_chars or 0))
        received = (doc.stream_received_bytes if doc.stream_expected_bytes
                    else doc.stream_received_chars)
        now = time.perf_counter()
        # Progress/status repainting can dominate the actual SFTP throughput on
        # a fast LAN.  Notepad++-style editors update these indicators at a
        # human-readable cadence rather than once per data packet.
        if (now - float(doc.last_progress_ui or 0.0) >= self.PROGRESS_UI_INTERVAL
                or received >= expected):
            doc.last_progress_ui = now
            percent = min(99, int((received * 100) / expected))
            if self._active_doc() is doc:
                self._show_load_progress(True, float(percent))
            label = "Reloading" if doc.stream_operation == "reload" else "Opening"
            pending_chars = sum(len(value) for value in doc.render_chunks)
            pending_mib = pending_chars / (1024.0 * 1024.0)
            self._set_doc_status(
                doc,
                "{} from server... {}%   render queue {:.1f} MB{}".format(
                    label, percent, pending_mib,
                    "   [Performance mode]" if doc.performance_mode else ""))
            if self._active_doc() is doc:
                self._update_stats(doc, approximate=True)

    def _snapshot_end_ui(self, operation, path, snapshot=None):
        del operation
        path = str(path or "")
        doc = self._documents.get(path)
        if doc is None:
            self._finish_load_slot(path)
            return
        final = dict(snapshot or {})
        if final:
            doc.signature = dict(final.get("signature") or doc.signature)
            doc.size = int(final.get("size") or doc.size or 0)
            doc.encoding = str(final.get("encoding") or doc.encoding)
            doc.original_encoding = doc.encoding
            doc.eol = str(final.get("eol") or doc.eol or "\n")
            doc.original_eol = doc.eol
            doc.load_seconds = float(final.get("load_seconds") or doc.load_seconds or 0.0)
        if doc.stream_pending_cr:
            doc.render_chunks.append("\n")
            doc.snapshot_parts.append("\n")
            doc.stream_pending_cr = ""
        doc.stream_end_pending = True
        doc.stream_end_meta = final
        if doc.render_after is None:
            doc.render_after = self.after_idle(
                lambda d=doc: self._render_pending_chunks(d))

    def _render_pending_chunks(self, doc):
        """Insert buffered text in short Tk slices to keep the UI responsive."""
        doc.render_after = None
        if doc.path not in self._documents or not doc.loading:
            doc.render_chunks.clear()
            return
        started = time.perf_counter()
        budget = self.RENDER_BUDGET_MS / 1000.0
        try:
            while doc.render_chunks and (time.perf_counter() - started) < budget:
                value = doc.render_chunks.popleft()
                slice_chars = max(
                    self.RENDER_SLICE_MIN_CHARS,
                    min(self.RENDER_SLICE_MAX_CHARS, int(doc.render_slice_chars or self.RENDER_SLICE_CHARS)))
                if len(value) > slice_chars:
                    part = value[:slice_chars]
                    doc.render_chunks.appendleft(value[slice_chars:])
                else:
                    part = value
                if part:
                    insert_started = time.perf_counter()
                    doc.text.insert("end", part)
                    insert_ms = (time.perf_counter() - insert_started) * 1000.0
                    doc.last_render_ms = insert_ms
                    # Aim at ~3 ms per Tcl insertion: grow on fast machines,
                    # shrink quickly on slower/RDP sessions.  This mirrors the
                    # adaptive batching used by high-performance editors.
                    if insert_ms < 2.0 and len(part) >= slice_chars:
                        doc.render_slice_chars = min(
                            self.RENDER_SLICE_MAX_CHARS, int(slice_chars * 1.5))
                    elif insert_ms > 6.0:
                        doc.render_slice_chars = max(
                            self.RENDER_SLICE_MIN_CHARS, int(slice_chars * 0.60))
                    doc.line_count += part.count("\n")
                    doc.rendered_chars += len(part)
        except Exception as exc:
            self._load_failed_ui(str(exc), doc.path)
            return
        if doc.render_chunks:
            # after(1) yields to expose/paint/scroll events; after_idle can
            # starve them when a fast network continuously feeds the queue.
            doc.render_after = self.after(
                1, lambda d=doc: self._render_pending_chunks(d))
            return
        if doc.stream_end_pending:
            self._complete_stream_snapshot(doc)

    def _complete_stream_snapshot(self, doc):
        was_reload = doc.stream_operation == "reload"
        doc.original_text = ""
        doc.loading = False
        doc.loaded = True
        doc.busy = False
        doc.pending_operation = ""
        doc.dirty = False
        doc.stream_operation = ""
        doc.stream_end_pending = False
        doc.stream_end_meta = {}
        try:
            doc.text.configure(
                state="normal", undo=True, autoseparators=True,
                maxundo=(5000 if doc.performance_mode else -1))
            doc.text.edit_reset()
            doc.text.edit_modified(False)
        except Exception:
            pass
        self._configure_syntax_tags(doc)
        if doc.load_seconds > 0.0 and doc.size > 0:
            mib = doc.size / (1024.0 * 1024.0)
            rate = mib / max(0.001, doc.load_seconds)
            status = "{} - {:.2f} MB in {:.2f}s ({:.1f} MB/s)".format(
                "Reloaded from server" if was_reload else "Loaded from server",
                mib, doc.load_seconds, rate)
        else:
            status = "Reloaded from server" if was_reload else "Loaded from server"
        if doc.performance_mode:
            status += "   [Performance mode: viewport lexer + background index]"
        self._show_load_progress(False, 100.0)
        self._set_doc_status(doc, status)
        self._start_background_index(doc)
        self._update_tab_title(doc)
        self._update_line_numbers(doc)
        self._update_stats(doc)
        self._sync_active_ui()
        # Visible-region syntax highlighting is cheap even for multi-MB
        # buffers because it never scans the full document.  Function-list
        # extraction remains deferred in performance mode because that is an
        # O(n) whole-document operation.
        self._schedule_highlight(doc, immediate=True)
        if not doc.performance_mode:
            self._schedule_function_refresh(doc)
        if self._active_doc() is doc:
            try:
                doc.text.focus_set()
            except Exception:
                pass
        if not was_reload:
            self._finish_load_slot(doc.path)

    def _begin_snapshot_insert(self, doc, snapshot, label="Loaded from server"):
        raw_text = str((snapshot or {}).get("text") or "")
        eol = _detect_eol(raw_text)
        normalised = _normalise_eol(raw_text)
        doc.encoding = str((snapshot or {}).get("encoding") or "utf-8")
        doc.original_encoding = doc.encoding
        doc.eol = eol
        doc.original_eol = eol
        doc.signature = dict((snapshot or {}).get("signature") or {})
        doc.size = int((snapshot or {}).get("size") or 0)
        doc.language = _language_for_path(doc.path)
        doc.conflict = False
        doc.load_text = normalised
        doc.load_offset = 0
        doc.load_label = str(label or "Loaded")
        doc.loading = True
        doc.loaded = False
        doc.busy = True
        doc.pending_operation = "load" if self._current_load_path == doc.path else "reload"
        try:
            doc.text.configure(state="normal")
            doc.text.delete("1.0", "end")
            doc.text.edit_reset()
            doc.text.edit_modified(False)
        except Exception:
            pass
        self._set_doc_status(doc, "Loading editor buffer... 0%")
        self.after_idle(lambda d=doc: self._insert_snapshot_chunk(d))

    def _insert_snapshot_chunk(self, doc):
        if doc.path not in self._documents:
            self._finish_load_slot(doc.path)
            return
        content = doc.load_text
        total = len(content)
        if doc.load_offset < total:
            step = 256 * 1024 if total < 4 * 1024 * 1024 else 512 * 1024
            end = min(total, doc.load_offset + step)
            try:
                doc.text.insert("end", content[doc.load_offset:end])
            except Exception as exc:
                self._load_failed_ui(str(exc), doc.path)
                return
            doc.load_offset = end
            percent = 100 if not total else int((end * 100) / total)
            self._set_doc_status(doc, "Loading editor buffer... {}%".format(percent))
            self.after_idle(lambda d=doc: self._insert_snapshot_chunk(d))
            return

        doc.original_text = ""
        doc.dirty = False
        doc.load_text = ""
        doc.load_offset = 0
        doc.loading = False
        doc.loaded = True
        doc.busy = False
        doc.pending_operation = ""
        try:
            doc.text.edit_reset()
            doc.text.edit_modified(False)
            doc.text.configure(state="normal")
        except Exception:
            pass
        self._configure_syntax_tags(doc)
        self._set_doc_status(doc, doc.load_label)
        self._update_tab_title(doc)
        self._update_line_numbers(doc)
        self._sync_active_ui()
        self._schedule_highlight(doc, immediate=False)
        if self._active_doc() is doc:
            try:
                doc.text.focus_set()
            except Exception:
                pass
        self._finish_load_slot(doc.path)

    def _finish_load_slot(self, path):
        if self._current_load_path == path:
            self._current_load_path = None
        # Give the just-loaded tab one paint/input window before beginning the
        # next queued remote file.  Hidden-tab population must not steal the
        # same event-loop turn in which the active file becomes editable.
        self.after(75, self._start_next_load)

    def _load_failed_ui(self, message, path=None):
        path = str(path or "")
        doc = self._documents.get(path)
        restored_only = bool(doc is not None and doc.session_restore)
        if doc is not None:
            doc.loading = False
            doc.loaded = False
            doc.queued = False
            doc.busy = False
            doc.pending_operation = ""
            doc.render_chunks.clear()
            doc.stream_end_pending = False
            if doc.render_after is not None:
                try:
                    self.after_cancel(doc.render_after)
                except Exception:
                    pass
                doc.render_after = None
            self._show_load_progress(False, 0.0)
            try:
                doc.text.configure(state="normal")
                doc.text.delete("1.0", "end")
                doc.text.insert("1.0", "Could not load this server file.\n\n{}".format(message))
                doc.text.configure(state="disabled")
            except Exception:
                pass
            self._set_doc_status(doc, "Load failed: {}".format(message))
            self._update_tab_title(doc)
        self._finish_load_slot(path)
        if restored_only and doc is not None:
            # Session restore is best-effort.  A path saved from an earlier
            # server/job may no longer exist, and showing a modal error for it
            # makes it look as though the newly selected file failed.  Remove
            # only that stale restored tab and continue the load queue.
            self.after_idle(lambda d=doc: self._remove_doc(d)
                            if d.path in self._documents else None)
            return
        detail = str(message or "The server file could not be loaded.")
        if path and path not in detail:
            detail = "Remote path: {}\n\n{}".format(path, detail)
        show_modern_message(
            self.root, "Server Notepad",
            detail,
            intent="error", heading="Could not load server file")

