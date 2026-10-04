"""Retained tab-strip widgets for the standalone Tk server editor."""
import tkinter as tk
from pathlib import PurePosixPath


class _ToolTip:
    """Tiny dependency-free tooltip for compact icon-only toolbar buttons."""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = str(text or "")
        self.delay = int(delay)
        self._after = None
        self._window = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")
        widget.bind("<Destroy>", self._leave, add="+")

    def _enter(self, _event=None):
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except Exception:
            self._after = None

    def _leave(self, _event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        self._after = None
        if not self.text or self._window is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 4
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            win = tk.Toplevel(self.widget)
            win.wm_overrideredirect(True)
            win.wm_geometry("+{}+{}".format(x, y))
            label = tk.Label(
                win, text=self.text, background="#ffffe1", foreground="#202020",
                relief="solid", borderwidth=1, padx=5, pady=2,
                font=("Segoe UI", 9))
            label.pack()
            self._window = win
        except Exception:
            self._window = None

    def _hide(self):
        win = self._window
        self._window = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass


class _EditorTabStrip:
    """Small custom tab strip with real close buttons and horizontal scrolling.

    ttk.Notebook remains the content host, but its native tabs are hidden.  The
    strip mirrors Notepad++ more closely: rectangular tabs, a blue active
    accent, an actual close button, and wheel/chevron navigation when many
    server documents are open.
    """

    HEIGHT = 29
    TAB_MIN_WIDTH = 112
    TAB_MAX_WIDTH = 240

    def __init__(self, owner, parent):
        self.owner = owner
        self.frame = tk.Frame(parent, height=self.HEIGHT, background="#dedede",
                              borderwidth=0, highlightthickness=0)
        self.frame.pack_propagate(False)
        self.left = tk.Button(
            self.frame, text="<", width=2, takefocus=False, relief="flat",
            borderwidth=0, padx=0, pady=0, background="#e7e7e7",
            activebackground="#d5e8f8", command=lambda: self._scroll(-1))
        self.left.pack(side="left", fill="y")
        self.right = tk.Button(
            self.frame, text=">", width=2, takefocus=False, relief="flat",
            borderwidth=0, padx=0, pady=0, background="#e7e7e7",
            activebackground="#d5e8f8", command=lambda: self._scroll(1))
        self.right.pack(side="right", fill="y")
        self.canvas = tk.Canvas(
            self.frame, height=self.HEIGHT, background="#dedede",
            borderwidth=0, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, background="#dedede", height=self.HEIGHT)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure, add="+")
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        self.canvas.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self.inner.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self._items = {}
        self._order = ()

    def pack(self, *args, **kwargs):
        return self.frame.pack(*args, **kwargs)

    def _on_inner_configure(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas_configure(self, event=None):
        try:
            height = int(event.height if event is not None else self.HEIGHT)
            self.canvas.itemconfigure(self.window_id, height=max(1, height))
        except Exception:
            pass

    def _on_mousewheel(self, event):
        delta = -1 if int(getattr(event, "delta", 0)) > 0 else 1
        self._scroll(delta)
        return "break"

    def _scroll(self, direction):
        try:
            self.canvas.xview_scroll(int(direction) * 3, "units")
        except Exception:
            pass

    def rebuild(self, docs, active_path=None):
        docs = list(docs)
        by_path = {doc.path: doc for doc in docs}
        structure_changed = False
        for path, item in tuple(self._items.items()):
            # Callbacks close over the document instance, so replacement at the
            # same path must replace the tab as well as its displayed label.
            if by_path.get(path) is not item["doc"]:
                item["cell"].destroy()
                del self._items[path]
                structure_changed = True
        for doc in docs:
            if doc.path not in self._items:
                self._create_tab(doc, active=(doc.path == active_path))
                structure_changed = True
            else:
                self._update_doc(doc, active_path, ensure_visible=False)
        order = tuple(doc.path for doc in docs)
        if structure_changed or order != self._order:
            for path in order:
                self._items[path]["cell"].pack_forget()
            for path in order:
                self._items[path]["cell"].pack(side="left", fill="y", padx=(0, 1), pady=(1, 0))
            self._order = order
        self._on_inner_configure()
        self.ensure_visible(active_path)

    def _create_tab(self, doc, active=False):
        bg = "#ffffff" if active else "#e8e8e8"
        hover = "#edf6fd"
        border = "#bfc7cf" if active else "#c9c9c9"
        cell = tk.Frame(
            self.inner, height=self.HEIGHT - 1, background=bg,
            highlightthickness=1, highlightbackground=border, borderwidth=0)
        cell.pack(side="left", fill="y", padx=(0, 1), pady=(1, 0))
        cell.pack_propagate(False)

        accent = tk.Frame(cell, height=2, background="#2b78d6" if active else bg)
        accent.pack(side="top", fill="x")

        body = tk.Frame(cell, background=bg)
        body.pack(side="top", fill="both", expand=True)
        title = tk.Label(
            body, text=self.owner._tab_title(doc, include_close=False), anchor="w",
            background=bg, foreground="#171717", padx=7, pady=0,
            font=("Segoe UI", 9))
        title.pack(side="left", fill="both", expand=True)
        close = tk.Button(
            body, text="x", takefocus=False, relief="flat", borderwidth=0,
            padx=0, pady=0, width=2, background=bg, activebackground="#e81123",
            activeforeground="#ffffff", command=lambda d=doc: self.owner._close_doc(d))
        close.pack(side="right", fill="y")

        # Estimate a bounded tab width from the title.  Keeping this explicit
        # avoids ttk theme-dependent sizing and matches Notepad++'s dense tabs.
        name = PurePosixPath(doc.path).name or doc.path or "Server file"
        width = max(self.TAB_MIN_WIDTH, min(self.TAB_MAX_WIDTH, 54 + len(name) * 7))
        cell.configure(width=width)

        def select(_event=None, d=doc):
            self.owner._select_doc(d)
            return "break"

        def middle(event, d=doc):
            if int(getattr(event, "num", 0)) == 2:
                self.owner._close_doc(d)
                return "break"
            return None

        def context(event, d=doc):
            self.owner._show_tab_context_menu(event, d)
            return "break"

        def enter(_event=None):
            if self.owner._active_doc() is doc:
                return
            for widget in (cell, body, title, close):
                try:
                    widget.configure(background=hover)
                except Exception:
                    pass

        def leave(_event=None):
            if self.owner._active_doc() is doc:
                return
            for widget in (cell, body, title, close):
                try:
                    widget.configure(background="#e8e8e8")
                except Exception:
                    pass

        for widget in (cell, body, title, accent):
            widget.bind("<Button-1>", select, add="+")
            widget.bind("<Button-2>", middle, add="+")
            widget.bind("<Button-3>", context, add="+")
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        close.bind("<Button-3>", context, add="+")
        close.bind("<MouseWheel>", self._on_mousewheel, add="+")
        _ToolTip(close, "Close")
        self._items[doc.path] = {
            "cell": cell, "body": body, "label": title, "close": close,
            "accent": accent,
            "doc": doc,
        }

    def update_doc(self, doc, active_path=None):
        return self._update_doc(doc, active_path, ensure_visible=True)

    def _update_doc(self, doc, active_path, *, ensure_visible):
        item = self._items.get(doc.path)
        if item is None:
            return
        active = doc.path == active_path
        bg = "#ffffff" if active else "#e8e8e8"
        border = "#bfc7cf" if active else "#c9c9c9"
        try:
            item["cell"].configure(background=bg, highlightbackground=border)
            item["body"].configure(background=bg)
            item["label"].configure(
                background=bg, text=self.owner._tab_title(doc, include_close=False))
            item["close"].configure(background=bg)
            item["accent"].configure(background="#2b78d6" if active else bg)
        except Exception:
            pass
        if active and ensure_visible:
            self.ensure_visible(doc.path)

    def ensure_visible(self, path):
        item = self._items.get(str(path or ""))
        if not item:
            return
        try:
            self.canvas.update_idletasks()
            cell = item["cell"]
            left = int(cell.winfo_x())
            right = left + int(cell.winfo_width())
            total = max(1, int(self.inner.winfo_reqwidth()))
            view_left = int(self.canvas.canvasx(0))
            view_right = view_left + int(self.canvas.winfo_width())
            if left < view_left:
                self.canvas.xview_moveto(max(0.0, left / float(total)))
            elif right > view_right:
                target = max(0, right - int(self.canvas.winfo_width()))
                self.canvas.xview_moveto(min(1.0, target / float(total)))
        except Exception:
            pass

