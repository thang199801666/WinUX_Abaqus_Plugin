from __future__ import annotations

"""Shared Tk dialog chrome for WinUx native windows.

The goal of this module is deterministic layout rather than theme-dependent
button metrics.  Native ttk buttons are hosted in fixed-size containers, so
Windows/Abaqus DPI/theme differences cannot make action rows appear staggered.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ..resources import apply_tk_app_icon
from ..components.qt_style import QtFusionPalette, QtFusionMetrics, color_hex
from ..components.shared_scroller import (
    SharedScrollerMetrics, configure_ttk_scroller_styles, make_ttk_scroller,
)
from ..platform.native_dialog_host import apply_native_qt_chrome


class ModernDialogPalette:
    """Qt/Fusion palette exposed as Tk colour strings."""

    WINDOW = color_hex(QtFusionPalette.WINDOW)
    SURFACE = color_hex(QtFusionPalette.BASE)
    ALT_SURFACE = color_hex(QtFusionPalette.WINDOW_ALT)
    FOOTER = color_hex(QtFusionPalette.WINDOW)
    BORDER = color_hex(QtFusionPalette.BORDER)
    BORDER_LIGHT = color_hex(QtFusionPalette.BORDER_LIGHT)
    TEXT = color_hex(QtFusionPalette.TEXT)
    MUTED = color_hex(QtFusionPalette.TEXT_MUTED)
    PRIMARY = color_hex(QtFusionPalette.PRIMARY)
    PRIMARY_HOVER = color_hex(QtFusionPalette.PRIMARY_HOVER)
    PRIMARY_ACTIVE = color_hex(QtFusionPalette.PRIMARY_ACTIVE)
    DANGER = color_hex(QtFusionPalette.DANGER)
    DANGER_HOVER = color_hex(QtFusionPalette.DANGER_HOVER)
    DANGER_ACTIVE = color_hex(QtFusionPalette.DANGER_ACTIVE)
    SECONDARY = color_hex(QtFusionPalette.BUTTON)
    SECONDARY_HOVER = color_hex(QtFusionPalette.BUTTON_HOVER)
    SECONDARY_ACTIVE = color_hex(QtFusionPalette.BUTTON_ACTIVE)
    HOVER = color_hex(QtFusionPalette.HIGHLIGHT_HOVER)
    ACCENT = color_hex(QtFusionPalette.HIGHLIGHT)
    SELECT = color_hex(QtFusionPalette.HIGHLIGHT_SOFT)
    SELECT_INACTIVE = color_hex(QtFusionPalette.SELECTION_INACTIVE)
    FOCUS = color_hex(QtFusionPalette.FOCUS)
    INFO = "#e7f2fb"
    WARNING = "#fff4ce"
    ERROR = "#fde7e9"
    SUCCESS = "#e7f4ea"


class ModernDialogMetrics:
    PAD_X = 18
    PAD_Y = 16
    BUTTON_WIDTH = 94
    BUTTON_HEIGHT = 32
    BUTTON_GAP = 8
    FOOTER_PAD_X = 14
    FOOTER_PAD_Y = 12
    ICON_SIZE = 36
    MIN_WIDTH = 410
    MIN_HEIGHT = 168

    # QFormLayout/QGroupBox-like shared metrics.  Keeping these in one place
    # prevents every native dialog from inventing its own label width and row
    # spacing, which was the main source of visual drift after the Qt migration.
    FORM_LABEL_WIDTH = 118
    FORM_H_GAP = 12
    FORM_V_GAP = 8
    GROUP_PAD_X = 12
    GROUP_PAD_TOP = 8
    GROUP_PAD_BOTTOM = 11
    GROUP_TITLE_GAP = 6

    # QTreeView/QTableView/QHeaderView-like metrics shared by native dialogs.
    ITEM_VIEW_ROW_HEIGHT = 24
    ITEM_VIEW_HEADER_PAD_X = 7
    ITEM_VIEW_HEADER_PAD_Y = 5
    ITEM_VIEW_BORDER = 1
    ITEM_VIEW_SCROLLBAR = SharedScrollerMetrics.THICKNESS
    ITEM_VIEW_MIN_COLUMN = 60
    ITEM_VIEW_MAX_COLUMN = 520
    TAB_PAD_X = 11
    TAB_PAD_Y = 5

def configure_modern_ttk_styles(widget):
    """Install compact Qt/Fusion-like ttk styles into one Tk interpreter."""
    style = ttk.Style(widget)
    p = ModernDialogPalette
    try:
        # Do not change the host theme: Abaqus may patch ``vista``.  Styling
        # the common ttk classes is enough to make all WinUx helper dialogs
        # visually coherent while preserving platform metrics.
        style.configure("WinUxDialog.TFrame", background=p.WINDOW)
        style.configure("WinUxDialog.Surface.TFrame", background=p.SURFACE)
        style.configure("WinUxDialog.Footer.TFrame", background=p.FOOTER)
        style.configure(
            "WinUxDialog.Title.TLabel",
            background=p.SURFACE, foreground=p.TEXT,
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "WinUxDialog.Message.TLabel",
            background=p.SURFACE, foreground=p.TEXT,
            font=("Segoe UI", 9),
        )
        style.configure(
            "WinUxDialog.Muted.TLabel",
            background=p.SURFACE, foreground=p.MUTED,
            font=("Segoe UI", 8),
        )

        # Standard widgets used throughout Settings, Job Manager, Site Manager,
        # ODB dialogs and transfer dialogs.  This removes the mix of Windows
        # theme defaults and old rounded WinUx controls.
        style.configure(
            "TLabel", background=p.WINDOW, foreground=p.TEXT,
            font=("Segoe UI", 9),
        )
        style.configure(
            "TCheckbutton", background=p.WINDOW, foreground=p.TEXT,
            font=("Segoe UI", 9), padding=(2, 1),
        )
        style.map(
            "TCheckbutton",
            background=[("active", p.WINDOW), ("!disabled", p.WINDOW)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TRadiobutton", background=p.WINDOW, foreground=p.TEXT,
            font=("Segoe UI", 9), padding=(2, 1),
        )
        style.map(
            "TRadiobutton",
            background=[("active", p.WINDOW), ("!disabled", p.WINDOW)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TButton", background=p.SECONDARY, foreground=p.TEXT,
            font=("Segoe UI", 9), padding=(9, 4), borderwidth=1, relief="flat",
        )
        style.map(
            "TButton",
            background=[
                ("pressed", p.SECONDARY_ACTIVE),
                ("active", p.SECONDARY_HOVER),
                ("disabled", p.SECONDARY),
                ("!disabled", p.SECONDARY),
            ],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TEntry", fieldbackground=p.SURFACE, foreground=p.TEXT,
            insertcolor=p.TEXT, padding=(5, 3), borderwidth=1, relief="solid",
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", p.SECONDARY), ("!disabled", p.SURFACE)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TSpinbox", fieldbackground=p.SURFACE, foreground=p.TEXT,
            insertcolor=p.TEXT, padding=(5, 3), borderwidth=1, relief="solid",
            arrowsize=12,
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", p.SECONDARY), ("readonly", p.SURFACE), ("!disabled", p.SURFACE)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TCombobox", fieldbackground=p.SURFACE, background=p.SECONDARY,
            foreground=p.TEXT, arrowcolor=p.TEXT, padding=(5, 3),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p.SURFACE), ("!disabled", p.SURFACE)],
            background=[("active", p.SECONDARY_HOVER), ("!disabled", p.SECONDARY)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
            arrowcolor=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "Treeview", background=p.SURFACE, fieldbackground=p.SURFACE,
            foreground=p.TEXT, bordercolor=p.BORDER,
            rowheight=ModernDialogMetrics.ITEM_VIEW_ROW_HEIGHT,
            font=("Segoe UI", 9), relief="flat",
        )
        style.map(
            "Treeview",
            background=[
                ("selected", "focus", p.SELECT),
                ("selected", "!focus", p.SELECT_INACTIVE),
                ("selected", p.SELECT),
            ],
            foreground=[("selected", p.TEXT)],
        )
        style.configure(
            "Treeview.Heading", background=p.SECONDARY, foreground=p.TEXT,
            font=("Segoe UI", 9),
            padding=(ModernDialogMetrics.ITEM_VIEW_HEADER_PAD_X,
                     ModernDialogMetrics.ITEM_VIEW_HEADER_PAD_Y),
            relief="flat", borderwidth=1,
        )
        style.map(
            "Treeview.Heading",
            background=[("active", p.SECONDARY_HOVER), ("!disabled", p.SECONDARY)],
        )
        style.configure("TNotebook", background=p.WINDOW, borderwidth=0)
        style.configure(
            "TNotebook.Tab", background=p.SECONDARY, foreground=p.TEXT,
            padding=(ModernDialogMetrics.TAB_PAD_X, ModernDialogMetrics.TAB_PAD_Y),
            font=("Segoe UI", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", p.SURFACE), ("active", p.SECONDARY_HOVER)],
            foreground=[("disabled", p.MUTED), ("!disabled", p.TEXT)],
        )
        style.configure(
            "TLabelframe", background=p.WINDOW, bordercolor=p.BORDER,
            relief="solid", borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label", background=p.WINDOW, foreground=p.TEXT,
            font=("Segoe UI", 9),
        )
        style.configure("TSeparator", background=p.BORDER_LIGHT)
        # Shared styles: WinUx.Vertical.TScrollbar / WinUx.Horizontal.TScrollbar
        configure_ttk_scroller_styles(style)
        style.configure(
            "Horizontal.TProgressbar", background=p.PRIMARY, troughcolor=p.WINDOW,
            bordercolor=p.BORDER_LIGHT, lightcolor=p.PRIMARY, darkcolor=p.PRIMARY,
            thickness=8,
        )

        # Qt exposes keyboard focus with a restrained accent border instead of
        # recolouring the entire control.  Some embedded Windows ttk themes
        # ignore these element colours; keeping them here still improves clam
        # and newer Tcl/Tk builds without breaking vista/Abaqus themes.
        for field_style in ("TEntry", "TSpinbox", "TCombobox"):
            try:
                style.map(
                    field_style,
                    bordercolor=[("focus", p.FOCUS), ("!focus", p.BORDER)],
                    lightcolor=[("focus", p.FOCUS), ("!focus", p.BORDER)],
                    darkcolor=[("focus", p.FOCUS), ("!focus", p.BORDER)],
                )
            except tk.TclError:
                pass

        # Keep named action styles for callers that use ttk.Button directly.
        for name, font in (
            ("WinUxDialog.Primary.TButton", ("Segoe UI Semibold", 9)),
            ("WinUxDialog.Secondary.TButton", ("Segoe UI", 9)),
            ("WinUxDialog.Danger.TButton", ("Segoe UI Semibold", 9)),
        ):
            style.configure(name, font=font, padding=(10, 4))
        style.map(
            "WinUxDialog.Primary.TButton",
            foreground=[("!disabled", "#ffffff")],
            background=[("active", p.PRIMARY_HOVER), ("!disabled", p.PRIMARY)],
        )
        style.map(
            "WinUxDialog.Danger.TButton",
            foreground=[("!disabled", "#ffffff")],
            background=[("active", p.DANGER_HOVER), ("!disabled", p.DANGER)],
        )
    except tk.TclError:
        pass
    return style






class QtDialogHeader(tk.Frame):
    """Reusable QDialog-style header with title, subtitle and trailing status.

    Existing WinUx dialogs historically hand-built slightly different white
    title bands.  Keeping the geometry in one widget makes every native dialog
    align like a Qt desktop application and removes repeated hard-coded colours.
    """

    def __init__(
            self, master, title, *, subtitle=None, trailing_var=None,
            trailing_text=None, background=None, bottom_separator=False):
        p = ModernDialogPalette
        bg = str(background or p.SURFACE)
        super().__init__(
            master, background=bg, borderwidth=0, highlightthickness=0)
        self._background = bg
        self.columnconfigure(0, weight=1)

        self.title_label = tk.Label(
            self, text=str(title or ""), anchor="w", justify="left",
            background=bg, foreground=p.TEXT,
            font=("Segoe UI Semibold", 11))
        self.title_label.grid(
            row=0, column=0, sticky="ew", padx=(14, 8), pady=(10, 1))

        self.subtitle_label = tk.Label(
            self, text=str(subtitle or ""), anchor="w", justify="left",
            background=bg, foreground=p.MUTED, font=("Segoe UI", 9))
        self.subtitle_label.grid(
            row=1, column=0, sticky="ew", padx=(14, 8), pady=(0, 9))
        if not subtitle:
            self.subtitle_label.grid_remove()
            self.title_label.grid_configure(pady=(10, 10))

        self.trailing_label = None
        if trailing_var is not None or trailing_text is not None:
            self.trailing_label = tk.Label(
                self, text="" if trailing_text is None else str(trailing_text),
                textvariable=trailing_var, anchor="e", justify="right",
                background=bg, foreground=p.MUTED, font=("Segoe UI", 8))
            self.trailing_label.grid(
                row=0, column=1, rowspan=2, sticky="e",
                padx=(8, 14), pady=(8, 8))

        self.separator = None
        if bottom_separator:
            self.separator = tk.Frame(
                self, height=1, background=p.BORDER_LIGHT,
                borderwidth=0, highlightthickness=0)
            self.separator.grid(row=2, column=0, columnspan=2, sticky="ew")

    def set_title(self, text):
        self.title_label.configure(text=str(text or ""))

    def set_subtitle(self, text):
        value = str(text or "")
        self.subtitle_label.configure(text=value)
        if value:
            self.subtitle_label.grid()
            self.title_label.grid_configure(pady=(10, 1))
        else:
            self.subtitle_label.grid_remove()
            self.title_label.grid_configure(pady=(10, 10))


class QtScrollArea(tk.Frame):
    """Small QScrollArea analogue used by native WinUx dialogs.

    ``body`` is an ordinary Tk frame so existing row widgets can keep their
    current code.  Scroll bars, viewport colour, wheel handling and resize
    semantics are centralized here instead of being copied into every dialog.
    """

    def __init__(
            self, master, *, background=None, vertical=True, horizontal=False,
            border=False, wheel_units=3):
        p = ModernDialogPalette
        bg = str(background or p.SURFACE)
        super().__init__(
            master, background=bg, borderwidth=0,
            highlightthickness=1 if border else 0,
            highlightbackground=p.BORDER, highlightcolor=p.BORDER)
        self._background = bg
        self._horizontal = bool(horizontal)
        self._wheel_units = max(1, int(wheel_units))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self, highlightthickness=0, borderwidth=0, background=bg)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.scrollbar = None
        if vertical:
            self.scrollbar = make_ttk_scroller(
                ttk, self, orient="vertical", command=self.canvas.yview)
            self.scrollbar.grid(row=0, column=1, sticky="ns")
            self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.hscrollbar = None
        if horizontal:
            self.hscrollbar = make_ttk_scroller(
                ttk, self, orient="horizontal", command=self.canvas.xview)
            self.hscrollbar.grid(row=1, column=0, sticky="ew")
            self.canvas.configure(xscrollcommand=self.hscrollbar.set)

        self.body = tk.Frame(
            self.canvas, background=bg, borderwidth=0, highlightthickness=0)
        self._body_window = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_scrollregion, add="+")
        self.canvas.bind("<Configure>", self._canvas_resized, add="+")
        for widget in (self, self.canvas, self.body):
            widget.bind("<MouseWheel>", self._mouse_wheel, add="+")
            if horizontal:
                widget.bind("<Shift-MouseWheel>", self._shift_mouse_wheel, add="+")

    def _sync_scrollregion(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass

    def _canvas_resized(self, event):
        if self._horizontal:
            return
        try:
            self.canvas.itemconfigure(
                self._body_window, width=max(1, int(event.width)))
        except tk.TclError:
            pass

    def _mouse_wheel(self, event):
        delta = int(getattr(event, "delta", 0) or 0)
        if not delta:
            return None
        try:
            steps = -self._wheel_units if delta > 0 else self._wheel_units
            self.canvas.yview_scroll(steps, "units")
            return "break"
        except tk.TclError:
            return None

    def _shift_mouse_wheel(self, event):
        delta = int(getattr(event, "delta", 0) or 0)
        if not delta:
            return None
        try:
            steps = -self._wheel_units if delta > 0 else self._wheel_units
            self.canvas.xview_scroll(steps, "units")
            return "break"
        except tk.TclError:
            return None

    def bind_mousewheel_recursive(self, widget):
        try:
            widget.bind("<MouseWheel>", self._mouse_wheel, add="+")
            if self._horizontal:
                widget.bind("<Shift-MouseWheel>", self._shift_mouse_wheel, add="+")
        except tk.TclError:
            pass
        for child in tuple(getattr(widget, "winfo_children", lambda: ())()):
            self.bind_mousewheel_recursive(child)
        return widget


class QtGroupBox(tk.Frame):
    """Compact native group box with deterministic Qt/Fusion geometry.

    ttk.LabelFrame metrics vary considerably between the Windows, clam and
    Abaqus-patched themes.  This wrapper keeps the one-pixel frame, title and
    client padding stable while still exposing an ordinary Tk frame as
    ``content`` for existing dialog code.
    """

    def __init__(self, master, title, *, background=None, fill=True):
        p = ModernDialogPalette
        bg = str(background or p.SURFACE)
        super().__init__(
            master, background=bg, borderwidth=0, highlightthickness=1,
            highlightbackground=p.BORDER, highlightcolor=p.BORDER)
        self._background = bg
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1 if fill else 0)

        self.title_label = tk.Label(
            self, text=str(title or ""), anchor="w", background=bg,
            foreground=p.TEXT, font=("Segoe UI Semibold", 9))
        self.title_label.grid(
            row=0, column=0, sticky="ew",
            padx=ModernDialogMetrics.GROUP_PAD_X,
            pady=(ModernDialogMetrics.GROUP_PAD_TOP,
                  ModernDialogMetrics.GROUP_TITLE_GAP))

        self.content = tk.Frame(
            self, background=bg, borderwidth=0, highlightthickness=0)
        self.content.grid(
            row=1, column=0, sticky="nsew",
            padx=ModernDialogMetrics.GROUP_PAD_X,
            pady=(0, ModernDialogMetrics.GROUP_PAD_BOTTOM))
        self.content.columnconfigure(0, weight=1)


class QtFormLayout(tk.Frame):
    """Small QFormLayout analogue for native WinUx dialogs.

    Labels share one minimum-width column and fields share one expanding
    column.  Rows use a single vertical metric, so Entry/ComboBox/SpinBox and
    static-value rows line up exactly across all dialogs.
    """

    def __init__(self, master, *, background=None, label_width=None,
                 hgap=None, vgap=None):
        p = ModernDialogPalette
        bg = str(background or p.SURFACE)
        super().__init__(
            master, background=bg, borderwidth=0, highlightthickness=0)
        self._background = bg
        self._row = 0
        self._hgap = int(hgap if hgap is not None else ModernDialogMetrics.FORM_H_GAP)
        self._vgap = int(vgap if vgap is not None else ModernDialogMetrics.FORM_V_GAP)
        width = int(label_width if label_width is not None else ModernDialogMetrics.FORM_LABEL_WIDTH)
        self.columnconfigure(0, minsize=max(1, width), weight=0)
        self.columnconfigure(1, weight=1)

    def add_row(self, label, widget, *, label_muted=False, sticky="ew", pady=None):
        row = self._row
        self._row += 1
        p = ModernDialogPalette
        pad_y = (0, self._vgap) if pady is None else pady
        label_widget = tk.Label(
            self, text=str(label), anchor="w", background=self._background,
            foreground=p.MUTED if label_muted else p.TEXT,
            font=("Segoe UI", 9))
        label_widget.grid(
            row=row, column=0, sticky="w", padx=(0, self._hgap), pady=pad_y)
        widget.grid(row=row, column=1, sticky=sticky, pady=pad_y)
        return label_widget, widget

    def add_value_row(self, label, variable=None, text=None, *, muted_label=True):
        value = tk.Label(
            self, text="" if text is None else str(text),
            textvariable=variable, anchor="w", background=self._background,
            foreground=ModernDialogPalette.TEXT, font=("Segoe UI", 9))
        self.add_row(label, value, label_muted=muted_label)
        return value

    def add_full_row(self, widget, *, pady=None, sticky="ew"):
        row = self._row
        self._row += 1
        pad_y = (0, self._vgap) if pady is None else pady
        widget.grid(row=row, column=0, columnspan=2, sticky=sticky, pady=pad_y)
        return widget


class QtTabWidget(ttk.Notebook):
    """QTabWidget-like wrapper with consistent page padding and shortcuts.

    ``Ctrl+Tab`` / ``Ctrl+Shift+Tab`` cycle pages like Qt.  Home/End select
    the first/last page while the tab widget owns focus.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, takefocus=True, **kwargs)
        self._pages = []
        self.bind("<Control-Tab>", lambda _e: self._cycle_page(1), add="+")
        self.bind("<Control-Shift-Tab>", lambda _e: self._cycle_page(-1), add="+")
        self.bind("<Control-ISO_Left_Tab>", lambda _e: self._cycle_page(-1), add="+")
        self.bind("<Home>", lambda _e: self._select_edge_page(False), add="+")
        self.bind("<End>", lambda _e: self._select_edge_page(True), add="+")

    def add_page(self, title, *, background=None, padding=10):
        bg = str(background or ModernDialogPalette.WINDOW)
        page = tk.Frame(self, background=bg, borderwidth=0, highlightthickness=0)
        inner = tk.Frame(page, background=bg, borderwidth=0, highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.add(page, text=str(title))
        self._pages.append((page, inner))
        return inner

    def _cycle_page(self, delta):
        tabs = self.tabs()
        if not tabs:
            return "break"
        try:
            current = self.index(self.select())
        except tk.TclError:
            current = 0
        self.select(tabs[(current + int(delta)) % len(tabs)])
        return "break"

    def _select_edge_page(self, last=False):
        tabs = self.tabs()
        if tabs:
            self.select(tabs[-1 if last else 0])
        return "break"


def _tree_column_ids(tree):
    try:
        return tuple(str(value) for value in tree.cget("columns"))
    except Exception:
        try:
            return tuple(tree["columns"])
        except Exception:
            return ()


def _smart_tree_sort_key(value):
    """Stable Qt-style sort key: numbers first, then case-insensitive text."""
    raw = "" if value is None else str(value).strip()
    compact = raw.replace(",", "")
    try:
        return (0, float(compact), raw.casefold())
    except (TypeError, ValueError):
        return (1, raw.casefold(), raw)


def _tree_column_from_x(tree, x):
    try:
        token = str(tree.identify_column(int(x)))
        if not token.startswith("#"):
            return None
        index = int(token[1:]) - 1
        columns = _tree_column_ids(tree)
        return columns[index] if 0 <= index < len(columns) else None
    except Exception:
        return None


def resize_tree_column_to_contents(tree, column, *, min_width=None, max_width=None):
    """Resize one ttk.Treeview column similarly to QHeaderView::ResizeToContents."""
    column = str(column or "")
    if not column:
        return False
    min_width = int(min_width or ModernDialogMetrics.ITEM_VIEW_MIN_COLUMN)
    max_width = int(max_width or ModernDialogMetrics.ITEM_VIEW_MAX_COLUMN)
    try:
        heading = str(tree.heading(column, "text") or "").replace(" [asc]", "").replace(" [desc]", "")
        font_name = ttk.Style(tree).lookup("Treeview", "font") or "TkDefaultFont"
        try:
            font = tkfont.Font(tree, name=font_name, exists=True)
        except Exception:
            font = tkfont.nametofont("TkDefaultFont")
        width = font.measure(heading) + 28
        for iid in tree.get_children(""):
            width = max(width, font.measure(str(tree.set(iid, column) or "")) + 22)
        tree.column(column, width=max(min_width, min(max_width, int(width))))
        return True
    except Exception:
        return False


def install_qt_header_behavior(tree, *, sortable=False):
    """Install QHeaderView-like sorting and double-click resize-to-contents.

    Heading clicks toggle ascending/descending order when ``sortable`` is
    enabled. Double-clicking a separator auto-sizes the column immediately to
    its left, matching the desktop-table convention used by Qt/Explorer.
    """
    if getattr(tree, "_winux_qt_header_behavior", False):
        return tree
    tree._winux_qt_header_behavior = True
    tree._winux_qt_sort_column = None
    tree._winux_qt_sort_desc = False
    columns = _tree_column_ids(tree)
    tree._winux_qt_heading_text = {}

    for column in columns:
        try:
            tree._winux_qt_heading_text[column] = str(tree.heading(column, "text") or column)
        except tk.TclError:
            tree._winux_qt_heading_text[column] = column

    def update_sort_indicator(active_column=None, descending=False):
        for column in columns:
            base = tree._winux_qt_heading_text.get(column, column)
            suffix = " [desc]" if descending else " [asc]"
            try:
                tree.heading(column, text=base + (suffix if column == active_column else ""))
            except tk.TclError:
                pass

    def sort_by(column):
        if not sortable:
            return
        column = str(column)
        descending = (
            tree._winux_qt_sort_column == column
            and not bool(tree._winux_qt_sort_desc))
        rows = list(tree.get_children(""))
        focused = tree.focus()
        selected = tuple(tree.selection())
        rows.sort(key=lambda iid: _smart_tree_sort_key(tree.set(iid, column)), reverse=descending)
        for index, iid in enumerate(rows):
            tree.move(iid, "", index)
        tree._winux_qt_sort_column = column
        tree._winux_qt_sort_desc = descending
        update_sort_indicator(column, descending)
        if selected:
            try:
                tree.selection_set(selected)
            except tk.TclError:
                pass
        if focused:
            try:
                tree.focus(focused)
                tree.see(focused)
            except tk.TclError:
                pass

    if sortable:
        for column in columns:
            try:
                tree.heading(column, command=lambda c=column: sort_by(c))
            except tk.TclError:
                pass

    def double_click(event):
        try:
            if tree.identify_region(event.x, event.y) != "separator":
                return None
        except tk.TclError:
            return None
        column = _tree_column_from_x(tree, event.x)
        if column is None:
            return None
        resize_tree_column_to_contents(tree, column)
        return "break"

    tree.bind("<Double-1>", double_click, add="+")
    return tree


class QtTreeView(tk.Frame):
    """QTreeView/QTableView-like composite with native ttk scrollbars.

    The public ``tree`` attribute remains a normal ``ttk.Treeview`` so existing
    WinUx model/update code does not need an adapter layer.  This wrapper only
    centralizes frame border, scrollbars, keyboard behaviour and header rules.
    """

    def __init__(self, master, *, columns=(), show="headings",
                 selectmode="browse", vertical_scrollbar=True,
                 horizontal_scrollbar=False, sortable=False, style="Treeview",
                 background=None, **tree_kwargs):
        bg = str(background or ModernDialogPalette.SURFACE)
        super().__init__(
            master, background=bg, borderwidth=0,
            highlightbackground=ModernDialogPalette.BORDER,
            highlightcolor=ModernDialogPalette.FOCUS,
            highlightthickness=ModernDialogMetrics.ITEM_VIEW_BORDER,
            takefocus=False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self, columns=columns, show=show, selectmode=selectmode,
            style=style, takefocus=True, **tree_kwargs)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vscroll = None
        self.hscroll = None
        if vertical_scrollbar:
            self.vscroll = make_ttk_scroller(ttk, self, orient="vertical", command=self.tree.yview)
            self.vscroll.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=self.vscroll.set)
        if horizontal_scrollbar:
            self.hscroll = make_ttk_scroller(ttk, self, orient="horizontal", command=self.tree.xview)
            self.hscroll.grid(row=1, column=0, sticky="ew")
            self.tree.configure(xscrollcommand=self.hscroll.set)
        install_qt_treeview_behavior(self.tree)
        install_qt_header_behavior(self.tree, sortable=sortable)

    def configure_columns(self, specs):
        """Configure ``(key, label, width, stretch, anchor)`` column specs."""
        for spec in specs:
            key, label, width = spec[:3]
            stretch = bool(spec[3]) if len(spec) > 3 else True
            anchor = spec[4] if len(spec) > 4 else "w"
            self.tree.heading(key, text=str(label))
            self.tree.column(
                key, width=int(width), minwidth=ModernDialogMetrics.ITEM_VIEW_MIN_COLUMN,
                stretch=stretch, anchor=anchor)
        # Heading labels are now final; reinstall the stored names before any
        # sort indicator is displayed.
        self.tree._winux_qt_heading_text = {
            str(key): str(self.tree.heading(key, "text") or key)
            for key in _tree_column_ids(self.tree)
        }
        return self.tree



def _select_all_single_line(event=None):
    widget = getattr(event, "widget", None)
    if widget is None:
        return None
    try:
        widget.selection_range(0, "end")
        widget.icursor("end")
        return "break"
    except Exception:
        return None


def _post_ttk_combobox(event=None):
    widget = getattr(event, "widget", None)
    if widget is None:
        return None
    try:
        if "disabled" in tuple(widget.state()):
            return "break"
    except Exception:
        pass
    try:
        widget.tk.call("ttk::combobox::Post", str(widget))
        return "break"
    except Exception:
        return None


def _unpost_ttk_combobox(event=None):
    widget = getattr(event, "widget", None)
    if widget is None:
        return None
    try:
        widget.tk.call("ttk::combobox::Unpost", str(widget))
        return "break"
    except Exception:
        return None


def _guard_combobox_wheel(event=None):
    """Match Qt's conservative wheel behaviour for unfocused comboboxes."""
    widget = getattr(event, "widget", None)
    if widget is None:
        return None
    try:
        return None if widget.focus_get() == widget else "break"
    except Exception:
        return "break"


def install_qt_widget_behavior(window):
    """Install QLineEdit/QComboBox-like keyboard behaviour for native dialogs.

    Bindings are class-level within WinUx's shared Tk interpreter, so controls
    created after ``prepare_modern_toplevel`` automatically inherit them too.
    This avoids per-dialog drift in Ctrl+A, F4/Alt+Down and mouse-wheel rules.
    """
    if window is None:
        return window
    try:
        root = window._root()
    except Exception:
        root = window
    if getattr(root, "_winux_qt_widget_behavior", False):
        return window
    root._winux_qt_widget_behavior = True

    for klass in ("TEntry", "TSpinbox", "TCombobox", "Entry", "Spinbox"):
        try:
            root.bind_class(klass, "<Control-a>", _select_all_single_line, add="+")
            root.bind_class(klass, "<Control-A>", _select_all_single_line, add="+")
        except tk.TclError:
            pass

    for sequence in ("<F4>", "<Alt-Down>"):
        try:
            root.bind_class("TCombobox", sequence, _post_ttk_combobox, add="+")
        except tk.TclError:
            pass
    try:
        root.bind_class("TCombobox", "<Escape>", _unpost_ttk_combobox, add="+")
        root.bind_class("TCombobox", "<MouseWheel>", _guard_combobox_wheel, add="+")
    except tk.TclError:
        pass
    return window


_DIALOG_CANCEL_CAPTIONS = {"cancel", "close", "dismiss", "no"}


def _dialog_toplevel(widget):
    try:
        return widget.winfo_toplevel()
    except Exception:
        return None


def _focused_widget_consumes_return(window, event=None):
    """Return True when Return belongs to an editor/item view, not QDialog."""
    widget = getattr(event, "widget", None)
    if widget is None:
        try:
            widget = window.focus_get()
        except Exception:
            widget = None
    if widget is None:
        return False
    try:
        klass = str(widget.winfo_class())
    except Exception:
        klass = ""
    # QTextEdit/QAbstractItemView equivalents own Return. Entry/Combobox do not
    # unless they installed a widget binding that already returned "break".
    return klass in {"Text", "Treeview", "Listbox"}


def _invoke_dialog_button(button):
    if button is None:
        return False
    try:
        if not button.winfo_exists() or button._is_disabled():
            return False
    except Exception:
        return False
    try:
        button.invoke()
        return True
    except Exception:
        return False


def _qt_dialog_return(window, event=None):
    if _focused_widget_consumes_return(window, event):
        return None
    button = getattr(window, "_winux_qt_default_button", None)
    return "break" if _invoke_dialog_button(button) else None


def _qt_dialog_escape(window, event=None):
    del event
    button = getattr(window, "_winux_qt_cancel_button", None)
    return "break" if _invoke_dialog_button(button) else None


def install_qt_dialog_behavior(window):
    """Install QDialog-style default/reject actions and focus conventions.

    ``FixedActionButton`` instances register themselves dynamically, so this
    function can be called before the footer is built. Widget-specific Return
    or Escape bindings still win: Tk stops propagation when those handlers
    return ``"break"``.
    """
    if getattr(window, "_winux_qt_dialog_behavior", False):
        return window
    window._winux_qt_dialog_behavior = True
    window._winux_qt_default_button = None
    window._winux_qt_cancel_button = None
    try:
        window.bind("<Return>", lambda event: _qt_dialog_return(window, event), add="+")
        window.bind("<KP_Enter>", lambda event: _qt_dialog_return(window, event), add="+")
        window.bind("<Escape>", lambda event: _qt_dialog_escape(window, event), add="+")
    except tk.TclError:
        pass
    return window


def register_qt_dialog_action(button, text, role):
    """Register one action button as a QDialog default or reject button."""
    window = _dialog_toplevel(button)
    if window is None:
        return
    install_qt_dialog_behavior(window)
    role = str(role or "secondary").lower()
    caption = str(text or "").strip().lower().replace("&", "")
    if role == "primary" and getattr(window, "_winux_qt_default_button", None) is None:
        window._winux_qt_default_button = button
        try:
            button.set_default(True)
        except Exception:
            pass
    if caption in _DIALOG_CANCEL_CAPTIONS and getattr(window, "_winux_qt_cancel_button", None) is None:
        window._winux_qt_cancel_button = button


def install_qt_treeview_behavior(tree, *, on_activate=None, on_delete=None, on_rename=None):
    """Add QTreeView-like focus/selection shortcuts to a ttk.Treeview.

    ttk already supplies arrow/Home/End traversal. This helper fills the gaps
    WinUx users expect from Qt item views: current-row focus, Ctrl+A for
    extended selection, Ctrl+Space toggling, and optional Enter/F2/Delete
    actions without forcing those actions on read-only result tables.
    """
    first_install = not getattr(tree, "_winux_qt_tree_behavior", False)
    if first_install:
        tree._winux_qt_tree_behavior = True
        try:
            tree.configure(takefocus=True)
        except tk.TclError:
            pass

    def current_item():
        try:
            current = tree.focus()
            if current:
                return current
            selection = tree.selection()
            if selection:
                current = selection[0]
            else:
                children = tree.get_children("")
                current = children[0] if children else ""
            if current:
                tree.focus(current)
            return current
        except tk.TclError:
            return ""

    def focus_in(_event=None):
        current_item()

    def select_all(_event=None):
        try:
            if str(tree.cget("selectmode")) == "browse":
                item = current_item()
                if item:
                    tree.selection_set(item)
            else:
                children = tree.get_children("")
                if children:
                    tree.selection_set(children)
                    if not tree.focus():
                        tree.focus(children[0])
            return "break"
        except tk.TclError:
            return None

    def toggle_current(_event=None):
        try:
            item = current_item()
            if not item:
                return "break"
            if str(tree.cget("selectmode")) == "browse":
                tree.selection_set(item)
            elif item in tree.selection():
                tree.selection_remove(item)
            else:
                tree.selection_add(item)
            tree.see(item)
            return "break"
        except tk.TclError:
            return None

    if first_install:
        tree.bind("<FocusIn>", focus_in, add="+")
        tree.bind("<Control-a>", select_all, add="+")
        tree.bind("<Control-A>", select_all, add="+")
        tree.bind("<Control-space>", toggle_current, add="+")
    if callable(on_activate):
        tree.bind("<Return>", lambda _event: (on_activate(), "break")[1], add="+")
        tree.bind("<KP_Enter>", lambda _event: (on_activate(), "break")[1], add="+")
    if callable(on_delete):
        tree.bind("<Delete>", lambda _event: (on_delete(), "break")[1], add="+")
    if callable(on_rename):
        tree.bind("<F2>", lambda _event: (on_rename(), "break")[1], add="+")
    return tree


def configure_qt_menu(menu):
    """Apply the shared Qt/Fusion palette to a classic Tk popup menu."""
    p = ModernDialogPalette
    try:
        menu.configure(
            background=p.SURFACE,
            foreground=p.TEXT,
            activebackground=p.SECONDARY_HOVER,
            activeforeground=p.TEXT,
            disabledforeground=p.MUTED,
            selectcolor=p.ACCENT,
            relief="solid",
            borderwidth=1,
            activeborderwidth=0,
            font=("Segoe UI", 9),
        )
    except tk.TclError:
        pass
    return menu


class FixedActionButton(tk.Frame):
    """Pixel-stable action button whose colours do not depend on ttk theme.

    Windows' ``vista``/Abaqus ttk theme can ignore a custom button background
    while still honoring a mapped white foreground.  That combination produced
    an apparently blank primary button (white text on the theme's white face).
    Use a classic Tk button for dialog actions so foreground/background are
    controlled as one unit on every state and every embedded Python/Tk build.
    """

    _ROLE_COLOURS = {
        "primary": {
            "background": ModernDialogPalette.PRIMARY,
            "foreground": "#ffffff",
            "activebackground": ModernDialogPalette.PRIMARY_HOVER,
            "activeforeground": "#ffffff",
            "disabledforeground": "#d0d0d0",
            "border": ModernDialogPalette.PRIMARY_ACTIVE,
            "focus": ModernDialogPalette.ACCENT,
        },
        "danger": {
            "background": ModernDialogPalette.DANGER,
            "foreground": "#ffffff",
            "activebackground": ModernDialogPalette.DANGER_HOVER,
            "activeforeground": "#ffffff",
            "disabledforeground": "#e0c4c1",
            "border": ModernDialogPalette.DANGER_ACTIVE,
            "focus": ModernDialogPalette.DANGER,
        },
        "secondary": {
            "background": ModernDialogPalette.SECONDARY,
            "foreground": ModernDialogPalette.TEXT,
            "activebackground": ModernDialogPalette.SECONDARY_HOVER,
            "activeforeground": ModernDialogPalette.TEXT,
            "disabledforeground": ModernDialogPalette.MUTED,
            "border": ModernDialogPalette.BORDER,
            "focus": ModernDialogPalette.ACCENT,
        },
    }

    def __init__(self, master, text, command, role="secondary", width=None, height=None):
        palette = ModernDialogPalette
        super().__init__(
            master,
            width=int(width or ModernDialogMetrics.BUTTON_WIDTH),
            height=int(height or ModernDialogMetrics.BUTTON_HEIGHT),
            background=getattr(master, "cget", lambda *_: palette.FOOTER)("background")
            if isinstance(master, tk.Widget) else palette.FOOTER,
            borderwidth=0,
            highlightthickness=0,
            takefocus=False,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._role = str(role or "secondary").lower()
        if self._role not in self._ROLE_COLOURS:
            self._role = "secondary"
        colours = self._ROLE_COLOURS[self._role]

        # Use tk.Button, not ttk.Button.  The Windows Vista theme may keep its
        # native white button face even when ttk foreground is mapped to white.
        # A Tk button gives us deterministic colour pairing and fixes invisible
        # primary/danger captions on Abaqus/Windows.
        self.button = tk.Button(
            self,
            text=str(text),
            command=command,
            takefocus=True,
            font=("Segoe UI Semibold", 9) if self._role != "secondary" else ("Segoe UI", 9),
            background=colours["background"],
            foreground=colours["foreground"],
            activebackground=colours["activebackground"],
            activeforeground=colours["activeforeground"],
            disabledforeground=colours["disabledforeground"],
            relief="flat",
            overrelief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=colours["border"],
            highlightcolor=colours["focus"],
            padx=10,
            pady=0,
            cursor="arrow",
        )
        self.button.pack(fill="both", expand=True)

        # Hover feedback is explicit so it remains consistent even when an
        # embedded Tcl/Tk build does not apply activebackground until click.
        self.button.bind("<Enter>", self._on_enter, add="+")
        self.button.bind("<Leave>", self._on_leave, add="+")
        self.button.bind("<FocusIn>", self._on_focus_in, add="+")
        self.button.bind("<FocusOut>", self._on_focus_out, add="+")
        register_qt_dialog_action(self, text, self._role)

    def _colours(self):
        return self._ROLE_COLOURS[self._role]

    def _is_disabled(self):
        try:
            return str(self.button.cget("state")) == "disabled"
        except Exception:
            return False

    def _on_enter(self, _event=None):
        if not self._is_disabled():
            colours = self._colours()
            self.button.configure(
                background=colours["activebackground"],
                foreground=colours["activeforeground"],
            )

    def _on_leave(self, _event=None):
        if not self._is_disabled():
            colours = self._colours()
            self.button.configure(
                background=colours["background"],
                foreground=colours["foreground"],
            )

    def _on_focus_in(self, _event=None):
        try:
            self.button.configure(highlightbackground=self._colours()["focus"])
        except tk.TclError:
            pass

    def _on_focus_out(self, _event=None):
        try:
            self.button.configure(highlightbackground=self._colours()["border"])
        except tk.TclError:
            pass

    def invoke(self):
        if self._is_disabled():
            return None
        return self.button.invoke()

    def set_default(self, enabled=True):
        """Show the subtle focus/default frame used by a Qt default button."""
        colours = self._colours()
        try:
            self.button.configure(
                highlightthickness=2 if enabled else 1,
                highlightbackground=colours["focus"] if enabled else colours["border"],
            )
        except tk.TclError:
            pass
        return self

    def focus_set(self):
        return self.button.focus_set()

    def configure(self, cnf=None, **kw):
        # Route common button options to the child button while retaining Frame
        # configure behaviour for geometry options.
        button_keys = {"text", "command", "state"}
        child = {key: kw.pop(key) for key in tuple(kw) if key in button_keys}
        # Preserve compatibility with older callers that assigned a ttk style;
        # the native Tk button intentionally owns its visual state now.
        kw.pop("style", None)
        if child:
            self.button.configure(**child)
            if "state" in child and str(child["state"]) != "disabled":
                self._on_leave()
        if cnf is not None or kw:
            return super().configure(cnf, **kw)
        return None


class QtDialogButtonBox(tk.Frame):
    """Reusable QDialogButtonBox-like footer for native WinUx dialogs.

    The optional status text occupies the stretchable left side while standard
    actions stay aligned to the lower-right with one shared button metric and
    gap.  ``FixedActionButton`` registration supplies default/reject semantics.
    """

    def __init__(
            self, master, *, status_var=None, status_color=None,
            background=None, top_separator=False):
        palette = ModernDialogPalette
        self._background = str(background or palette.WINDOW)
        super().__init__(
            master, background=self._background, borderwidth=0,
            highlightthickness=0)
        self.columnconfigure(1, weight=1)
        self._buttons = []
        self._left_buttons = []

        row = 0
        if top_separator:
            tk.Frame(
                self, height=1, background=palette.BORDER,
                borderwidth=0, highlightthickness=0,
            ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
            row = 1

        self.left_actions = tk.Frame(
            self, background=self._background, borderwidth=0,
            highlightthickness=0)
        self.left_actions.grid(row=row, column=0, sticky="w")

        self.status_label = None
        if status_var is not None:
            self.status_label = tk.Label(
                self, textvariable=status_var, anchor="w", justify="left",
                background=self._background,
                foreground=str(status_color or palette.DANGER),
                font=("Segoe UI", 8),
            )
            self.status_label.grid(
                row=row, column=1, sticky="ew", padx=(12, 12), pady=0)

        self.actions = tk.Frame(
            self, background=self._background, borderwidth=0,
            highlightthickness=0)
        self.actions.grid(row=row, column=2, sticky="e")

    def add_left_button(self, text, command, *, role="secondary", width=None, height=None):
        button = FixedActionButton(
            self.left_actions, str(text), command, role=role,
            width=width, height=height)
        if self._left_buttons:
            button.pack(side="left", padx=(ModernDialogMetrics.BUTTON_GAP, 0))
        else:
            button.pack(side="left")
        self._left_buttons.append(button)
        return button

    def add_button(self, text, command, *, role="secondary", width=None, height=None):
        button = FixedActionButton(
            self.actions, str(text), command, role=role,
            width=width, height=height)
        if self._buttons:
            button.pack(side="left", padx=(ModernDialogMetrics.BUTTON_GAP, 0))
        else:
            button.pack(side="left")
        self._buttons.append(button)
        return button

    def buttons(self):
        return tuple(self._buttons)

    def left_buttons(self):
        return tuple(self._left_buttons)


class StatusGlyph(tk.Canvas):
    """Small native-drawn semantic glyph; no external bitmap dependency."""

    def __init__(self, master, intent="info"):
        size = ModernDialogMetrics.ICON_SIZE
        super().__init__(
            master,
            width=size,
            height=size,
            background=ModernDialogPalette.SURFACE,
            highlightthickness=0,
            borderwidth=0,
        )
        self._intent = str(intent or "info").lower()
        self._draw()

    def _draw(self):
        self.delete("all")
        intent = self._intent
        if intent in ("danger", "error"):
            fill, fg, mark = "#fdebec", "#c53434", "!"
        elif intent in ("warning", "warn"):
            fill, fg, mark = "#fff5dd", "#b26b00", "!"
        elif intent == "success":
            fill, fg, mark = "#eaf7ef", "#18864b", "OK"
        elif intent == "question":
            fill, fg, mark = "#eaf3ff", "#0b6fd3", "?"
        else:
            fill, fg, mark = "#eaf3ff", "#0b6fd3", "i"
        self.create_oval(3, 3, 35, 35, fill=fill, outline=fg, width=1)
        self.create_text(
            19, 19,
            text=mark,
            fill=fg,
            font=("Segoe UI Semibold", 15),
            anchor="center",
        )


def fit_and_center_toplevel(window, parent, min_width=1, min_height=1):
    """Open a Tk top-level at its content-safe minimum, centered on *parent*.

    This is the standalone/widget-parent counterpart of the native WinUx dialog
    host policy.  It uses the actual requested layout size, respects the caller's
    minimum, centers even when the child is larger than the parent, and clamps
    the result to Tk's virtual desktop bounds.
    """
    if window is None:
        return None
    try:
        window.update_idletasks()
        width = max(int(min_width), int(window.winfo_reqwidth()))
        height = max(int(min_height), int(window.winfo_reqheight()))

        try:
            parent.update_idletasks()
        except Exception:
            pass
        try:
            px = int(parent.winfo_rootx())
            py = int(parent.winfo_rooty())
            pw = max(1, int(parent.winfo_width()))
            ph = max(1, int(parent.winfo_height()))
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        except Exception:
            x = (int(window.winfo_screenwidth()) - width) // 2
            y = (int(window.winfo_screenheight()) - height) // 2

        try:
            left = int(window.winfo_vrootx())
            top = int(window.winfo_vrooty())
            right = left + max(1, int(window.winfo_vrootwidth()))
            bottom = top + max(1, int(window.winfo_vrootheight()))
        except Exception:
            left = top = 0
            right = max(1, int(window.winfo_screenwidth()))
            bottom = max(1, int(window.winfo_screenheight()))

        width = min(width, max(1, right - left))
        height = min(height, max(1, bottom - top))
        x = min(max(x, left), max(left, right - width))
        y = min(max(y, top), max(top, bottom - height))

        window.minsize(width, height)
        try:
            horizontal, vertical = window.resizable()
            if not horizontal and not vertical:
                window.maxsize(width, height)
        except Exception:
            pass
        window.geometry("{}x{}+{}+{}".format(width, height, x, y))
        window.update_idletasks()
        return width, height, x, y
    except Exception:
        return None


def prepare_modern_toplevel(window, title, owner_hwnd=None):
    """Apply common window chrome without forcing modal semantics."""
    del owner_hwnd  # owner positioning/enable is managed by NativeDialogController.
    configure_modern_ttk_styles(window)
    install_qt_widget_behavior(window)
    install_qt_dialog_behavior(window)
    window.title(str(title))
    window.configure(background=ModernDialogPalette.WINDOW)
    # Classic Tk controls (Text/Listbox/Menu) do not use ttk styles. The option
    # database gives them the same Qt/Fusion selection/focus palette without
    # overriding per-dialog background choices.
    try:
        window.option_add("*selectBackground", ModernDialogPalette.SELECT)
        window.option_add("*selectForeground", ModernDialogPalette.TEXT)
        window.option_add("*insertBackground", ModernDialogPalette.TEXT)
        window.option_add("*highlightColor", ModernDialogPalette.FOCUS)
        window.option_add("*highlightBackground", ModernDialogPalette.BORDER)
    except tk.TclError:
        pass
    apply_tk_app_icon(window)
    # Keep the dialog a genuine native top-level HWND.  This gives WinUx the
    # same unconstrained movement/resizing model as QDialog instead of the
    # viewport-clipped behavior of an ImGui window.
    try:
        apply_native_qt_chrome(window)
    except Exception:
        pass
    return window


class StandaloneModernDialog(tk.Toplevel):
    """Theme-stable modal dialog usable outside WinUx's DPG dialog host.

    This is intentionally independent of ``NativeDialogController`` so helper
    processes such as Server Notepad can use exactly the same WinUx dialog
    visual language.  Buttons use :class:`FixedActionButton`, therefore Windows
    themes cannot alter their baseline, size, foreground or background.
    """

    def __init__(
        self,
        parent,
        title,
        message,
        *,
        heading=None,
        intent="info",
        actions=None,
        entry=False,
        initialvalue="",
        validator=None,
        entry_width=48,
        detail=None,
    ):
        super().__init__(master=parent)
        self.withdraw()
        self._parent = parent
        self._result = None
        self._validator = validator
        self._closed = False
        self._entry_var = tk.StringVar(master=self, value=str(initialvalue or ""))
        prepare_modern_toplevel(self, title)
        self.transient(parent)
        self.resizable(False, False)
        # Re-apply native flags after the final resize policy is known so the
        # non-client frame matches a fixed-size QDialog (Close only, no Max).
        apply_native_qt_chrome(self)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", self._cancel, add="+")

        outer = tk.Frame(self, background=ModernDialogPalette.WINDOW, borderwidth=0)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        body = tk.Frame(outer, background=ModernDialogPalette.SURFACE, borderwidth=0)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        glyph = StatusGlyph(body, intent)
        glyph.grid(
            row=0, column=0, rowspan=4, sticky="n",
            padx=(ModernDialogMetrics.PAD_X, 14),
            pady=(ModernDialogMetrics.PAD_Y + 1, 10),
        )

        heading_label = ttk.Label(
            body, text=str(heading or title), style="WinUxDialog.Title.TLabel", anchor="w")
        heading_label.grid(
            row=0, column=1, sticky="ew",
            padx=(0, ModernDialogMetrics.PAD_X),
            pady=(ModernDialogMetrics.PAD_Y, 6),
        )
        message_label = ttk.Label(
            body, text=str(message or ""), style="WinUxDialog.Message.TLabel",
            justify="left", anchor="nw", wraplength=520)
        message_label.grid(
            row=1, column=1, sticky="ew",
            padx=(0, ModernDialogMetrics.PAD_X), pady=(0, 8))

        self.entry = None
        if entry:
            self.entry = ttk.Entry(body, textvariable=self._entry_var, width=int(entry_width))
            self.entry.grid(
                row=2, column=1, sticky="ew",
                padx=(0, ModernDialogMetrics.PAD_X), pady=(0, 7))
            self.entry.bind("<Return>", self._accept_default, add="+")

        self.error_var = tk.StringVar(master=self, value="")
        self.error_label = ttk.Label(
            body, textvariable=self.error_var, style="WinUxDialog.Muted.TLabel",
            foreground=ModernDialogPalette.DANGER, anchor="w")
        self.error_label.grid(
            row=3, column=1, sticky="ew",
            padx=(0, ModernDialogMetrics.PAD_X), pady=(0, 7))

        if detail:
            ttk.Label(
                body, text=str(detail), style="WinUxDialog.Muted.TLabel",
                justify="left", anchor="nw", wraplength=520
            ).grid(row=4, column=1, sticky="ew",
                   padx=(0, ModernDialogMetrics.PAD_X), pady=(0, 10))

        tk.Frame(outer, height=1, background=ModernDialogPalette.BORDER).grid(
            row=1, column=0, sticky="ew")
        footer = tk.Frame(outer, background=ModernDialogPalette.FOOTER, borderwidth=0)
        footer.grid(row=2, column=0, sticky="ew")
        actions_frame = tk.Frame(footer, background=ModernDialogPalette.FOOTER, borderwidth=0)
        actions_frame.pack(
            side="right", padx=ModernDialogMetrics.FOOTER_PAD_X,
            pady=ModernDialogMetrics.FOOTER_PAD_Y)

        normalized = list(actions or [("OK", True, "primary")])
        self._default_value = normalized[-1][1] if normalized else None
        self._buttons = []
        for index, item in enumerate(normalized):
            label, value, role = item
            button = FixedActionButton(
                actions_frame, str(label),
                lambda v=value: self._finish(v), role=str(role or "secondary"))
            button.pack(
                side="left",
                padx=(0, ModernDialogMetrics.BUTTON_GAP) if index < len(normalized)-1 else 0)
            self._buttons.append((button, value))
        if self._buttons:
            self.bind("<Return>", self._accept_default, add="+")

        self.update_idletasks()
        self._center_over_parent()
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except Exception:
            pass
        if self.entry is not None:
            self.entry.focus_set()
            try:
                self.entry.selection_range(0, "end")
            except Exception:
                pass
        elif self._buttons:
            self._buttons[-1][0].focus_set()

    def _center_over_parent(self):
        fit_and_center_toplevel(
            self, self._parent,
            min_width=ModernDialogMetrics.MIN_WIDTH,
            min_height=ModernDialogMetrics.MIN_HEIGHT,
        )

    def _accept_default(self, _event=None):
        return self._finish(self._default_value)

    def _cancel(self, _event=None):
        return self._finish(None)

    def _finish(self, value):
        if self._closed:
            return "break"
        if self.entry is not None and value is not None:
            raw = self._entry_var.get()
            if self._validator is not None:
                try:
                    ok, converted, message = self._validator(raw)
                except Exception as exc:
                    ok, converted, message = False, None, str(exc)
                if not ok:
                    self.error_var.set(str(message or "Invalid value."))
                    self.entry.focus_set()
                    return "break"
                self._result = converted
            else:
                self._result = raw
        else:
            self._result = value
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        return "break"

    def show(self):
        self.wait_window(self)
        return self._result


def show_modern_message(parent, title, message, *, intent="info", heading=None, detail=None):
    return StandaloneModernDialog(
        parent, title, message, heading=heading, intent=intent,
        actions=[("OK", True, "primary")], detail=detail).show()


def ask_modern_confirm(
    parent, title, message, *, intent="question", heading=None,
    primary_text="OK", secondary_text="Cancel", primary_role="primary", detail=None,
):
    return StandaloneModernDialog(
        parent, title, message, heading=heading, intent=intent,
        actions=[
            (str(secondary_text), False, "secondary"),
            (str(primary_text), True, str(primary_role)),
        ], detail=detail).show()


def ask_modern_choice(parent, title, message, *, actions, intent="question", heading=None, detail=None):
    return StandaloneModernDialog(
        parent, title, message, heading=heading, intent=intent,
        actions=list(actions), detail=detail).show()


def ask_modern_text(
    parent, title, prompt, *, initialvalue="", heading=None,
    primary_text="OK", secondary_text="Cancel", validator=None, detail=None,
):
    return StandaloneModernDialog(
        parent, title, prompt, heading=heading or title, intent="info", entry=True,
        initialvalue=initialvalue, validator=validator, detail=detail,
        actions=[
            (str(secondary_text), None, "secondary"),
            (str(primary_text), True, "primary"),
        ]).show()


def ask_modern_integer(
    parent, title, prompt, *, initialvalue=None, minvalue=None, maxvalue=None, heading=None,
):
    def validate(raw):
        try:
            value = int(str(raw).strip())
        except Exception:
            return False, None, "Enter a whole number."
        if minvalue is not None and value < int(minvalue):
            return False, None, "Value must be at least {}.".format(int(minvalue))
        if maxvalue is not None and value > int(maxvalue):
            return False, None, "Value must be at most {}.".format(int(maxvalue))
        return True, value, ""
    return ask_modern_text(
        parent, title, prompt, initialvalue="" if initialvalue is None else str(initialvalue),
        heading=heading or title, validator=validate)


__all__ = [
    "FixedActionButton",
    "QtDialogButtonBox",
    "QtDialogHeader",
    "QtScrollArea",
    "QtGroupBox",
    "QtFormLayout",
    "QtTabWidget",
    "QtTreeView",
    "StandaloneModernDialog",
    "ModernDialogMetrics",
    "ModernDialogPalette",
    "StatusGlyph",
    "configure_modern_ttk_styles",
    "install_qt_dialog_behavior",
    "install_qt_widget_behavior",
    "register_qt_dialog_action",
    "install_qt_treeview_behavior",
    "install_qt_header_behavior",
    "resize_tree_column_to_contents",
    "configure_qt_menu",
    "prepare_modern_toplevel",
    "fit_and_center_toplevel",
    "show_modern_message",
    "ask_modern_confirm",
    "ask_modern_choice",
    "ask_modern_text",
    "ask_modern_integer",
]
