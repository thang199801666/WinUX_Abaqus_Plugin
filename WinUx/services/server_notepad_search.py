"""Search and replacement orchestration owned separately from the editor window."""
from __future__ import annotations
import re
import time
from pathlib import PurePosixPath
import tkinter as tk


class ServerNotepadSearchController:
    def __init__(self, view, ask_text):
        self.view = view
        self.ask_text = ask_text
        self._search_generation = 0
        self._search_results_meta = []
        self._search_state = None

    def _close_search_results(self):
        self._search_generation += 1
        self._search_state = None
        try:
            self.view.search_results_panel.pack_forget()
        except Exception:
            pass

    def _find_all_current(self):
        doc = self.view._active_doc()
        if doc is None or not doc.loaded:
            return
        needle = ""
        match_case = False
        regex = False
        if self.view._find_vars:
            needle = str(self.view._find_vars["find"].get() or "")
            match_case = bool(self.view._find_vars["case"].get())
            regex = bool(self.view._find_vars["regex"].get())
        if not needle:
            try:
                needle = str(doc.text.get("sel.first", "sel.last") or "")
            except tk.TclError:
                needle = str(doc.last_find or "")
        if not needle:
            needle = self.ask_text(
                self.view.root, "Find All", "Find what:",
                heading="Find all in current document",
                primary_text="Find All", secondary_text="Cancel") or ""
        if not needle:
            return

        doc.last_find = needle
        doc.last_find_options = {
            "match_case": bool(match_case), "regex": bool(regex), "wrap": True}
        # Unmodified large files have an immutable Python-side index.  Search
        # that in a worker thread instead of repeatedly crossing Tcl/Tk.
        if self.view._start_background_find_all(
                doc, needle, match_case=match_case, regex=regex):
            return
        self._search_generation += 1
        generation = self._search_generation
        self._search_results_meta = []
        self.view.search_results.delete(0, "end")
        self.view.search_results.insert(
            "end", "Searching '{}' in {} ...".format(
                needle, PurePosixPath(doc.path).name))
        self.view.search_results_panel.pack(side="bottom", fill="x", before=self.view.notebook)
        count_var = tk.IntVar(master=self.view, value=0)
        self._search_state = {
            "generation": generation,
            "path": doc.path,
            "needle": needle,
            "match_case": bool(match_case),
            "regex": bool(regex),
            "index": "1.0",
            "count_var": count_var,
            "matches": 0,
        }
        self.view.after_idle(self._find_all_step)

    def _find_all_step(self):
        state = self._search_state
        if not state or state.get("generation") != self._search_generation:
            return
        doc = self.view._documents.get(str(state.get("path") or ""))
        if doc is None or doc.text is None or not doc.loaded:
            self._search_state = None
            return
        text = doc.text
        needle = str(state.get("needle") or "")
        if not needle:
            return
        started = time.perf_counter()
        budget = 0.008
        batch = 0
        complete = False
        while batch < 80 and (time.perf_counter() - started) < budget:
            count_var = state["count_var"]
            count_var.set(0)
            try:
                found = text.search(
                    needle, str(state["index"]), stopindex="end-1c",
                    nocase=not bool(state.get("match_case")),
                    regexp=bool(state.get("regex")), count=count_var)
            except tk.TclError as exc:
                self.view.search_results.delete(0, "end")
                self.view.search_results.insert("end", "Find error: {}".format(exc))
                self._search_state = None
                return
            if not found:
                complete = True
                break
            length = int(count_var.get() or 0)
            if length <= 0:
                length = max(1, len(needle))
            try:
                end = text.index("{}+{}c".format(found, length))
                line = int(str(found).split(".")[0])
                snippet = text.get("{}.0".format(line), "{}.0 lineend".format(line)).strip()
            except Exception:
                end = text.index("{}+1c".format(found))
                line = int(str(found).split(".")[0])
                snippet = ""
            if state["matches"] == 0:
                self.view.search_results.delete(0, "end")
            display = "Line {:>7}: {}".format(line, snippet[:220])
            self.view.search_results.insert("end", display)
            self._search_results_meta.append((doc.path, found, end))
            state["matches"] += 1
            state["index"] = end if end != found else text.index("{}+1c".format(found))
            batch += 1
            if state["matches"] >= 5000:
                complete = True
                self.view.search_results.insert("end", "[Result limit reached: 5000]")
                break
        if complete:
            matches = int(state.get("matches") or 0)
            if matches == 0:
                self.view.search_results.delete(0, "end")
                self.view.search_results.insert("end", "No matches found")
            self.view._status_var.set("Find All: {} match(es)".format(matches))
            self._search_state = None
            return
        self.view.after(1, self._find_all_step)

    def _goto_search_result(self, _event=None):
        try:
            selection = self.view.search_results.curselection()
            if not selection:
                return
            index = int(selection[0])
            if index < 0 or index >= len(self._search_results_meta):
                return
            path, start, end = self._search_results_meta[index]
            doc = self.view._documents.get(path)
            if doc is None or doc.text is None:
                return
            self.view.notebook.select(doc.frame)
            doc.text.tag_remove("sel", "1.0", "end")
            doc.text.tag_add("sel", start, end)
            doc.text.mark_set("insert", end)
            doc.text.see(start)
            doc.text.focus_set()
            self.view._on_editor_activity(doc)
        except Exception:
            pass

    def _find_from_dialog(self, forward=True):
        if not self.view._find_vars:
            return False
        return self._find_next(
            forward=forward,
            needle=self.view._find_vars["find"].get(),
            match_case=bool(self.view._find_vars["case"].get()),
            regex=bool(self.view._find_vars["regex"].get()),
            wrap=bool(self.view._find_vars["wrap"].get()),
        )

    def _find_next(self, forward=True, needle=None, match_case=None, regex=None, wrap=None):
        doc = self.view._active_doc()
        if doc is None:
            return False
        if needle is None:
            if self.view._find_vars:
                needle = self.view._find_vars["find"].get()
                match_case = bool(self.view._find_vars["case"].get())
                regex = bool(self.view._find_vars["regex"].get())
                wrap = bool(self.view._find_vars["wrap"].get())
            else:
                needle = doc.last_find
                options = doc.last_find_options or {}
                match_case = bool(options.get("match_case", False))
                regex = bool(options.get("regex", False))
                wrap = bool(options.get("wrap", True))
        needle = str(needle or "")
        if not needle:
            self.view._show_find_replace(False)
            return False

        doc.last_find = needle
        doc.last_find_options = {
            "match_case": bool(match_case),
            "regex": bool(regex),
            "wrap": True if wrap is None else bool(wrap),
        }
        text = doc.text
        try:
            if forward:
                start = text.index("sel.last") if text.tag_ranges("sel") else text.index("insert")
                stop = "end-1c"
            else:
                start = text.index("sel.first") if text.tag_ranges("sel") else text.index("insert")
                stop = "1.0"
            count = tk.IntVar(master=self.view, value=0)
            found = text.search(
                needle,
                start,
                stopindex=stop,
                backwards=not forward,
                nocase=not bool(match_case),
                regexp=bool(regex),
                count=count,
            )
            if not found and doc.last_find_options["wrap"]:
                start = "1.0" if forward else "end-1c"
                stop = "end-1c" if forward else "1.0"
                found = text.search(
                    needle,
                    start,
                    stopindex=stop,
                    backwards=not forward,
                    nocase=not bool(match_case),
                    regexp=bool(regex),
                    count=count,
                )
            if not found:
                self.view._status_var.set("Cannot find '{}'".format(needle))
                return False
            length = int(count.get() or 0)
            if length <= 0:
                length = len(needle)
            end = text.index("{}+{}c".format(found, length))
            text.tag_remove("sel", "1.0", "end")
            text.tag_add("sel", found, end)
            text.mark_set("insert", end if forward else found)
            text.see(found)
            text.focus_set()
            self.view._status_var.set("Found '{}'".format(needle))
            self.view._update_position(doc)
            return True
        except tk.TclError as exc:
            self.view._status_var.set("Find error: {}".format(exc))
            return False

    def _replace_one(self):
        doc = self.view._active_doc()
        if doc is None or not self.view._find_vars:
            return
        needle = self.view._find_vars["find"].get()
        replacement = self.view._find_vars["replace"].get()
        try:
            selected = doc.text.get("sel.first", "sel.last")
        except tk.TclError:
            selected = None
        compare_left = selected if self.view._find_vars["case"].get() else (selected or "").casefold()
        compare_right = needle if self.view._find_vars["case"].get() else str(needle).casefold()
        if selected is not None and not self.view._find_vars["regex"].get() and compare_left == compare_right:
            doc.text.delete("sel.first", "sel.last")
            doc.text.insert("insert", replacement)
        elif selected is not None and self.view._find_vars["regex"].get():
            try:
                flags = 0 if self.view._find_vars["case"].get() else re.IGNORECASE
                replaced = re.sub(needle, replacement, selected, count=1, flags=flags)
                if replaced != selected:
                    doc.text.delete("sel.first", "sel.last")
                    doc.text.insert("insert", replaced)
            except re.error as exc:
                self.view._status_var.set("Regex error: {}".format(exc))
                return
        self._find_from_dialog(True)

    def _replace_all(self):
        doc = self.view._active_doc()
        if doc is None or not self.view._find_vars:
            return
        needle = str(self.view._find_vars["find"].get() or "")
        if not needle:
            return
        replacement = self.view._find_vars["replace"].get()
        content = doc.text.get("1.0", "end-1c")
        try:
            if self.view._find_vars["regex"].get():
                flags = 0 if self.view._find_vars["case"].get() else re.IGNORECASE
                updated, count = re.subn(needle, replacement, content, flags=flags)
            else:
                if self.view._find_vars["case"].get():
                    count = content.count(needle)
                    updated = content.replace(needle, replacement)
                else:
                    pattern = re.compile(re.escape(needle), re.IGNORECASE)
                    updated, count = pattern.subn(lambda _m: replacement, content)
        except re.error as exc:
            self.view._status_var.set("Regex error: {}".format(exc))
            return
        if count:
            doc.text.delete("1.0", "end")
            doc.text.insert("1.0", updated)
            doc.text.edit_modified(True)
            self.view._status_var.set("Replaced {} occurrence(s)".format(count))
        else:
            self.view._status_var.set("No occurrences found")
