from __future__ import annotations

"""Background index/search pipeline for the standalone Server Notepad."""

import queue
import re
import threading
from bisect import bisect_right


class ServerNotepadBackgroundMixin:
    @staticmethod
    def _extract_function_entries_from_text(language, text):
        """Build the lightweight Function List in one O(n) pass."""
        entries = []
        interesting_inp = {
            "*part", "*assembly", "*step", "*material", "*section controls",
            "*amplitude", "*surface", "*nset", "*elset", "*instance",
            "*interaction", "*boundary", "*heading",
        }
        py_re = re.compile(r"^\s*(class|def|async\s+def)\s+([A-Za-z_]\w*)")
        cpp_re = re.compile(
            r"^\s*(?:[A-Za-z_]\w*[\w:<>,*&\s]+\s+)?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{")
        fort_re = re.compile(
            r"^\s*(?:subroutine|function|module|program)\s+([A-Za-z_]\w*)",
            re.IGNORECASE)
        for line_no, line_text in enumerate(str(text or "").splitlines(), 1):
            stripped = line_text.strip()
            if language == "Python":
                match = py_re.match(line_text)
                if match:
                    entries.append((line_no, "{} {}".format(match.group(1), match.group(2))))
            elif language == "Abaqus INP":
                if stripped.startswith("*") and not stripped.startswith("**"):
                    head = stripped.split(",", 1)[0].casefold()
                    if head in interesting_inp:
                        entries.append((line_no, stripped[:120]))
            elif language == "C/C++":
                match = cpp_re.match(line_text)
                if match:
                    entries.append((line_no, stripped[:120]))
            elif language == "Fortran":
                match = fort_re.match(line_text)
                if match:
                    entries.append((line_no, stripped[:120]))
            if len(entries) >= 1000:
                break
        return entries

    def _start_background_index(self, doc):
        """Build immutable large-file indexes away from the Tk mainloop."""
        if doc is None or not doc.loaded:
            return
        generation = int(doc.index_generation)
        path = str(doc.path)
        language = str(doc.language)
        parts = list(doc.snapshot_parts or [])
        doc.snapshot_parts = []
        if not parts:
            return

        def worker():
            try:
                text = "".join(parts)
                # A compact line-start table makes offset -> line/column O(log n)
                # for background search results without asking Tcl to scan text.
                offsets = [0]
                cursor = 0
                while True:
                    found = text.find("\n", cursor)
                    if found < 0:
                        break
                    offsets.append(found + 1)
                    cursor = found + 1
                entries = self._extract_function_entries_from_text(language, text)
                self._background_events.put(
                    ("index_ready", path, generation, text, offsets, entries))
            except Exception as exc:
                self._background_events.put(
                    ("index_failed", path, generation, str(exc)))

        threading.Thread(
            target=worker,
            name="winux-notepad-index",
            daemon=True,
        ).start()

    def _start_background_find_all(self, doc, needle, match_case=False, regex=False):
        """Search an immutable loaded snapshot without traversing Tk Text."""
        if doc is None or not doc.index_ready or doc.dirty or not doc.snapshot_text:
            return False
        self._search_generation += 1
        generation = self._search_generation
        text = doc.snapshot_text
        line_offsets = list(doc.line_offsets or [0])
        path = str(doc.path)
        self._search_results_meta = []
        self.search_results.delete(0, "end")
        self.search_results.insert(
            "end", "Searching indexed document '{}' ...".format(needle))
        self.search_results_panel.pack(side="bottom", fill="x", before=self.notebook)
        self._status_var.set("Searching in background...")

        def worker():
            results = []
            error = ""
            truncated = False
            try:
                if regex:
                    flags = 0 if match_case else re.IGNORECASE
                    iterator = re.finditer(needle, text, flags)
                else:
                    pattern = re.compile(
                        re.escape(needle), 0 if match_case else re.IGNORECASE)
                    iterator = pattern.finditer(text)
                for match in iterator:
                    start = int(match.start())
                    end = int(match.end())
                    if end <= start:
                        end = min(len(text), start + 1)
                    line_index = max(0, bisect_right(line_offsets, start) - 1)
                    line_no = line_index + 1
                    column = start - int(line_offsets[line_index])
                    line_end = text.find("\n", start)
                    if line_end < 0:
                        line_end = len(text)
                    line_start = int(line_offsets[line_index])
                    snippet = text[line_start:line_end].strip()[:220]
                    results.append((line_no, column, end - start, snippet))
                    if len(results) >= 5000:
                        truncated = True
                        break
            except Exception as exc:
                error = str(exc)
            self._background_events.put(
                ("find_results", generation, path, str(needle), results, error, truncated))

        threading.Thread(
            target=worker,
            name="winux-notepad-find-all",
            daemon=True,
        ).start()
        return True

    def _pump_background_events(self):
        """Apply worker results in short bursts on the Tk thread."""
        processed = 0
        while processed < 4:
            try:
                event = self._background_events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            kind = event[0]
            if kind == "index_ready":
                _kind, path, generation, text, offsets, entries = event
                doc = self._documents.get(str(path))
                if (doc is not None and doc.loaded and not doc.dirty
                        and int(doc.index_generation) == int(generation)):
                    doc.snapshot_text = text
                    doc.line_offsets = offsets
                    doc.function_entries = entries
                    doc.index_ready = True
                    if self._active_doc() is doc and self._show_function_list.get():
                        self._refresh_function_list(doc)
                    if doc.performance_mode:
                        self._set_doc_status(
                            doc,
                            doc.status_message.replace(
                                "viewport lexer + background index",
                                "viewport lexer + index ready"))
            elif kind == "find_results":
                _kind, generation, path, needle, results, error, truncated = event
                if int(generation) != int(self._search_generation):
                    continue
                self.search_results.delete(0, "end")
                self._search_results_meta = []
                if error:
                    self.search_results.insert("end", "Find error: {}".format(error))
                    self._status_var.set("Find error")
                    continue
                for line_no, column, length, snippet in results:
                    self.search_results.insert(
                        "end", "Line {:>7}: {}".format(line_no, snippet))
                    start = "{}.{}".format(line_no, column)
                    end = "{}+{}c".format(start, max(1, int(length)))
                    self._search_results_meta.append((str(path), start, end))
                if truncated:
                    self.search_results.insert("end", "[Result limit reached: 5000]")
                if not results:
                    self.search_results.insert("end", "No matches found")
                self._status_var.set(
                    "Find All: {} match(es){}".format(
                        len(results), " (limited)" if truncated else ""))
            elif kind in {"save_failed", "save_ready"}:
                # Save/export lifecycle is owned by ServerNotepadSaveMixin.
                # The background pump only transports worker results back to
                # the Tk thread so indexing/search and save orchestration do
                # not become coupled again.
                self._handle_save_background_event(event)
        try:
            self.after(35, self._pump_background_events)
        except Exception:
            pass

    def _schedule_function_refresh(self, doc=None):
        target = doc or self._active_doc()
        if (target is not None and target.performance_mode
                and not (target.index_ready and not target.dirty)):
            return
        if not self._show_function_list.get():
            return
        if self._function_after is not None:
            try:
                self.after_cancel(self._function_after)
            except Exception:
                pass
        self._function_after = self.after(420, lambda d=doc: self._refresh_function_list(d))

    def _refresh_function_list(self, doc=None):
        self._function_after = None
        if not self._show_function_list.get():
            return
        doc = doc or self._active_doc()
        widget = getattr(self, "function_list", None)
        if widget is None:
            return
        try:
            widget.delete(0, "end")
        except Exception:
            return
        self._function_lines = []
        if doc is None or not doc.loaded:
            return
        if doc.index_ready and not doc.dirty and doc.function_entries:
            for line, label in list(doc.function_entries)[:1000]:
                self._function_lines.append(int(line))
                widget.insert("end", str(label))
            return
        if doc.performance_mode:
            return
        try:
            sample = doc.text.get("1.0", "1.0+350000c")
        except Exception:
            return
        entries = []
        if doc.language == "Python":
            pattern = re.compile(r"(?m)^(?P<indent>\s*)(?P<kind>class|def|async\s+def)\s+(?P<name>[A-Za-z_]\w*)")
            for match in pattern.finditer(sample):
                line = sample.count("\n", 0, match.start()) + 1
                entries.append((line, "{} {}".format(match.group("kind"), match.group("name"))))
        elif doc.language == "Abaqus INP":
            for line_no, line_text in enumerate(sample.splitlines(), 1):
                stripped = line_text.strip()
                if stripped.startswith("*") and not stripped.startswith("**"):
                    head = stripped.split(",", 1)[0]
                    if head.casefold() in {"*part", "*assembly", "*step", "*material", "*section controls", "*amplitude", "*surface", "*nset", "*elset"}:
                        entries.append((line_no, stripped[:90]))
        elif doc.language in {"C/C++", "Fortran"}:
            pattern = (re.compile(r"(?m)^\s*(?:[A-Za-z_]\w*[\w:<>,*&\s]+\s+)?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{")
                       if doc.language == "C/C++" else
                       re.compile(r"(?im)^\s*(?:subroutine|function|module|program)\s+([A-Za-z_]\w*)"))
            for match in pattern.finditer(sample):
                line = sample.count("\n", 0, match.start()) + 1
                entries.append((line, match.group(0).strip()[:90]))
        for line, label in entries[:500]:
            self._function_lines.append(line)
            widget.insert("end", label)

    def _goto_selected_function(self, _event=None):
        doc = self._active_doc()
        if doc is None:
            return
        try:
            selection = self.function_list.curselection()
            if not selection:
                return
            line = self._function_lines[int(selection[0])]
            index = "{}.0".format(line)
            doc.text.mark_set("insert", index)
            doc.text.see(index)
            doc.text.focus_set()
            self._on_editor_activity(doc)
        except Exception:
            pass

