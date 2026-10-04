from __future__ import annotations

"""Direct server save, conflict and reload lifecycle for Server Notepad."""

import threading

from WinUx.dialogs.modern import ask_modern_confirm, show_modern_message


class ServerNotepadSaveMixin:
    def _save_active(self, force=False):
        doc = self._active_doc()
        if doc is not None:
            self._save_doc(doc, force=force)

    def _save_doc(self, doc, force=False):
        if not doc.loaded:
            self._set_doc_status(doc, "Wait until the file has finished loading")
            return
        if doc.busy:
            self._set_doc_status(doc, "An operation is already running")
            return
        if not self._is_dirty(doc) and not force:
            self._set_doc_status(doc, "No changes to save")
            return
        if force and not doc.conflict:
            if not ask_modern_confirm(
                    self.root, "Force Save",
                    "Force Save bypasses the server-change conflict check.\n\n"
                    "Overwrite the current server file?",
                    intent="warning", heading="Overwrite server file?",
                    primary_text="Force Save", secondary_text="Cancel",
                    primary_role="danger"):
                return
        doc.busy = True
        doc.pending_operation = "save"
        doc.save_force = bool(force)
        doc.save_export_generation += 1
        doc.save_export_parts = []
        doc.save_export_index = "1.0"
        doc.save_export_chars = 0
        self._set_doc_status(doc, "Preparing save snapshot...")
        self._set_doc_enabled(doc, False)
        # Extract the Tcl Text rope in bounded slices.  A multi-megabyte
        # Ctrl+S therefore yields between chunks instead of blocking the Tk
        # mainloop on one giant text.get()/replace/json.dumps operation.
        self.after_idle(lambda d=doc: self._export_save_chunk(d))

    def _export_save_chunk(self, doc):
        if (doc is None or doc.path not in self._documents or not doc.busy
                or doc.pending_operation != "save"):
            return
        text = doc.text
        try:
            start = str(doc.save_export_index or "1.0")
            final = "end-1c"
            if text.compare(start, ">=", final):
                self._finish_save_export(doc)
                return
            end = text.index("{}+{}c".format(start, self.SAVE_EXPORT_SLICE_CHARS))
            if text.compare(end, ">", final):
                end = final
            if text.compare(end, "<=", start):
                self._finish_save_export(doc)
                return
            part = text.get(start, end)
            if doc.eol != "\n":
                part = part.replace("\n", doc.eol)
            doc.save_export_parts.append(part)
            doc.save_export_chars += len(part)
            doc.save_export_index = end
            expected = max(1, int(doc.rendered_chars or doc.size or doc.save_export_chars))
            percent = min(99, int(doc.save_export_chars * 100 / expected))
            self._set_doc_status(doc, "Preparing save snapshot... {}%".format(percent))
            self.after(1, lambda d=doc: self._export_save_chunk(d))
        except Exception as exc:
            doc.busy = False
            doc.pending_operation = ""
            doc.save_export_parts = []
            self._set_doc_enabled(doc, True)
            self._set_doc_status(doc, "Save preparation failed: {}".format(exc))

    def _finish_save_export(self, doc):
        generation = int(doc.save_export_generation)
        parts = list(doc.save_export_parts or [])
        doc.save_export_parts = []
        path = str(doc.path)
        encoding = str(doc.encoding)
        signature = dict(doc.signature)
        force = bool(doc.save_force)
        self._set_doc_status(doc, "Compressing save payload...")

        def worker():
            try:
                server_text = "".join(parts)
                self._background_events.put((
                    "save_ready", path, generation, server_text,
                    encoding, signature, force))
            except Exception as exc:
                self._background_events.put((
                    "save_failed", path, generation, str(exc)))

        threading.Thread(
            target=worker, name="winux-notepad-save-export", daemon=True).start()

    def _save_all(self):
        dirty_docs = [doc for doc in self._documents.values() if self._is_dirty(doc)]
        if not dirty_docs:
            self._status_var.set("No modified files")
            return
        # TaskManager serialises SFTP model calls, so it is safe to queue each
        # dirty tab without freezing the editor.
        for doc in dirty_docs:
            if not doc.busy:
                self._save_doc(doc, force=False)

    def _save_succeeded_ui(self, snapshot):
        path = str((snapshot or {}).get("path") or "")
        doc = self._documents.get(path)
        if doc is None:
            return
        doc.signature = dict((snapshot or {}).get("signature") or {})
        doc.encoding = str((snapshot or {}).get("encoding") or doc.encoding)
        doc.original_encoding = doc.encoding
        doc.original_eol = doc.eol
        # Tk's dirty/save-point flag is cheaper than copying the full text
        # buffer after every save.
        doc.original_text = ""
        doc.dirty = False
        doc.size = int((snapshot or {}).get("size") or 0)
        doc.conflict = False
        doc.busy = False
        doc.pending_operation = ""
        self._set_doc_enabled(doc, True)
        self._set_doc_status(doc, "Saved to server")
        self._update_tab_title(doc)
        self._sync_active_ui()

    def _save_conflict_ui(self, message, path=None):
        doc = self._doc_for_path(path)
        if doc is None:
            return
        doc.busy = False
        doc.pending_operation = ""
        doc.conflict = True
        self._set_doc_enabled(doc, True)
        self.notebook.select(doc.frame)
        self._set_doc_status(
            doc,
            "Conflict: {}  Use Reload or Force Save.".format(message),
        )
        self._update_tab_title(doc)
        show_modern_message(
            self.root, "Server File Changed",
            "{}\n\nThe server copy changed after this tab was opened.\n\n"
            "Use Reload to inspect the new server copy, or Force Save to overwrite it."
            .format(message), intent="warning", heading="Server copy changed")

    def _reload_active(self):
        doc = self._active_doc()
        if doc is not None:
            self._reload_doc(doc)

    def _reload_doc(self, doc):
        if not doc.loaded:
            self._set_doc_status(doc, "File is still loading")
            return
        if doc.busy:
            return
        if self._is_dirty(doc):
            if not ask_modern_confirm(
                    self.root, "Reload from Server",
                    "This tab has unsaved changes.\n\nDiscard them and reload the server copy?",
                    intent="warning", heading="Discard unsaved changes?",
                    primary_text="Reload", secondary_text="Cancel",
                    primary_role="danger"):
                return
        doc.busy = True
        doc.pending_operation = "reload"
        self._set_doc_enabled(doc, False)
        self._set_doc_status(doc, "Reloading from server...")
        if not self.owner.request_reload(doc.path):
            doc.busy = False
            doc.pending_operation = ""
            self._set_doc_enabled(doc, True)
            self._set_doc_status(doc, "Could not queue reload request")

    def _reload_succeeded_ui(self, snapshot):
        path = str((snapshot or {}).get("path") or "")
        doc = self._documents.get(path)
        if doc is None:
            return
        self._begin_snapshot_insert(doc, snapshot, label="Reloaded from server")

    def _operation_failed_ui(self, message, path=None, operation=None):
        if str(operation or "") == "load":
            self._load_failed_ui(message, path)
            return
        doc = self._doc_for_path(path)
        if doc is not None:
            doc.busy = False
            doc.pending_operation = ""
            self._set_doc_enabled(doc, True)
            self.notebook.select(doc.frame)
            self._set_doc_status(doc, "Error: {}".format(message))
        show_modern_message(
            self.root, "Server Notepad",
            str(message or "The server operation failed."),
            intent="error", heading="Server operation failed")

    def _handle_save_background_event(self, event):
        kind = event[0]
        if kind == "save_failed":
            _kind, path, generation, message = event
            doc = self._documents.get(str(path))
            if doc is not None and int(doc.save_export_generation) == int(generation):
                doc.busy = False
                doc.pending_operation = ""
                self._set_doc_enabled(doc, True)
                self._set_doc_status(doc, "Save preparation failed: {}".format(message))
            return True
        if kind == "save_ready":
            _kind, path, generation, server_text, encoding, signature, force = event
            doc = self._documents.get(str(path))
            if (doc is None or int(doc.save_export_generation) != int(generation)
                    or not doc.busy or doc.pending_operation != "save"):
                return True
            self._set_doc_status(doc, "Sending save to server...")
            if not self.owner.request_save(
                    doc.path, server_text, encoding, signature, bool(force)):
                doc.busy = False
                doc.pending_operation = ""
                self._set_doc_enabled(doc, True)
                self._set_doc_status(doc, "Could not queue save request")
            return True
        return False

