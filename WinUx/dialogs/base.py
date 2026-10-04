from __future__ import annotations

import dearpygui.dearpygui as dpg

from ..components.explorer_list_view import (
    register_modal_window,
    unregister_modal_window,
)
from .theme import (
    DialogMetrics,
    dialog_theme,
    primary_button_theme,
    secondary_button_theme,
)


_ESCAPE_TARGETS = []
_ESCAPE_HANDLER_REGISTRY = None


def _remove_escape_target(tag):
    global _ESCAPE_TARGETS
    _ESCAPE_TARGETS = [
        entry for entry in _ESCAPE_TARGETS if entry[0] != tag
    ]


def _dispatch_escape(sender=None, app_data=None, user_data=None):
    """Close only the top-most visible dialog for one Escape press."""
    stale = []
    for tag, callback in reversed(tuple(_ESCAPE_TARGETS)):
        try:
            if not dpg.does_item_exist(tag):
                stale.append(tag)
                continue
            if not dpg.is_item_shown(tag):
                continue
        except Exception:
            stale.append(tag)
            continue

        try:
            callback()
        except Exception:
            pass
        break

    for tag in stale:
        _remove_escape_target(tag)


def _ensure_escape_handler():
    global _ESCAPE_HANDLER_REGISTRY
    if (
        _ESCAPE_HANDLER_REGISTRY is not None
        and dpg.does_item_exist(_ESCAPE_HANDLER_REGISTRY)
    ):
        return

    try:
        with dpg.handler_registry() as registry:
            dpg.add_key_press_handler(
                key=dpg.mvKey_Escape,
                callback=_dispatch_escape,
            )
        _ESCAPE_HANDLER_REGISTRY = registry
    except Exception:
        _ESCAPE_HANDLER_REGISTRY = None


def register_escape_target(tag, callback):
    """Register or raise a dialog in the Escape-close stack."""
    if tag is None or not callable(callback):
        return
    _ensure_escape_handler()
    _remove_escape_target(tag)
    _ESCAPE_TARGETS.append((tag, callback))


def unregister_escape_target(tag):
    _remove_escape_target(tag)


class DialogBase:
    NATIVE_WINDOW = False

    def __init__(self, tag, width=None, height=None):
        self.tag = tag
        self.width = width
        self.height = height
        self._closed = False
        self._destroy_scheduled = False
        self._resize_registry = None
        if dpg.does_item_exist(tag):
            # Every DialogBase window owns application input while it is
            # visible. Dear PyGui's normal modal flag blocks regular widgets,
            # while the explicit registry also blocks ExplorerListView's global
            # mouse/keyboard handlers so clicks can never pass through to rows
            # behind the dialog.
            try:
                dpg.configure_item(tag, modal=not self.NATIVE_WINDOW)
            except Exception:
                pass
            register_modal_window(tag)
            register_escape_target(tag, self._close_from_escape)
            self._fit_content()
            dpg.bind_item_theme(tag, dialog_theme())
            self._bind_resize_handler()
            self.center()
            self._apply_layout()

    def _fit_content(self):
        """Keep dialog contents inside one fitted, scrollable component."""
        children = list(dpg.get_item_children(self.tag, 1) or [])
        if not children:
            return
        content = dpg.add_child_window(
            parent=self.tag, width=-1, height=-1, border=False,
            no_scrollbar=False, no_scroll_with_mouse=False,
            horizontal_scrollbar=False,
        )
        for child in children:
            if child != content and dpg.does_item_exist(child):
                dpg.move_item(child, parent=content)
        self.content = content

    def _bind_resize_handler(self):
        """Reflow dialog-owned widgets whenever the native window is resized."""
        try:
            with dpg.item_handler_registry() as registry:
                dpg.add_item_resize_handler(callback=self._on_native_resize)
            dpg.bind_item_handler_registry(self.tag, registry)
            self._resize_registry = registry
        except Exception:
            self._resize_registry = None

    def _on_native_resize(self, sender=None, app_data=None, user_data=None):
        self._apply_layout()

    def _apply_layout(self):
        if not dpg.does_item_exist(self.tag):
            return
        try:
            if hasattr(self, "content") and dpg.does_item_exist(self.content):
                dpg.configure_item(self.content, width=-1, height=-1)
        except Exception:
            pass
        callback = getattr(self, "layout_dialog", None)
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    def center(self):
        try:
            vw = dpg.get_viewport_client_width()
            vh = dpg.get_viewport_client_height()
            width = int(self.width or dpg.get_item_width(self.tag))
            height = int(self.height or dpg.get_item_height(self.tag))
            dpg.set_item_pos(self.tag, (max(0, (vw-width)//2), max(0, (vh-height)//2)))
        except Exception:
            pass

    def winfo_exists(self):
        return (not self._closed) and dpg.does_item_exist(self.tag)

    def lift(self):
        if self.winfo_exists():
            register_escape_target(self.tag, self._close_from_escape)
            dpg.show_item(self.tag)
            dpg.focus_item(self.tag)

    def _close_from_escape(self):
        """Apply the dialog's normal cancel semantics, then close it."""
        if self._destroy_scheduled or not self.winfo_exists():
            return

        # Result dialogs must report a cancelled result instead of merely
        # disappearing. Transfer progress dialogs must signal cancellation.
        finish = getattr(self, "finish", None)
        if callable(finish):
            finish(None)
            return

        cancel = getattr(self, "cancel", None)
        if callable(cancel):
            cancel()
            # Some cancel methods (for example ProgressDialog.cancel) only
            # signal a worker. Escape is explicitly a close action, so hide and
            # remove the modal immediately after the cancellation request.
            if self.winfo_exists() and not self._destroy_scheduled:
                self.destroy()
            return

        self.destroy()

    def _finalize_visual_destroy(self, *_args, **_kwargs):
        """Delete the DPG item after its native viewport is no longer visible.

        A process-isolated dialog uses the DPG window as the *only* content of a
        native viewport.  Hiding/deleting that item before ``SW_HIDE`` leaves a
        live swap chain with no content, so DPG clears it to black for one frame.
        The floating runtime therefore sets ``_defer_visual_destroy`` and calls
        this method only after the HWND has been hidden.
        """
        tag = self.tag
        try:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        except Exception:
            pass
        finally:
            unregister_modal_window(tag)

    def destroy(self):
        """Close a dialog exactly once without exposing an empty viewport.

        Embedded dialogs keep the legacy behaviour: hide immediately and delete
        on the UI queue.  Dedicated floating viewports preserve their last fully
        rendered frame until the native HWND is hidden, then delete the DPG item.
        This mirrors Qt/WinForms destruction ordering and prevents the black
        clear-frame that used to appear just before a dialog disappeared.
        """
        # ``_closed`` is also used by a few subclasses as a logical result
        # guard.  Do not use it to decide whether the native DPG window still
        # needs cleanup: older dialog code may set ``_closed`` immediately
        # before calling destroy().
        if self._destroy_scheduled:
            return
        self._destroy_scheduled = True
        self._closed = True
        tag = self.tag
        if not dpg.does_item_exist(tag):
            unregister_escape_target(tag)
            unregister_modal_window(tag)
            return

        unregister_escape_target(tag)

        # A dedicated native viewport must keep its final pixels intact until
        # SW_HIDE.  The runtime owns the final item deletion after native hide.
        if bool(getattr(self, "_defer_visual_destroy", False)):
            return

        try:
            dpg.configure_item(tag, show=False)
        except Exception:
            pass

        # Use the application's own UI queue instead of set_frame_callback.
        # Dear PyGui supports only one callback per target frame, so resize/layout
        # callbacks could overwrite modal cleanup and leave the modal stack stuck.
        view = getattr(self, "view", None)
        if view is not None and hasattr(view, "after"):
            view.after(0, self._finalize_visual_destroy)
        else:
            self._finalize_visual_destroy()

    def grab_release(self):
        pass

    @staticmethod
    def add_title(text):
        # The native dialog title bar already identifies the window. Keeping a
        # second blue heading wastes vertical space and caused short dialogs to
        # overflow at scaled DPI settings.
        return None

    @staticmethod
    def add_footer(ok_text="OK", ok_callback=None, cancel_text="Cancel", cancel_callback=None,
                   spacer_width=0):
        """Create a responsive dialog footer.

        A single action is centered at the bottom of the dialog. Two or more
        actions are grouped at the bottom-right. ``spacer_width`` is retained
        for API compatibility but deliberately ignored so resizing never relies
        on fixed pixel spacers.
        """
        actions = []
        if ok_text:
            actions.append((ok_text, ok_callback, False))
        if cancel_text:
            actions.append((cancel_text, cancel_callback, True))

        if not actions:
            return None, None

        ok = None
        cancel = None
        if len(actions) == 1:
            # Stretch / fixed / stretch keeps the only button centered at every
            # dialog width and DPI scale.
            with dpg.table(
                header_row=False, width=-1, policy=dpg.mvTable_SizingStretchProp,
                borders_innerH=False, borders_outerH=False,
                borders_innerV=False, borders_outerV=False,
                pad_outerX=False,
            ):
                dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
                dpg.add_table_column(width_fixed=True,
                                     init_width_or_weight=DialogMetrics.BUTTON_WIDTH)
                dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
                with dpg.table_row():
                    dpg.add_spacer()
                    text, callback, secondary = actions[0]
                    button = dpg.add_button(
                        label=text, width=DialogMetrics.BUTTON_WIDTH,
                        height=DialogMetrics.BUTTON_HEIGHT,
                        callback=callback,
                    )
                    dpg.bind_item_theme(
                        button,
                        secondary_button_theme() if secondary else primary_button_theme(),
                    )
                    dpg.add_spacer()
                    if ok_text:
                        ok = button
                    else:
                        cancel = button
        else:
            group_width = (len(actions) * DialogMetrics.BUTTON_WIDTH
                           + max(0, len(actions) - 1) * 8)
            with dpg.table(
                header_row=False, width=-1, policy=dpg.mvTable_SizingStretchProp,
                borders_innerH=False, borders_outerH=False,
                borders_innerV=False, borders_outerV=False,
                pad_outerX=False,
            ):
                dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
                dpg.add_table_column(width_fixed=True, init_width_or_weight=group_width)
                with dpg.table_row():
                    dpg.add_spacer()
                    with dpg.group(horizontal=True, horizontal_spacing=8):
                        for index, (text, callback, secondary) in enumerate(actions):
                            button = dpg.add_button(
                                label=text, width=DialogMetrics.BUTTON_WIDTH,
                                height=DialogMetrics.BUTTON_HEIGHT,
                                callback=callback,
                            )
                            dpg.bind_item_theme(
                                button,
                                secondary_button_theme() if secondary else primary_button_theme(),
                            )
                            if index == 0:
                                ok = button
                            elif index == 1:
                                cancel = button
        return ok, cancel

    @staticmethod
    def add_labeled_row(label, builder):
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp,
                       borders_innerH=False, borders_outerH=False,
                       borders_innerV=False, borders_outerV=False):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=DialogMetrics.LABEL_WIDTH)
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_text(label)
                return builder()
