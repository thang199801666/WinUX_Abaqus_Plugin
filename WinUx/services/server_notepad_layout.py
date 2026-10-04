"""Server Notepad window chrome, menus, toolbar and dock construction."""
import os
import tkinter as tk
from tkinter import ttk
from WinUx.components.server_notepad_tabs import _ToolTip, _EditorTabStrip
from WinUx.components.shared_scroller import configure_ttk_scroller_styles
from WinUx.services.server_notepad_types import _ENCODING_LABELS, _EOL_NAMES


class ServerNotepadLayout:
    def __init__(self, view):
        self.view = view

    def _show_load_progress(self, show=True, value=None):
        view = self.view
        if value is not None:
            try:
                view._load_progress_var.set(float(value))
            except Exception:
                pass
        try:
            if show:
                if not view.load_progress.winfo_ismapped():
                    view.load_progress.pack(
                        side="left", padx=(2, 6), pady=1, before=view._status_stats_separator)
            else:
                view.load_progress.pack_forget()
        except Exception:
            pass


    def _build_dock_header(self, parent, title, close_command):
        view = self.view
        header = tk.Frame(parent, height=24, background="#ececec", borderwidth=0)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text=str(title), anchor="w", background="#ececec",
            foreground="#222222", font=("Segoe UI", 9, "bold"),
            padx=5, pady=0).pack(side="left", fill="both", expand=True)
        close = tk.Button(
            header, text="x", takefocus=False, width=2, relief="flat", borderwidth=0,
            padx=0, pady=0, background="#ececec", activebackground="#e81123",
            activeforeground="#ffffff", command=close_command)
        close.pack(side="right", fill="y")
        _ToolTip(close, "Close")
        return header


    def _build_window(self):
        view = self.view
        view.root.title("WinUx Server Notepad++")
        view.root.geometry("1120x760")
        view.root.minsize(760, 500)
        view.root.protocol("WM_DELETE_WINDOW", view._close_window_ui)
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "..", "Resources", "WinUx.ico")
            icon_path = os.path.abspath(icon_path)
            if os.path.isfile(icon_path):
                view.root.iconbitmap(icon_path)
        except Exception:
            pass

        style = ttk.Style(view.root)
        try:
            style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        except Exception:
            pass
        configure_ttk_scroller_styles(style)
        # Dense desktop-editor chrome.  Keep tabs rectangular and compact like
        # Notepad++ rather than the large rounded controls used by generic ttk
        # applications.  Toolbar buttons themselves are pixel-sized tk.Button
        # cells (see _build_toolbar) so every command remains perfectly square.
        style.configure(
            "ServerNotepad.TNotebook", tabmargins=(0, 1, 0, 0),
            borderwidth=0, background="#d9d9d9")
        style.configure(
            "ServerNotepad.TNotebook.Tab", padding=(8, 3),
            font=("Segoe UI", 9), borderwidth=1)
        style.map(
            "ServerNotepad.TNotebook.Tab",
            background=[
                ("selected", "#ffffff"),
                ("active", "#eaf3fb"),
                ("!selected", "#e5e5e5"),
            ],
            foreground=[("selected", "#111111"), ("!selected", "#333333")],
        )
        style.configure("ServerNotepad.Dock.TFrame", background="#f2f2f2")
        style.configure("ServerNotepad.DockHeader.TLabel",
                        background="#ececec", foreground="#222222",
                        font=("Segoe UI", 9, "bold"), padding=(5, 3))

        view._build_menu()
        view._build_toolbar()

        body = ttk.Frame(view.root)
        body.pack(fill="both", expand=True)

        # Notepad++-style docked panes: a document list on the left, editor
        # tabs in the centre and an optional function list on the right.
        view.main_pane = ttk.Panedwindow(body, orient="horizontal")
        view.main_pane.pack(fill="both", expand=True)

        view.document_panel = ttk.Frame(
            view.main_pane, width=176, style="ServerNotepad.Dock.TFrame")
        view._build_dock_header(
            view.document_panel, "Document List",
            lambda: (view._show_document_list.set(False), view._apply_document_list_visibility()))
        view.document_list = tk.Listbox(
            view.document_panel, activestyle="none", exportselection=False,
            borderwidth=0, highlightthickness=0, background="#f7f7f7")
        view.document_list.pack(fill="both", expand=True, padx=(3, 2), pady=(0, 3))
        view.document_list.bind("<<ListboxSelect>>", view._on_document_list_select, add="+")
        if view._show_document_list.get():
            view.main_pane.add(view.document_panel, weight=0)

        view.editor_panel = ttk.Frame(view.main_pane)
        # Hide native ttk tabs and render our own compact Notepad++-style tab
        # strip with real close buttons.  Notebook remains a reliable content
        # stack, so this visual refactor does not destabilize document widgets.
        try:
            # The Notebook is only a content stack.  Its native tab strip must
            # never be visible because WinUx renders a dedicated Notepad++-style
            # tab bar above it.  Hiding only Notebook.client is insufficient on
            # Windows/Vista themes: ttk can still paint TNotebook.Tab, producing
            # a second row with the filename.  Remove the tab element itself and
            # collapse every theme-dependent tab margin/padding.
            style.layout(
                "ServerNotepad.Content.TNotebook",
                [("Notebook.client", {"sticky": "nswe"})],
            )
            style.layout("ServerNotepad.Content.TNotebook.Tab", [])
            style.configure(
                "ServerNotepad.Content.TNotebook",
                tabmargins=(0, 0, 0, 0), borderwidth=0, padding=0,
            )
            style.configure(
                "ServerNotepad.Content.TNotebook.Tab",
                padding=0, borderwidth=0, width=0,
            )
        except Exception:
            pass
        view._tab_strip = _EditorTabStrip(view, view.editor_panel)
        view._tab_strip.pack(side="top", fill="x")
        view.notebook = ttk.Notebook(view.editor_panel, style="ServerNotepad.Content.TNotebook")
        view.notebook.pack(side="top", fill="both", expand=True)
        view.notebook.bind("<<NotebookTabChanged>>", view._on_tab_changed, add="+")

        # Notepad++-style Search Results dock.  It remains hidden until a
        # Find All operation is requested and can be dismissed independently.
        view.search_results_panel = ttk.Frame(view.editor_panel, relief="sunken", borderwidth=1)
        search_header = tk.Frame(
            view.search_results_panel, background="#ececec", height=24)
        search_header.pack(side="top", fill="x")
        search_header.pack_propagate(False)
        tk.Label(
            search_header, text="Search Results", anchor="w",
            background="#ececec", foreground="#222222",
            font=("Segoe UI", 9, "bold")).pack(
                side="left", fill="x", expand=True, padx=(5, 2))
        close_results = tk.Button(
            search_header, text="x", takefocus=False, width=2,
            relief="flat", borderwidth=0, padx=0, pady=0,
            background="#ececec", activebackground="#e81123",
            activeforeground="#ffffff", command=view._close_search_results)
        close_results.pack(side="right", fill="y", padx=0, pady=0)
        _ToolTip(close_results, "Close Search Results")
        view.search_results = tk.Listbox(
            view.search_results_panel, height=7, activestyle="none",
            exportselection=False, borderwidth=0, highlightthickness=0,
            background="#ffffff", font=(view._preferred_editor_font(), 9))
        view.search_results.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        view.search_results.bind("<Double-Button-1>", view._goto_search_result, add="+")

        view.main_pane.add(view.editor_panel, weight=1)

        view.function_panel = ttk.Frame(
            view.main_pane, width=220, style="ServerNotepad.Dock.TFrame")
        view._build_dock_header(
            view.function_panel, "Function List",
            lambda: (view._show_function_list.set(False), view._apply_function_list_visibility()))
        view.function_list = tk.Listbox(
            view.function_panel, activestyle="none", exportselection=False,
            borderwidth=0, highlightthickness=0, background="#f7f7f7")
        view.function_list.pack(fill="both", expand=True, padx=(3, 2), pady=(0, 3))
        view.function_list.bind("<Double-Button-1>", view._goto_selected_function, add="+")
        view._function_lines = []

        # Thin segmented status bar, closer to Notepad++ than ttk's tall
        # default widgets.  Each field stays visually square and aligned.
        view.statusbar = tk.Frame(
            view.root, height=22, background="#f2f2f2",
            highlightthickness=1, highlightbackground="#c6c6c6",
            borderwidth=0)
        view.statusbar.pack(side="bottom", fill="x")
        view.statusbar.pack_propagate(False)

        def status_label(variable, width=0, anchor="center", expand=False):
            label = tk.Label(
                view.statusbar, textvariable=variable, anchor=anchor,
                background="#f2f2f2", foreground="#202020",
                borderwidth=0, padx=5, pady=0,
                font=("Segoe UI", 9), width=width)
            label.pack(side="left", fill="x" if expand else "y",
                       expand=bool(expand))
            return label

        def status_separator():
            sep = tk.Frame(view.statusbar, width=1, background="#c7c7c7")
            sep.pack(side="left", fill="y", pady=2)
            return sep

        status_label(view._status_var, anchor="w", expand=True)
        view.load_progress = ttk.Progressbar(
            view.statusbar, orient="horizontal", mode="determinate",
            maximum=100.0, variable=view._load_progress_var, length=96)
        # Hidden while idle; inserted before the first fixed status field.
        view._status_stats_separator = status_separator()
        status_label(view._length_var, width=14)
        status_separator()
        status_label(view._lines_var, width=10)
        status_separator()
        status_label(view._position_var, width=17)
        status_separator()
        status_label(view._mode_var, width=5)
        status_separator()
        status_label(view._format_var, width=29)
        status_separator()
        status_label(view._zoom_var, width=6)


        # Global editor shortcuts.  Return "break" where needed so Tk does not
        # also insert the shortcut character into the text widget.
        bindings = {
            "<Control-o>": view._shortcut_open,
            "<Control-s>": view._shortcut_save,
            "<Control-Shift-S>": view._shortcut_save_all,
            "<Control-f>": view._shortcut_find,
            "<Control-h>": view._shortcut_replace,
            "<Control-g>": view._shortcut_goto,
            "<Control-r>": view._shortcut_reload,
            "<Control-w>": view._shortcut_close_tab,
            "<F3>": view._shortcut_find_next,
            "<Shift-F3>": view._shortcut_find_previous,
            "<Control-plus>": view._shortcut_zoom_in,
            "<Control-equal>": view._shortcut_zoom_in,
            "<Control-minus>": view._shortcut_zoom_out,
            "<Control-0>": view._shortcut_zoom_reset,
            "<Control-Tab>": view._shortcut_next_tab,
            "<Control-Shift-Tab>": view._shortcut_previous_tab,
            "<Control-Prior>": view._shortcut_previous_tab,
            "<Control-Next>": view._shortcut_next_tab,
            "<Control-F2>": view._shortcut_toggle_bookmark,
            "<F2>": view._shortcut_next_bookmark,
            "<Shift-F2>": view._shortcut_previous_bookmark,
            "<Control-d>": view._shortcut_duplicate_line,
            "<Control-l>": view._shortcut_delete_line,
        }
        for sequence, callback in bindings.items():
            view.bind(sequence, callback, add="+")


    def _build_menu(self):
        view = self.view
        menu = tk.Menu(view.root, tearoff=False)
        view.root.configure(menu=menu)

        file_menu = tk.Menu(menu, tearoff=False)
        view.file_menu = file_menu
        file_menu.add_command(label="Open Server Path...", accelerator="Ctrl+O", command=view._open_server_path)
        view.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Recent Server Files", menu=view.recent_menu)
        view._rebuild_recent_menu()
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=view._save_active)
        file_menu.add_command(label="Save All", accelerator="Ctrl+Shift+S", command=view._save_all)
        file_menu.add_separator()
        file_menu.add_command(label="Reload from Server", accelerator="Ctrl+R", command=view._reload_active)
        file_menu.add_command(label="Force Save to Server", command=lambda: view._save_active(force=True))
        file_menu.add_separator()
        file_menu.add_command(label="Close", accelerator="Ctrl+W", command=view._close_active_tab)
        file_menu.add_command(label="Close All", command=view._close_all_tabs)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Alt+F4", command=view._close_window_ui)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=lambda: view._text_event("<<Undo>>"))
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=lambda: view._text_event("<<Redo>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: view._text_event("<<Cut>>"))
        edit_menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: view._text_event("<<Copy>>"))
        edit_menu.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: view._text_event("<<Paste>>"))
        edit_menu.add_command(label="Delete", accelerator="Del", command=view._delete_selection)
        edit_menu.add_separator()
        edit_menu.add_command(label="Duplicate Current Line", accelerator="Ctrl+D", command=view._duplicate_current_line)
        edit_menu.add_command(label="Delete Current Line", accelerator="Ctrl+L", command=view._delete_current_line)
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All", accelerator="Ctrl+A", command=view._select_all)
        menu.add_cascade(label="Edit", menu=edit_menu)

        search_menu = tk.Menu(menu, tearoff=False)
        search_menu.add_command(label="Find...", accelerator="Ctrl+F", command=lambda: view._show_find_replace(False))
        search_menu.add_command(label="Find Next", accelerator="F3", command=lambda: view._find_next(True))
        search_menu.add_command(label="Find Previous", accelerator="Shift+F3", command=lambda: view._find_next(False))
        search_menu.add_command(label="Replace...", accelerator="Ctrl+H", command=lambda: view._show_find_replace(True))
        search_menu.add_command(label="Find All in Current Document", command=view._find_all_current)
        search_menu.add_separator()
        search_menu.add_command(label="Go to Line...", accelerator="Ctrl+G", command=view._goto_line)
        bookmark_menu = tk.Menu(search_menu, tearoff=False)
        bookmark_menu.add_command(label="Toggle Bookmark", accelerator="Ctrl+F2", command=view._toggle_bookmark)
        bookmark_menu.add_command(label="Next Bookmark", accelerator="F2", command=lambda: view._goto_bookmark(1))
        bookmark_menu.add_command(label="Previous Bookmark", accelerator="Shift+F2", command=lambda: view._goto_bookmark(-1))
        bookmark_menu.add_command(label="Clear All Bookmarks", command=view._clear_bookmarks)
        search_menu.add_cascade(label="Bookmark", menu=bookmark_menu)
        menu.add_cascade(label="Search", menu=search_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(label="Word Wrap", variable=view._word_wrap, command=view._apply_word_wrap)
        view_menu.add_checkbutton(label="Line Numbers", variable=view._show_line_numbers, command=view._apply_line_number_visibility)
        view_menu.add_checkbutton(label="Status Bar", variable=view._show_statusbar, command=view._apply_statusbar_visibility)
        view_menu.add_checkbutton(label="Document List", variable=view._show_document_list, command=view._apply_document_list_visibility)
        view_menu.add_checkbutton(label="Function List", variable=view._show_function_list, command=view._apply_function_list_visibility)
        view_menu.add_checkbutton(label="Highlight Current Line", variable=view._highlight_current_line, command=view._apply_current_line_highlight)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom In", accelerator="Ctrl++", command=view._zoom_in)
        view_menu.add_command(label="Zoom Out", accelerator="Ctrl+-", command=view._zoom_out)
        view_menu.add_command(label="Restore Default Zoom", accelerator="Ctrl+0", command=view._zoom_reset)
        menu.add_cascade(label="View", menu=view_menu)

        view.encoding_menu = tk.Menu(menu, tearoff=False)
        for value, label in _ENCODING_LABELS.items():
            view.encoding_menu.add_radiobutton(
                label=label,
                variable=view._encoding_var,
                value=label,
                command=lambda v=value: view._set_active_encoding(v),
            )
        menu.add_cascade(label="Encoding", menu=view.encoding_menu)

        eol_menu = tk.Menu(menu, tearoff=False)
        for eol, label in _EOL_NAMES.items():
            eol_menu.add_radiobutton(
                label=label,
                variable=view._eol_var,
                value=label,
                command=lambda v=eol: view._set_active_eol(v),
            )
        menu.add_cascade(label="EOL Conversion", menu=eol_menu)

        view.language_menu = tk.Menu(menu, tearoff=False)
        for language in (
                "Normal Text", "Abaqus INP", "Python", "JSON", "XML/HTML",
                "C/C++", "Fortran", "Shell", "YAML"):
            view.language_menu.add_radiobutton(
                label=language,
                variable=view._language_var,
                value=language,
                command=lambda v=language: view._set_active_language(v),
            )
        menu.add_cascade(label="Language", menu=view.language_menu)

        settings_menu = tk.Menu(menu, tearoff=False)
        settings_menu.add_command(label="Style Configurator...", command=view._show_style_configurator)
        settings_menu.add_command(label="Preferences...", command=view._show_preferences)
        menu.add_cascade(label="Settings", menu=settings_menu)

        window_menu = tk.Menu(menu, tearoff=False)
        window_menu.add_command(label="Next Document", accelerator="Ctrl+Tab", command=lambda: view._switch_tab(1))
        window_menu.add_command(label="Previous Document", accelerator="Ctrl+Shift+Tab", command=lambda: view._switch_tab(-1))
        window_menu.add_separator()
        window_menu.add_command(label="Close Current Document", accelerator="Ctrl+W", command=view._close_active_tab)
        window_menu.add_command(label="Close All Documents", command=view._close_all_tabs)
        menu.add_cascade(label="Window", menu=window_menu)

        server_menu = tk.Menu(menu, tearoff=False)
        server_menu.add_command(label="Reload from Server", command=view._reload_active)
        server_menu.add_command(label="Force Save to Server", command=lambda: view._save_active(force=True))
        server_menu.add_command(label="Copy Server Path", command=view._copy_server_path)
        menu.add_cascade(label="Server", menu=server_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About WinUx Server Notepad", command=view._about)
        menu.add_cascade(label="?", menu=help_menu)


    def _build_toolbar(self):
        view = self.view
        """Build a dense Notepad++-style icon toolbar.

        Toolbar assets are prepared ahead of startup on a 28px transparent
        canvas.  The complete command set uses one coherent classic desktop
        icon family and normalises visible artwork to roughly 23-24px, so mixed
        source artwork never produces oversized or undersized buttons.  Runtime
        only loads the prepared PNGs; it never performs per-pixel transforms.
        """
        toolbar_bg = "#f5f5f5"
        hover_bg = "#e5f1fb"
        pressed_bg = "#cce4f7"
        hover_border = "#7eb4dc"
        pressed_border = "#4f9bd3"
        separator_color = "#c5c5c5"
        button_size = 30
        icon_size = 28
        bar = tk.Frame(
            view.root, background=toolbar_bg, height=34,
            highlightthickness=0, borderwidth=0)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        view.toolbar = bar

        # 1px divider below the toolbar gives the same crisp separation as
        # classic Windows editors without wasting vertical workspace.
        tk.Frame(view.root, height=1, background="#c9c9c9").pack(
            side="top", fill="x")

        def icon(name):
            if not name:
                return None
            if name in view._toolbar_images:
                return view._toolbar_images[name]
            resources = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "Resources"))
            # Pre-sized/cropped 28px toolbar assets keep startup deterministic.
            # Runtime pixel scanning through PhotoImage.transparency_get() performs a
            # Tcl round-trip for every pixel and could hold Tk startup beyond
            # the 10 s ready watchdog.  Loading the prepared PNG is O(1) from
            # Tk's point of view and keeps the visible artwork near 28x28.
            prepared = os.path.join(resources, "EditorToolbar28", name + ".png")
            source_path = os.path.join(resources, name + ".png")
            try:
                image = tk.PhotoImage(master=view.root, file=prepared)
            except Exception:
                try:
                    source = tk.PhotoImage(master=view.root, file=source_path)
                    # Dependency-free fallback only.  Never scan pixels here.
                    factor = max(1, int(round(
                        max(source.width(), source.height()) / 22.0)))
                    image = source.subsample(factor, factor) if factor > 1 else source
                except Exception:
                    return None
            view._toolbar_images[name] = image
            return image

        def button(label, command, icon_name=None, fallback=None):
            cell = tk.Frame(
                bar, width=button_size, height=button_size,
                background=toolbar_bg, highlightthickness=1,
                highlightbackground=toolbar_bg, highlightcolor=toolbar_bg,
                borderwidth=0)
            cell.pack(side="left", padx=(1, 0), pady=2)
            cell.pack_propagate(False)
            image = icon(icon_name)
            kwargs = dict(
                command=command, takefocus=False, relief="flat",
                overrelief="flat", borderwidth=0, highlightthickness=0,
                padx=0, pady=0, background=toolbar_bg,
                activebackground=pressed_bg, foreground="#202020",
                activeforeground="#202020", cursor="arrow",
                font=("Segoe UI", 9),
            )
            if image is not None:
                kwargs.update(image=image, text="", compound="center")
            else:
                kwargs.update(text=str(fallback if fallback is not None else label))
            widget = tk.Button(cell, **kwargs)
            widget.pack(fill="both", expand=True, padx=1, pady=1)

            def apply_state(background, border):
                try:
                    widget.configure(background=background)
                    cell.configure(
                        background=border,
                        highlightbackground=border,
                        highlightcolor=border)
                except Exception:
                    pass

            def enter(_event=None):
                apply_state(hover_bg, hover_border)

            def leave(_event=None):
                apply_state(toolbar_bg, toolbar_bg)

            def press(_event=None):
                apply_state(pressed_bg, pressed_border)

            def release(_event=None):
                try:
                    inside = bool(widget.winfo_containing(
                        widget.winfo_pointerx(), widget.winfo_pointery()) == widget)
                except Exception:
                    inside = True
                apply_state(hover_bg, hover_border) if inside else leave()

            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
            widget.bind("<ButtonPress-1>", press, add="+")
            widget.bind("<ButtonRelease-1>", release, add="+")
            _ToolTip(widget, label)
            return widget

        def separator():
            holder = tk.Frame(
                bar, width=7, height=button_size, background=toolbar_bg)
            holder.pack(side="left", padx=1, pady=2)
            holder.pack_propagate(False)
            tk.Frame(holder, width=1, background=separator_color).pack(
                side="left", fill="y", padx=(3, 0), pady=4)

        button("Open Server Path  Ctrl+O", view._open_server_path, "Editor_OpenServer", "O")
        separator()
        button("Save  Ctrl+S", view._save_active, "Editor_Save", "S")
        button("Save All  Ctrl+Shift+S", view._save_all, "Editor_SaveAll", "SA")
        button("Reload from Server  Ctrl+R", view._reload_active, "Editor_Reload", "R")
        separator()
        button("Undo  Ctrl+Z", lambda: view._text_event("<<Undo>>"), "Editor_Undo", "U")
        button("Redo  Ctrl+Y", lambda: view._text_event("<<Redo>>"), "Editor_Redo", "R")
        separator()
        button("Cut  Ctrl+X", lambda: view._text_event("<<Cut>>"), "Cut", "Cut")
        button("Copy  Ctrl+C", lambda: view._text_event("<<Copy>>"), "Copy", "C")
        button("Paste  Ctrl+V", lambda: view._text_event("<<Paste>>"), "Paste", "P")
        separator()
        button("Find  Ctrl+F", lambda: view._show_find_replace(False), "Editor_Find", "F")
        button("Replace  Ctrl+H", lambda: view._show_find_replace(True), "Editor_Replace", "R")
        button("Go to Line  Ctrl+G", view._goto_line, "Editor_Goto", "G")
        button("Toggle Bookmark  Ctrl+F2", view._toggle_bookmark, "Editor_Bookmark", "B")
        separator()
        button("Zoom Out", view._zoom_out, "Editor_ZoomOut", "-")
        button("Reset Zoom  Ctrl+0", view._zoom_reset, "Editor_ZoomReset", "1:1")
        button("Zoom In", view._zoom_in, "Editor_ZoomIn", "+")
        separator()
        view.force_toolbar_button = button(
            "Force Save to Server", lambda: view._save_active(force=True),
            "Upload", "Save")

