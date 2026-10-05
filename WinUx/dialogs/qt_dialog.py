"""Qt-like dialog lifecycle and layouts rendered exclusively by Dear PyGui."""
from __future__ import annotations

import threading
from contextlib import contextmanager
import dearpygui.dearpygui as dpg

from .base import DialogBase, register_escape_target, unregister_escape_target
from .theme import (
    DialogMetrics, DialogPalette, dialog_theme, primary_button_theme,
    secondary_button_theme, danger_button_theme, surface_theme, footer_theme, body_theme,
    muted_text_theme, error_text_theme, navigation_theme,
    bind_combo_style, refresh_combo_theme,
    line_edit_shell_theme, line_edit_editor_theme, plain_text_edit_theme,
)
from ..components.explorer_list_view import register_modal_window, unregister_modal_window
from ..runtime.latest_call import LatestCallQueue
from ..widgets.imgui_qt_style import METRICS, form_row_theme, form_label_cell_theme
from ..widgets import (
    QObject, QPushButton, ImGuiLineEdit, ImGuiSpinBox, ImGuiDoubleSpinBox,
    ImGuiGroupBox, ImGuiCheckBox, ImGuiRadioButtonGroup, ImGuiProgressBar,
    QGridLayout, QLabel, QtDataGridView,
)


_DIALOGS = []
_KEYS = None


def _editor_is_active():
    # Bundled DPG 2.3 exposes per-item active state, not is_any_item_active.
    any_active = getattr(dpg, "is_any_item_active", None)
    if callable(any_active):
        return bool(any_active())
    focused = dpg.get_focused_item()
    return bool(focused and dpg.does_item_exist(focused) and dpg.is_item_active(focused))


def _dispatch_key(sender, key):
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    for dialog in reversed(tuple(_DIALOGS)):
        if not dialog.winfo_exists() or not dpg.is_item_shown(dialog.tag):
            continue
        if not dialog.modal and not dpg.is_item_focused(dialog.tag):
            continue
        shortcut = dialog.shortcuts.get((key, ctrl))
        if shortcut:
            shortcut()
            return
        table = dialog.active_table
        if table is not None and not _editor_is_active():
            table.navigate(key, ctrl=ctrl, shift=shift)
        return


def _dispatch_return(*_args):
    for dialog in reversed(tuple(_DIALOGS)):
        if dialog.winfo_exists() and dpg.is_item_shown(dialog.tag):
            if dialog.modal or dpg.is_item_focused(dialog.tag):
                dialog.invoke_default()
                return


def _install_keys():
    global _KEYS
    if _KEYS is None or not dpg.does_item_exist(_KEYS):
        with dpg.handler_registry() as _KEYS:
            dpg.add_key_press_handler(key=dpg.mvKey_Return, callback=_dispatch_return)
            for key in (dpg.mvKey_Up, dpg.mvKey_Down, dpg.mvKey_Home, dpg.mvKey_End,
                        dpg.mvKey_Prior, dpg.mvKey_Next, dpg.mvKey_A,
                        dpg.mvKey_Spacebar, dpg.mvKey_F2, dpg.mvKey_Delete, dpg.mvKey_C):
                dpg.add_key_press_handler(key=key, callback=_dispatch_key)


class QtDialog(DialogBase):
    """QDialog contract, pinned button box and scrollable body in the UI viewport.

    ``post`` marshals background results through the application's UI queue;
    its lifetime check also discards results arriving after close.
    """

    def __init__(self, view, title, width=560, height=360, modal=True, footer=True):
        self.view = view
        self.modal = bool(modal)
        self.tag = dpg.generate_uuid()
        self.width, self.height = width, height
        self._closed = False
        self._destroy_scheduled = False
        self._resize_registry = None
        self._default = None
        self._default_button = None
        self._ui_thread = threading.get_ident()
        self._latest_updates = LatestCallQueue(view.after)
        self._widget_owner = QObject(after=view.after)
        self._owned_dialogs = []
        self._control_handler_registries = []
        self._line_edit_shells = {}  # legacy compatibility; new fields are direct ImGuiLineEdit
        self._control_wrappers = {}
        self.enter_editors = set()
        self.shortcuts = {}
        self.active_table = None
        self.has_footer = bool(footer)
        with dpg.window(tag=self.tag, label=title, width=width, height=height,
                        modal=self.modal, no_collapse=True, no_scrollbar=True,
                        no_scroll_with_mouse=True,
                        min_size=(DialogMetrics.MIN_DIALOG_WIDTH, DialogMetrics.MIN_DIALOG_HEIGHT),
                        on_close=lambda: self._close_from_escape()):
            self.content = dpg.add_child_window(width=-1, height=-(DialogMetrics.FOOTER_HEIGHT+1) if footer else -1,
                                                border=False, no_scrollbar=False, no_scroll_with_mouse=False,
                                                always_use_window_padding=True)
            self.footer_shell = self.footer = None
            if footer:
                dpg.add_separator()
                with dpg.child_window(width=-1, height=DialogMetrics.FOOTER_HEIGHT, border=False,
                                      no_scrollbar=True, always_use_window_padding=True) as self.footer_shell:
                    self.footer = dpg.add_group()
        dpg.bind_item_theme(self.tag, dialog_theme())
        dpg.bind_item_theme(self.content, body_theme())
        if footer:
            dpg.bind_item_theme(self.footer_shell, footer_theme())
        self._bind_resize_handler()
        self.show()
        self.center()
        _DIALOGS.append(self)
        _install_keys()

    def _apply_layout(self):
        if self.winfo_exists():
            dpg.configure_item(self.content, width=-1, height=-(DialogMetrics.FOOTER_HEIGHT+1) if self.has_footer else -1)
            if self.has_footer:
                dpg.configure_item(self.footer_shell, width=-1, height=DialogMetrics.FOOTER_HEIGHT)
            status = getattr(self, "_footer_status", None)
            if status is not None:
                dpg.configure_item(
                    status,
                    wrap=max(
                        80,
                        dpg.get_item_width(self.tag)
                        - getattr(self, "_footer_left_width", 0)
                        - self._footer_right_width - 60,
                    ),
                )

    def show(self):
        if not self.winfo_exists():
            return False
        # Explorer's custom global pollers must not see through a dialog.
        register_modal_window(self.tag)
        register_escape_target(self.tag, self._close_from_escape)
        if self in _DIALOGS:
            _DIALOGS.remove(self)
            _DIALOGS.append(self)
        dpg.show_item(self.tag)
        dpg.focus_item(self.tag)
        return True

    lift = show
    activate = show
    focus = show

    def hide(self):
        if self.winfo_exists():
            dpg.hide_item(self.tag)
            unregister_escape_target(self.tag)
            unregister_modal_window(self.tag)

    def post(self, command, *args, **kwargs):
        if self._closed:
            return False
        def deliver():
            if self.winfo_exists():
                self.handle_command(command, *args, **kwargs)
        self.view.after(0, deliver)
        return True

    def post_latest(self, command, *args, **kwargs):
        """Queue only the newest visual state; ordinary commands use post()."""
        if self._closed:
            return False
        def deliver():
            if self.winfo_exists():
                self.handle_command(command, *args, **kwargs)
        return self._latest_updates.post(command, deliver)

    def on_ui(self, callback, *args):
        if threading.get_ident() == self._ui_thread:
            if self.winfo_exists():
                callback(*args)
        else:
            def deliver():
                if self.winfo_exists():
                    callback(*args)
            self.view.after(0, deliver)

    def handle_command(self, command, *args, **kwargs):
        raise ValueError("Unknown dialog command: {}".format(command))

    def action(self, label, callback, role="secondary", default=False, parent=None,
               width=None, height=None):
        widget = self.own_widget(QPushButton(
            label,
            width=self.action_width(label) if width is None else int(width),
            height=DialogMetrics.BUTTON_HEIGHT if height is None else int(height),
            role=role, default=default, parent=parent or self.footer,
            after=self.view.after, backend=dpg))
        widget.clicked.connect(callback)
        button = widget.tag
        wrappers = getattr(self, "_control_wrappers", None)
        if wrappers is not None:
            wrappers[button] = widget
        # ImGuiPushButton owns the shared state/theme contract.  Avoid rebinding
        # a second dialog-local theme here so hover/disabled/default behavior is
        # identical in dialogs and non-dialog tool panels.
        if default:
            self._default, self._default_button = callback, button
        return button

    @staticmethod
    def action_width(label):
        return max(DialogMetrics.BUTTON_WIDTH, len(label) * 7 + 16)

    def button_box(self, actions, left_actions=(), status_item=None, status_left_padding=0):
        """QDialogButtonBox-like layout with auxiliary actions on the left.

        The old footer placed status text and auxiliary buttons in the same
        horizontal group, so long status messages squeezed buttons and shifted
        the accept/cancel group between dialogs.  Qt keeps those roles in
        independent layout slots; mirror that here.
        """
        actions = list(actions or ())
        left_actions = list(left_actions or ())

        def group_width(items):
            if not items:
                return 0
            return sum(self.action_width(item[0]) for item in items) + \
                DialogMetrics.BUTTON_GAP * max(0, len(items) - 1)

        right_width = group_width(actions)
        left_width = group_width(left_actions)
        self._footer_left_width = left_width
        self._footer_right_width = right_width
        self._footer_status = status_item
        minimum_width = max(
            DialogMetrics.MIN_DIALOG_WIDTH,
            left_width + right_width + (160 if status_item is not None else 40) + 32,
        )
        dpg.configure_item(
            self.tag,
            min_size=(minimum_width, DialogMetrics.MIN_DIALOG_HEIGHT),
        )
        if self.width < minimum_width:
            self.width = minimum_width
            dpg.configure_item(self.tag, width=minimum_width)

        with dpg.table(parent=self.footer, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
                       borders_innerH=False, borders_outerH=False,
                       borders_innerV=False, borders_outerV=False):
            if left_actions:
                dpg.add_table_column(width_fixed=True, init_width_or_weight=left_width)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=max(1, right_width))
            with dpg.table_row():
                if left_actions:
                    with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP) as left:
                        self.left_buttons = [
                            self.action(label, callback, role, default, left)
                            for label, callback, role, default in left_actions
                        ]
                else:
                    self.left_buttons = []
                if status_item is not None:
                    with dpg.group(horizontal=True) as status_host:
                        # Keep status/help text visually separated from auxiliary
                        # footer actions.  Qt's button-box layouts leave breathing
                        # room between the left action cluster and the expanding
                        # status slot; Dear ImGui tables otherwise place the text
                        # almost flush against the preceding button.
                        status_pad = max(0, int(status_left_padding or 0))
                        if status_pad:
                            dpg.add_spacer(width=status_pad)
                        dpg.move_item(status_item, parent=status_host)
                        dpg.configure_item(
                            status_item,
                            wrap=max(80, self.width-left_width-right_width-60-status_pad))
                else:
                    dpg.add_spacer(width=1)
                with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP) as group:
                    return [
                        self.action(label, callback, role, default, group)
                        for label, callback, role, default in actions
                    ]

    def form_layout(self, parent=None, *, label_width=None):
        """Create one shared QFormLayout-like table for multiple fields.

        Using one table for an entire form is important: a separate Dear ImGui
        table for every row inherits vertical item spacing between tables and
        makes compact dialogs look disconnected.  This helper centralizes one
        label column and one stretching editor column, matching Qt's
        QFormLayout much more closely.
        """
        table = dpg.add_table(
            parent=parent or self.content,
            header_row=False, width=-1,
            policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=False, borders_outerH=False,
            borders_innerV=False, borders_outerV=False,
        )
        dpg.add_table_column(
            parent=table, width_fixed=True,
            init_width_or_weight=int(label_width or DialogMetrics.LABEL_WIDTH))
        dpg.add_table_column(parent=table, width_stretch=True)
        dpg.bind_item_theme(table, form_row_theme(dpg))
        return table

    def form_layout_row(self, table, label, builder):
        """Append one label/editor row to ``form_layout`` and return editor."""
        with dpg.table_row(parent=table):
            label_cell = dpg.add_child_window(
                width=-1, height=DialogMetrics.CONTROL_HEIGHT, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            dpg.bind_item_theme(label_cell, form_label_cell_theme(dpg))
            if label:
                dpg.add_text(str(label), parent=label_cell)
            with dpg.group() as editor_cell:
                return builder(editor_cell)

    def summary_grid(self, items, parent=None, *, columns=2, label_width=72):
        """Create a compact read-only Qt property/summary grid.

        Summary blocks used to be hand-written four-column Dear ImGui tables.
        Keeping them here gives every dialog the same label/value spacing and
        prevents one-off tables from drifting away from the QFormLayout
        metrics used by editable forms. ``items`` is an iterable of
        ``(label, value)`` pairs laid out left-to-right across ``columns``
        logical fields per row.
        """
        pairs = [(str(label), "-" if value is None else str(value))
                 for label, value in items]
        logical_columns = max(1, int(columns or 1))
        table = dpg.add_table(
            parent=parent or self.content, header_row=False, width=-1,
            policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=False, borders_outerH=False,
            borders_innerV=False, borders_outerV=False,
        )
        for _ in range(logical_columns):
            dpg.add_table_column(
                parent=table, width_fixed=True,
                init_width_or_weight=max(44, int(label_width)))
            dpg.add_table_column(parent=table, width_stretch=True)
        try:
            dpg.bind_item_theme(table, form_row_theme(dpg))
        except Exception:
            pass
        for offset in range(0, len(pairs), logical_columns):
            row_items = pairs[offset:offset + logical_columns]
            with dpg.table_row(parent=table):
                for index in range(logical_columns):
                    if index < len(row_items):
                        label, value = row_items[index]
                        label_item = dpg.add_text(label)
                        dpg.bind_item_theme(label_item, muted_text_theme())
                        dpg.add_text(value)
                    else:
                        dpg.add_text("")
                        dpg.add_text("")
        return table

    def labeled_widget(self, label, builder, parent=None):
        """One QFormLayout-style row with a shared label column width."""
        grid = self.own_widget(QGridLayout(2,
            column_widths=(DialogMetrics.LABEL_WIDTH, None), parent=parent or self.content,
            after=self.view.after, backend=dpg))
        try:
            dpg.bind_item_theme(grid.tag, form_row_theme(dpg))
            label_cell = grid.cell(0, 0)
            dpg.add_spacer(parent=label_cell.tag, height=METRICS.form_label_top_pad)
            QLabel(label, parent=label_cell)
            dpg.push_container_stack(grid.cell(0, 1).tag)
            try:
                return builder()
            finally:
                dpg.pop_container_stack()
        except Exception:
            grid.delete()
            raise

    def _focus_text_editor_now(self, item):
        if not item or not dpg.does_item_exist(item):
            return
        try:
            if not dpg.get_item_configuration(item).get("enabled", True):
                return
            # Do not overwrite the insertion point from a real mouse click.
            # Repair focus only when Dear ImGui did not keep the editor active.
            state = dpg.get_item_state(item) or {}
            if state.get("active", False):
                return
            dpg.focus_item(item)
        except Exception:
            pass

    def focus_editor(self, item):
        """Assign keyboard-navigation focus to an InputText explicitly.

        This helper is for keyboard/programmatic navigation only. Mouse clicks
        are never routed through it; Dear ImGui must receive those directly so
        it owns the insertion position and blinking caret.
        """
        self._focus_text_editor_now(item)
        try:
            frame = int(dpg.get_frame_count())
            for offset in (1, 2):
                dpg.set_frame_callback(
                    frame + offset,
                    lambda *_args, _item=item, **_kwargs:
                        self._focus_text_editor_now(_item),
                )
        except Exception:
            pass

    def _refresh_line_edit_shell(self, item):
        shell = self._line_edit_shells.get(item)
        if not shell or not dpg.does_item_exist(shell) or not dpg.does_item_exist(item):
            return
        try:
            enabled = bool(dpg.get_item_configuration(item).get("enabled", True))
        except Exception:
            enabled = True
        try:
            state = dpg.get_item_state(item) or {}
            focused = bool(state.get("focused", False) or state.get("active", False))
        except Exception:
            focused = False
        dpg.bind_item_theme(
            shell,
            line_edit_shell_theme(focused=enabled and focused, disabled=not enabled),
        )

    def _bind_line_edit_shell_handlers(self, item):
        try:
            with dpg.item_handler_registry() as registry:
                # Mouse activation must remain entirely owned by ImGui's
                # InputText. Calling focus_item() from an item-click callback
                # can leave the editor with navigation focus only (blue border,
                # no blinking insertion caret) on the bundled DPG build.
                if hasattr(dpg, "add_item_focus_handler"):
                    dpg.add_item_focus_handler(
                        callback=lambda *_args, _item=item: self._refresh_line_edit_shell(_item))
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(
                        callback=lambda *_args, _item=item: self._refresh_line_edit_shell(_item))
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(
                        callback=lambda *_args, _item=item: self._refresh_line_edit_shell(_item))
            dpg.bind_item_handler_registry(item, registry)
            self._control_handler_registries.append(registry)
        except Exception:
            pass

    def line_edit(self, value="", parent=None, **kwargs):
        """Create a direct Dear ImGui editor with QLineEdit-like properties.

        Earlier builds wrapped InputText in a child-window shell to draw a
        focus border.  That made the control look closer to Qt, but it also
        introduced an extra item boundary around the editor and made caret
        activation less predictable.  The retained ImGuiLineEdit keeps one
        real mvInputText as the entire hit target so Dear ImGui exclusively
        owns mouse selection, insertion position and caret blinking.
        """
        options = dict(kwargs)
        requested_width = int(options.pop("width", -1))
        native_parent = options.pop("parent", parent)
        multiline = bool(options.get("multiline", False))
        if multiline:
            options.pop("multiline", None)
            return self.plain_text_edit(
                value, parent=native_parent, width=requested_width, **options)

        widget = self.own_widget(ImGuiLineEdit(
            str(value), parent=native_parent, after=self.view.after, backend=dpg,
            width=requested_width, **options))
        self._control_wrappers[widget.tag] = widget
        return widget.tag


    def plain_text_edit(self, value="", parent=None, *, width=-1, height=-1,
                        readonly=False, **kwargs):
        """Create a shared QPlainTextEdit-like multiline editor.

        The native Dear ImGui input remains the real text/selection/scroll
        owner.  This helper only standardizes its frame, padding and scrollbar
        chrome so diagnostics/log/result views no longer look like raw ImGui
        widgets.
        """
        options = dict(kwargs)
        options.setdefault("default_value", str(value))
        options.setdefault("width", int(width))
        options.setdefault("height", int(height))
        options.setdefault("multiline", True)
        options.setdefault("readonly", bool(readonly))
        options.setdefault("auto_select_all", False)
        options.setdefault("no_horizontal_scroll", False)
        if parent is not None:
            options["parent"] = parent
        item = dpg.add_input_text(**options)
        try:
            dpg.bind_item_theme(item, plain_text_edit_theme())
        except Exception:
            pass
        return item


    def spin_int(self, value=0, parent=None, *, minimum=None, maximum=None,
                 step=1, width=-1, callback=None):
        widget = self.own_widget(ImGuiSpinBox(
            value, parent=parent, after=self.view.after, backend=dpg,
            width=width, minimum=minimum, maximum=maximum,
            step=step, callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def spin_float(self, value=0.0, parent=None, *, minimum=None, maximum=None,
                   step=0.1, decimals=2, width=-1, callback=None):
        widget = self.own_widget(ImGuiDoubleSpinBox(
            value, parent=parent, after=self.view.after, backend=dpg,
            width=width, minimum=minimum, maximum=maximum,
            step=step, decimals=decimals, callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def checkbox(self, text="", *, checked=False, parent=None):
        """Create a retained native Dear ImGui checkbox with Qt-like states."""
        widget = self.own_widget(ImGuiCheckBox(
            text, checked=checked, parent=parent, after=self.view.after, backend=dpg,
        ))
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def radio_group(self, items=(), *, current=None, horizontal=False,
                    parent=None, callback=None):
        """Create a retained native Dear ImGui radio group.

        This intentionally wraps DPG's grouped radio primitive rather than
        drawing custom circles, so keyboard and pointer behavior stay native.
        """
        widget = self.own_widget(ImGuiRadioButtonGroup(
            items,
            current=current,
            horizontal=horizontal,
            parent=parent,
            after=self.view.after,
            backend=dpg,
            callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def progress_bar(self, value=0.0, *, parent=None, overlay=None):
        """Create the shared retained progress-bar surface and return its tag."""
        widget = self.own_widget(ImGuiProgressBar(
            parent=parent, after=self.view.after, backend=dpg,
        ))
        widget.setValue(value)
        if overlay is not None:
            widget.setFormat(overlay)
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def combo(self, items=(), parent=None, **kwargs):
        """Create one non-editable QComboBox-like control."""
        options = {"width": -1}
        options.update(kwargs)
        if parent is not None:
            options["parent"] = parent
        item = dpg.add_combo(list(items), **options)
        registry = bind_combo_style(item)
        if registry is not None:
            self._control_handler_registries.append(registry)
        return item

    def set_control_enabled(self, item, enabled):
        """Enable/disable a retained control as one visual/behavioral unit."""
        wrapper = self._control_wrappers.get(item)
        if wrapper is not None:
            wrapper.setEnabled(bool(enabled))
            return
        if dpg.does_item_exist(item):
            dpg.configure_item(item, enabled=bool(enabled))
            self.refresh_control_style(item)

    def refresh_control_style(self, item):
        """Refresh enabled/focus visual state after direct configure_item calls."""
        if not dpg.does_item_exist(item):
            return
        info = dpg.get_item_info(item) or {}
        item_type = str(info.get("type", ""))
        if item_type.endswith("::mvCombo"):
            refresh_combo_theme(item)
        elif item_type.endswith("::mvInputInt") or item_type.endswith("::mvInputFloat"):
            wrapper = self._control_wrappers.get(item)
            if wrapper is not None:
                try:
                    enabled = bool(dpg.get_item_configuration(item).get("enabled", True))
                    wrapper._properties["enabled"] = enabled
                    wrapper._refresh_style()
                except Exception:
                    pass
        elif item_type.endswith("::mvInputText"):
            wrapper = self._control_wrappers.get(item)
            if wrapper is not None:
                try:
                    enabled = bool(dpg.get_item_configuration(item).get("enabled", True))
                    wrapper._properties["enabled"] = enabled
                    wrapper._refresh_style()
                except Exception:
                    pass
            else:
                shell = self._line_edit_shells.get(item)
                if shell is not None:
                    try:
                        enabled = bool(dpg.get_item_configuration(item).get("enabled", True))
                    except Exception:
                        enabled = True
                    dpg.bind_item_theme(item, line_edit_editor_theme(disabled=not enabled))
                    self._refresh_line_edit_shell(item)

    def style_table(self, table):
        """Apply the shared QTableView/QHeaderView chrome to a raw DPG table.

        Editable dialog grids (Job Manager / Schedule) cannot use
        ``QtDataGridView`` because their cells host live widgets.  They still
        need the same palette, header padding, borders and scrollbar metrics
        as the retained item-view layer.  Keep that contract in one helper
        instead of allowing each dialog to invent its own ImGui table style.
        """
        try:
            from ..widgets.item_views import qt_item_view_theme
            dpg.bind_item_theme(table, qt_item_view_theme(dpg))
        except Exception:
            pass
        return table

    def message_box_body(self, heading, message, *, intent="info", detail=None, parent=None):
        """Build a compact QMessageBox-like content row from DPG primitives.

        The icon is vector geometry rather than a font symbol so Windows font
        fallback cannot turn warning/question glyphs into boxes or diamonds.
        Title-bar ownership stays with QDialog; this helper owns only the
        familiar icon + heading + message body arrangement.
        """
        parent = parent or self.content
        table = dpg.add_table(
            parent=parent, header_row=False, width=-1,
            policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=False, borders_outerH=False,
            borders_innerV=False, borders_outerV=False,
        )
        dpg.add_table_column(parent=table, width_fixed=True, init_width_or_weight=42)
        dpg.add_table_column(parent=table, width_stretch=True, init_width_or_weight=1.0)
        palette = {
            "error": (196, 43, 28, 255),
            "danger": (196, 43, 28, 255),
            "delete": (196, 43, 28, 255),
            "warning": (205, 132, 0, 255),
            "warn": (205, 132, 0, 255),
            "question": (0, 105, 180, 255),
            "info": (0, 120, 215, 255),
        }
        role = str(intent or "info").lower()
        color = palette.get(role, palette["info"])
        with dpg.table_row(parent=table):
            canvas = dpg.add_drawlist(width=36, height=36)
            cx, cy = 18, 18
            if role in ("warning", "warn"):
                dpg.draw_triangle((18, 3), (33, 31), (3, 31), color=color, fill=color, parent=canvas)
                dpg.draw_line((18, 11), (18, 22), color=(255,255,255,255), thickness=2.0, parent=canvas)
                dpg.draw_circle((18, 27), 1.6, color=(255,255,255,255), fill=(255,255,255,255), parent=canvas)
            else:
                dpg.draw_circle((cx, cy), 15, color=color, fill=color, parent=canvas)
                white = (255, 255, 255, 255)
                if role in ("error", "danger", "delete"):
                    dpg.draw_line((12, 12), (24, 24), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((24, 12), (12, 24), color=white, thickness=2.0, parent=canvas)
                elif role == "question":
                    dpg.draw_line((13, 12), (16, 9), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((16, 9), (21, 9), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((21, 9), (24, 12), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((24, 12), (24, 15), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((24, 15), (18, 20), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_line((18, 20), (18, 22), color=white, thickness=2.0, parent=canvas)
                    dpg.draw_circle((18, 27), 1.5, color=white, fill=white, parent=canvas)
                else:
                    dpg.draw_circle((18, 11), 1.6, color=white, fill=white, parent=canvas)
                    dpg.draw_line((18, 16), (18, 27), color=white, thickness=2.0, parent=canvas)
            with dpg.group() as body:
                title_item = dpg.add_text(str(heading or ""), wrap=max(260, self.width - 110))
                font = getattr(self.view, "heading_font", None)
                if font:
                    dpg.bind_item_font(title_item, font)
                dpg.add_spacer(height=2)
                dpg.add_text(str(message or ""), wrap=max(260, self.width - 110))
                if detail:
                    dpg.add_spacer(height=2)
                    self.note(detail, parent=body, wrap=max(260, self.width - 110))
        return table

    def field(self, label, value="", parent=None, **kwargs):
        return self.labeled_widget(
            label,
            lambda: self.line_edit(value, **kwargs),
            parent,
        )

    def note(self, text, parent=None, wrap=0):
        item = dpg.add_text(str(text), parent=parent or self.content, wrap=wrap)
        dpg.bind_item_theme(item, muted_text_theme())
        return item

    def status_text(self, text="", parent=None, error=False, wrap=0):
        """Create a uniform QLabel-like status/error slot.

        Empty validation errors should not reserve a blank row in a compact Qt
        form.  Ordinary informational status text remains visible even when
        empty because callers may update it continuously.
        """
        value = str(text or "")
        item = dpg.add_text(value, parent=parent or self.content, wrap=wrap)
        dpg.bind_item_theme(item, error_text_theme() if error else muted_text_theme())
        if error and not value:
            dpg.configure_item(item, show=False)
        return item

    def set_status_text(self, item, text, *, error=None):
        """Update a retained status QLabel and collapse empty error feedback."""
        if item is None or not dpg.does_item_exist(item):
            return False
        value = str(text or "")
        dpg.set_value(item, value)
        if error is not None:
            dpg.bind_item_theme(
                item, error_text_theme() if bool(error) else muted_text_theme())
        # Validation/error labels collapse when clear; informational labels stay
        # allocated unless the caller explicitly requests error semantics.
        if error is True:
            dpg.configure_item(item, show=bool(value))
        return True

    def navigation_panel(self, width=None, parent=None):
        panel = dpg.add_child_window(
            parent=parent or self.content,
            width=int(width or DialogMetrics.NAV_WIDTH),
            height=-1, border=True, no_scrollbar=True, no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(panel, navigation_theme())
        return panel

    def header(self, title, subtitle="", parent=None):
        """Compact Qt page heading used consistently by all dialog pages."""
        with dpg.group(parent=parent or self.content, horizontal_spacing=0) as header:
            heading = dpg.add_text(title)
            font = getattr(self.view, "heading_font", None)
            if font:
                dpg.bind_item_font(heading, font)
            if subtitle:
                self.note(subtitle, parent=header, wrap=max(320, self.width-72))
            # A single light separator gives Settings pages the same visual
            # hierarchy as a QWidget page without introducing a card/header
            # background that would make the dialog look like Dear ImGui.
            dpg.add_separator()
            dpg.add_spacer(height=2)
        return header

    @contextmanager
    def section(self, title, parent=None):
        """Create one reusable Dear ImGui QGroupBox-style container."""
        box = self.own_widget(ImGuiGroupBox(
            title, parent=parent or self.content, after=self.view.after, backend=dpg,
            width=-1, auto_resize_y=True,
        ))
        # QGroupBox captions use the application/body font.  Reserve the
        # larger heading font for the page title above the separator; using it
        # for every Settings section made the page look like stacked ImGui
        # cards rather than a native Qt preferences page.
        with box:
            yield box.content

    def invoke_default(self):
        if not callable(self._default) or self._default_button is None:
            return
        if not dpg.get_item_configuration(self._default_button).get("enabled", True):
            return
        # Multiline editors and result views own Enter; single-line forms use
        # QDialog's default action, with no duplicate on_enter callback.
        if any(dpg.does_item_exist(item) and dpg.is_item_focused(item)
               for item in self.enter_editors):
            return
        self._default()

    def own_dialog(self, dialog):
        self._owned_dialogs.append(dialog)
        return dialog

    def own_widget(self, widget):
        widget.setParent(self._widget_owner)
        return widget

    def _restore_embedded_owner_focus(self):
        """Return Dear ImGui navigation focus to the main client safely.

        Embedded QDialogs share the application's native viewport.  Deleting a
        focused modal window can leave ImGui's nav focus attached to an item
        that no longer exists, so keyboard input appears lost until the user
        clicks the main window.  Restore only when no newer embedded/floating
        dialog is visible; this mirrors Qt's parent activation semantics without
        stealing OS foreground focus from another application.
        """
        if getattr(self.view, "_floating_focus_suppressed", False):
            return
        try:
            for dialog in tuple(_DIALOGS):
                if dialog is self or not dialog.winfo_exists():
                    continue
                if dpg.does_item_exist(dialog.tag) and dpg.is_item_shown(dialog.tag):
                    return
            for dialog in tuple(getattr(self.view, "_floating_dialogs", ())):
                if (not getattr(dialog, "_closed", False)
                        and getattr(dialog, "_visible", False)):
                    return
            if dpg.does_item_exist("winux_primary"):
                dpg.focus_item("winux_primary")
        except Exception:
            pass

    def delete_owned_item(self, item):
        """Release wrappers before replacing a native row/container subtree."""
        descendants = {item}
        pending = [item]
        while pending:
            parent = pending.pop()
            for children in (dpg.get_item_children(parent) or {}).values():
                for child in children:
                    if child not in descendants:
                        descendants.add(child)
                        pending.append(child)
        for widget in tuple(self._widget_owner._children):
            if getattr(widget, "tag", None) in descendants:
                widget.delete()
        if dpg.does_item_exist(item):
            dpg.delete_item(item)

    def destroy(self):
        if threading.get_ident() != self._ui_thread:
            self.view.after(0, self.destroy)
            return
        if self._destroy_scheduled:
            return
        self._latest_updates.close()
        self._widget_owner.delete()
        for child in self._owned_dialogs:
            child.destroy()
        self._owned_dialogs.clear()
        if self in _DIALOGS:
            _DIALOGS.remove(self)
        registry = self._resize_registry
        control_registries = tuple(self._control_handler_registries)
        self._control_handler_registries.clear()
        self._line_edit_shells.clear()
        self._control_wrappers.clear()
        super().destroy()
        # Run after the modal item has been hidden/deleted on the UI queue.
        # A later dialog show will be detected and blocks this restoration.
        self.view.after(0, self._restore_embedded_owner_focus)
        if registry or control_registries:
            def cleanup():
                if registry and dpg.does_item_exist(registry):
                    dpg.delete_item(registry)
                for item in control_registries:
                    if item and dpg.does_item_exist(item):
                        dpg.delete_item(item)
            self.view.after(0, cleanup)


class QtTable(QtDataGridView):
    # The reusable QtDataGridView owns the actual DPG table contract, including
    # freeze_rows=1, alternating rows, QHeaderView-like chrome and row focus.
    """Backward-compatible QTableView wrapper for existing dialog forms.

    New code should use :class:`WinUx.widgets.QtDataGridView` directly.  This
    adapter keeps the historical ``rows``/``selected``/``items`` surface while
    moving rendering and selection behavior into the reusable item-view layer.
    """

    def __init__(self, parent, headings, height=-1, multiple=False, on_activate=None):
        super().__init__(
            parent, headings, height=height, width=-1, multiple=multiple,
            sortable=False, resizable=True, reorderable=False,
            alternating_rows=True, grid_lines=True, on_activate=on_activate,
        )
        self.owner = None
        ancestor = parent
        while ancestor:
            self.owner = next((dialog for dialog in _DIALOGS if dialog.tag == ancestor), None)
            if self.owner is not None:
                if self.owner.active_table is None:
                    self.owner.active_table = self
                # Mirror QObject ownership: table resources/signals are released
                # before the dialog's native DPG subtree is destroyed.
                self.owner.own_widget(self)
                break
            ancestor = dpg.get_item_parent(ancestor)

    def _row_clicked(self, sender, value, key):
        if self.owner is not None:
            self.owner.active_table = self
        super()._row_clicked(sender, value, key)

