"""Qt-like dialog lifecycle and layouts rendered exclusively by Dear PyGui."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from ..backends import dpg, get_backend

from .base import DialogBase, register_escape_target, unregister_escape_target
from .theme import (
    DialogMetrics, DialogPalette, dialog_theme, primary_button_theme,
    secondary_button_theme, danger_button_theme, surface_theme, footer_theme, body_theme,
    muted_text_theme, error_text_theme, navigation_theme,
    bind_combo_style, refresh_combo_theme,
    line_edit_shell_theme, line_edit_editor_theme, plain_text_edit_theme,
)
from ..modal import register_modal_window, unregister_modal_window
from .placement import centered_over
from ..input_gate import (
    guard_pointer_surface_release, register_pointer_protected_item,
    unregister_pointer_protected_item, release_pointer_input,
    _mouse_button_down,
)
from ..dispatch import LatestCallQueue
from ..gui.style import METRICS, form_row_theme, form_label_cell_theme, aligned_cell_theme
from ..core import Qt, QObject, QSize, QEvent, QKeyEvent, QCloseEvent, QMouseEvent
from ..widgets.widget import QWidget
from ..widgets.buttons import QPushButton, QLabel
from ..widgets.editors import ImGuiLineEdit, QPlainTextEdit, ImGuiSpinBox, ImGuiDoubleSpinBox
from ..widgets.containers import ImGuiGroupBox, ImGuiProgressBar
from ..widgets.combo_box import QComboBox
from .combo_callbacks import adapt_combo_callback
from ..widgets.selection import ImGuiCheckBox, ImGuiRadioButtonGroup
from ..layouts import QGridLayout
from ..modelview import QtDataGridView


_DIALOGS = []
_KEYS = None
_DIALOG_REJECT_CAPTIONS = {"cancel", "close", "dismiss", "no"}


def _editor_is_active():
    # Bundled DPG 2.3 exposes per-item active state, not is_any_item_active.
    any_active = getattr(dpg, "is_any_item_active", None)
    if callable(any_active):
        return bool(any_active())
    focused = dpg.get_focused_item()
    if not focused or not dpg.does_item_exist(focused):
        return False
    # Windows/containers can own focus without exposing an ``active`` state.
    # DPG's is_item_active indexes that optional field and raises KeyError.
    return bool(dpg.get_item_state(focused).get("active", False))


def _dispatch_key(sender, key):
    ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
    shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
    for dialog in reversed(tuple(_DIALOGS)):
        if not dialog.winfo_exists() or not dpg.is_item_shown(dialog.tag):
            continue
        if not dialog.modal and not dialog.isActiveWindow():
            continue
        shortcut = dialog.shortcuts.get((key, ctrl))
        if shortcut:
            # Explicit widget/application shortcuts keep priority over generic
            # QDialog focus traversal (e.g. console widgets own Tab).
            shortcut()
            return
        if key == getattr(dpg, "mvKey_Tab", None) and not ctrl:
            dialog.focusNextPrevChild(next=not shift)
            return
        table = dialog.active_table
        if table is not None and not _editor_is_active():
            table.navigate(key, ctrl=ctrl, shift=shift)
        return


def _dispatch_return(*_args):
    for dialog in reversed(tuple(_DIALOGS)):
        if dialog.winfo_exists() and dpg.is_item_shown(dialog.tag):
            if dialog.modal or dialog.isActiveWindow():
                dialog.invoke_default()
                return


def _install_keys():
    """Prefer QApplication's single keyboard bridge; retain standalone fallback."""
    global _KEYS
    try:
        from ..core.application import QApplication
        application = QApplication.instance()
        if application is not None and application.installInputBackend(get_backend()):
            return True
    except Exception:
        pass
    if _KEYS is None or not dpg.does_item_exist(_KEYS):
        with dpg.handler_registry() as _KEYS:
            dpg.add_key_press_handler(key=dpg.mvKey_Return, callback=_dispatch_return)
            numpad_enter = getattr(dpg, "mvKey_NumPadEnter", None)
            if numpad_enter is not None:
                dpg.add_key_press_handler(key=numpad_enter, callback=_dispatch_return)
            navigation_keys = [
                dpg.mvKey_Up, dpg.mvKey_Down, dpg.mvKey_Home, dpg.mvKey_End,
                dpg.mvKey_Prior, dpg.mvKey_Next, dpg.mvKey_A, dpg.mvKey_Spacebar,
                dpg.mvKey_F2, dpg.mvKey_Delete, dpg.mvKey_C,
            ]
            tab_key = getattr(dpg, "mvKey_Tab", None)
            if tab_key is not None:
                navigation_keys.append(tab_key)
            for key in navigation_keys:
                dpg.add_key_press_handler(key=key, callback=_dispatch_key)
    return False


class QtDialog(DialogBase, QObject):
    # QDialog-like native caption defaults. Owned/modal dialogs do not get an
    # independent taskbar button, so minimizing them can make them unreachable.
    ALLOW_MINIMIZE = False
    ALLOW_MAXIMIZE = None

    """QDialog contract, pinned button box and scrollable body in the UI viewport.

    ``post`` marshals background results through the application's UI queue;
    its lifetime check also discards results arriving after close.
    """

    # Opt in only after verifying widget, popup and background-work cleanup.
    REUSABLE_HOST = False

    def __init__(self, view, title, width=560, height=360, modal=True, footer=True, parent=None,
                 native=None, compact=False, resizable=True):
        from ..backends.native_windows import NativeWindowBackend
        native_backend = NativeWindowBackend()
        use_native = native_backend.isEnabled() if native is None else bool(native)
        if use_native:
            native_backend.require()
            if not native_backend.isEnabled():
                raise RuntimeError("Enable native windows on QGuiRuntime before creating native dialogs")
        self._native_window_backend = native_backend if use_native else None
        # Native owner focus is a two-phase transaction.  The immediate
        # hand-off happens before hide/destroy, while a guarded verification
        # runs only after the renderer has actually removed the secondary HWND.
        self._native_owner_close_lease = None
        self._native_owner_repair_generation = 0
        owner_parent = parent if isinstance(parent, QObject) else None
        self._requested_parent = parent
        # Defer external parenting until the dialog state is initialized so a
        # ParentChange event/filter can safely inspect this object.
        QObject.__init__(self, after=view.after)
        self.view = view
        self.modal = bool(modal)
        self._resizable = bool(resizable)
        self.tag = dpg.generate_uuid()
        self.width, self.height = width, height
        self._minimum_dialog_height = (
            DialogMetrics.COMPACT_DIALOG_MIN_HEIGHT if compact
            else DialogMetrics.MIN_DIALOG_HEIGHT
        )
        self._window_title = str(title or "")
        self._attributes = set()
        self._layout_manager = None
        # Qt constructs QWidget/QDialog trees while they are not yet exposed to
        # the window system.  In-process host dialogs historically created a
        # visible DPG window here, then spent the remainder of the subclass
        # constructor appending controls to that live surface.  Besides causing
        # incomplete first-frame layout/focus work, that makes every geometry
        # invalidation wake the application queue during construction.
        #
        # Keep process-host compatibility unchanged, but use a hidden
        # construction transaction whenever the dialog belongs to the main
        # QApplication.  The subclass can build synchronously; the first show
        # occurs only after the constructor returns (or immediately when its
        # owner explicitly calls show()).
        self._construction_deferred = False
        self._construction_finished = True
        self._construction_layout_dirty = False
        # One hidden-construction native commit per retained QWidget. This is
        # deliberately dialog-owned so lightweight controls remain backend-agnostic
        # outside a QApplication/QDialog construction transaction.
        self._construction_widget_configs = {}
        self._retained_layout_dirty = False
        self._layout_native_state = {}
        self._visible_state = True
        self._initial_visibility_requested = True
        self._initial_show_scheduled = False
        self._closed = False
        self._destroy_scheduled = False
        self._logical_cleanup_done = False
        self._resize_registry = None
        self._default = None
        self._default_button = None
        self._reject = None
        self._reject_button = None
        self._focus_order = []
        self._initial_focus_item = None
        try:
            self._focus_restore_item = dpg.get_focused_item() or None
        except Exception:
            self._focus_restore_item = None
        # QWidget/QDialog activation state is separate from visibility.  It is
        # used to decide whether a close is allowed to return focus: closing a
        # background/modeless window must never steal keyboard focus from the
        # currently active surface.
        self._activation_owned = False
        self._restore_focus_on_hide = False
        self._ui_thread = threading.get_ident()
        self._latest_updates = LatestCallQueue(view.after)
        self._widget_owner = QObject(parent=self, after=view.after)
        # QObject proxies let wrappers keep a real Qt ownership chain while still
        # targeting an arbitrary native DearPyGui container tag.  This means a
        # control can participate in hidden-construction batching from the moment
        # its constructor runs, rather than only after own_widget() reparents it.
        self._native_parent_owners = {}
        # Background work belongs to the dialog lifetime. Keeping explicit
        # handles lets close() request cancellation immediately and prevents
        # stale completion callbacks from retaining a closed form.
        self._async_futures = set()
        self._owned_dialogs = []
        self._control_handler_registries = []
        self._line_edit_shells = {}  # legacy compatibility; new fields are direct ImGuiLineEdit
        self._control_wrappers = {}
        self._button_pointer_target = None
        self._button_activation_serial = 0
        self._initial_pointer_activity = False
        self._pointer_interaction_serial = 0
        self.enter_editors = set()
        self.shortcuts = {}
        self.active_table = None
        self.has_footer = bool(footer)
        self._construction_deferred = self._should_defer_initial_show()
        self._construction_finished = not self._construction_deferred
        self._construction_layout_dirty = self._construction_deferred
        self._visible_state = not self._construction_deferred
        fixed_size = (int(width), int(height)) if not self._resizable else None
        with dpg.window(tag=self.tag, label=title, width=width, height=height,
                        show=not self._construction_deferred,
                        modal=self.modal and not use_native, no_collapse=True, no_scrollbar=True,
                        no_scroll_with_mouse=True, no_resize=not self._resizable,
                        min_size=(fixed_size if fixed_size is not None else
                                  (DialogMetrics.MIN_DIALOG_WIDTH, self._minimum_dialog_height)),
                        max_size=fixed_size if fixed_size is not None else (10000, 10000),
                        on_close=lambda: self.reject()):
            self.content = dpg.add_child_window(width=-1, height=-(DialogMetrics.FOOTER_HEIGHT+1) if footer else -1,
                                                border=False, no_scrollbar=False, no_scroll_with_mouse=False,
                                                always_use_window_padding=True)
            # Wrap the native body immediately so subclasses can stay on the
            # QWidget API instead of configuring this implementation tag.
            self._content_widget = QWidget(
                self.content, parent=self._widget_owner, after=view.after, backend=get_backend())
            self.footer_shell = self.footer = None
            if footer:
                dpg.add_separator()
                with dpg.child_window(width=-1, height=DialogMetrics.FOOTER_HEIGHT, border=False,
                                      no_scrollbar=True, always_use_window_padding=True) as self.footer_shell:
                    self.footer = dpg.add_group()
        dpg.bind_item_theme(self.tag, dialog_theme())
        self._content_widget.setTheme(body_theme())
        if footer:
            dpg.bind_item_theme(self.footer_shell, footer_theme())
        if use_native:
            native_backend.configure(
                self.tag, owner=self._modal_native_parent() if self.modal else None,
                modal=self.modal, owner_hwnd=self._native_main_owner_hwnd())
        self._bind_resize_handler()
        if owner_parent is not None:
            self.setParent(owner_parent)
        _DIALOGS.append(self)
        self._application_keyboard = _install_keys()
        if self._construction_deferred:
            # after(0) is a queued UI turn in the host application.  It cannot run until the
            # current constructor/callback returns, so subclasses get a hidden
            # transaction without needing a begin/end-construction call.
            self._initial_show_scheduled = True
            self.view.after(0, self._finish_initial_construction)
        else:
            self.show()
            # Standalone/native hosts center the OS viewport after its final size is
            # known. Avoid an eager DPG-window move here: it can trigger a redundant
            # resize/layout pass during cold dialog construction and adds measurable
            # startup work for large tool surfaces such as Plot Digitizer.
            if not bool(getattr(view, "is_standalone_ui_host", False)):
                self.center()
                self._schedule_native_modal_center()

    def _modal_owner_candidate(self):
        """Prefer an explicit QWidget owner, then the launching active dialog.

        WinUx registers dialogs under a shared QObject lifetime owner, which
        is deliberately *not* a visual parent.  Do not confuse that QObject
        with the application window, nor use OS foreground-window heuristics.
        """
        requested = getattr(self, "_requested_parent", None)
        if requested is not None:
            return requested
        ancestor = getattr(self, "parent", None)
        while ancestor is not None:
            if getattr(ancestor, "tag", None) is not None and ancestor is not self:
                return ancestor
            ancestor = getattr(ancestor, "parent", None)
        try:
            from ..core.application import QApplication
            app = QApplication.instance()
            if app is not None:
                for candidate in (app.activeModalWidget(), app.activeWindow()):
                    if (candidate is not None and candidate is not self
                            and not getattr(candidate, "_closed", False)
                            and getattr(candidate, "isVisible", lambda: True)()):
                        return candidate
        except Exception:
            pass
        return getattr(self.view, "primary_window_tag", None)

    def _modal_native_parent(self):
        owner = self._modal_owner_candidate()
        return owner if getattr(owner, "_native_window_backend", None) is not None else None

    def _native_main_owner_hwnd(self):
        """Return the primary WinUx HWND without using desktop focus heuristics."""
        resolver = getattr(self.view, "_find_main_viewport_hwnd", None)
        if not callable(resolver):
            return 0
        try:
            return int(resolver() or 0)
        except Exception:
            return 0

    def _synchronize_native_owner_once(self, remaining=3):
        """Attach the native viewport once its HWND exists, then stop touching it.

        Re-applying GWLP_HWNDPARENT every render resets Windows non-client hot
        tracking on some systems, which is visible as a continuously flashing
        Close button.  The backend compares the current owner before writing,
        so retries are safe while ImGui is still creating the platform HWND.
        """
        backend = self._native_window_backend
        if backend is None or not self.winfo_exists() or not self.isVisible():
            return
        try:
            if backend.synchronizeOwner(self.tag):
                return
        except Exception:
            return
        if remaining > 0:
            schedule = getattr(self.view, "after_render", None)
            if callable(schedule):
                schedule(self._synchronize_native_owner_once, remaining - 1)


    def _prepare_native_first_click_once(self, remaining=2):
        """Install Win32 first-click preservation plus one-shot button recovery."""
        backend = self._native_window_backend
        if backend is None or not self.winfo_exists() or not self.isVisible():
            return False
        preserve = getattr(backend, "preserveFirstClientClick", None)
        if not callable(preserve):
            return True
        recovery = getattr(self, "_queue_native_first_button_recovery", None)
        try:
            ready = preserve(self.tag, recovery) if callable(recovery) else preserve(self.tag)
        except TypeError:
            # Compatibility with older/custom backends that only implement the
            # original single-argument preservation contract.
            try:
                ready = preserve(self.tag)
            except Exception:
                return False
        except Exception:
            return False
        if ready is None and remaining > 0:
            schedule = getattr(self.view, "after_render", None)
            if callable(schedule):
                schedule(self._prepare_native_first_click_once, remaining - 1)
        return ready

    def _queue_native_first_button_recovery(self, screen_point):
        """Recover a lost first native click without duplicating normal delivery.

        The HWND hook observes the first client mouse-up after a visibility
        lease. Dear PyGui callbacks are drained before ``view.after`` callbacks,
        so a normally delivered QPushButton click increments the activation
        serial first and this fallback becomes a no-op.
        """
        baseline = int(getattr(self, "_button_activation_serial", 0))
        schedule = getattr(self.view, "after", None)
        if callable(schedule):
            schedule(0, self._recover_native_first_button_click, tuple(screen_point), baseline)

    def _recover_native_first_button_click(self, screen_point, baseline_serial):
        if (not self.winfo_exists() or not self.isVisible()
                or int(getattr(self, "_button_activation_serial", 0)) != int(baseline_serial)):
            return False
        for button in reversed(tuple(self._control_wrappers.values())):
            if (isinstance(button, QPushButton)
                    and self._button_contains_global_point(button, screen_point)):
                self._initial_pointer_activity = True
                return bool(button.click())
        return False

    def _activate_native_modal_once(self, remaining=2):
        """Make the first visible native modal immediately click-ready.

        ``dpg.focus_item`` focuses ImGui navigation, not necessarily the Win32
        secondary viewport HWND.  When USER32 still considers the owner the
        foreground window, the first mouse press on the dialog can otherwise
        become an activation-only click.
        """
        if (not self.modal or self._native_window_backend is None
                or not self.winfo_exists() or not self.isVisible()):
            return False
        try:
            self._native_window_backend.synchronizeOwner(self.tag)
            preserve = getattr(self._native_window_backend, "preserveFirstClientClick", None)
            if callable(preserve):
                recovery = getattr(self, "_queue_native_first_button_recovery", None)
                try:
                    click_ready = preserve(self.tag, recovery) if callable(recovery) else preserve(self.tag)
                except TypeError:
                    click_ready = preserve(self.tag)
            else:
                click_ready = True
            activated = self._native_window_backend.activateOwnedWindow(self.tag)
        except Exception:
            return False
        if (click_ready is None or activated is None) and remaining > 0:
            schedule = getattr(self.view, "after_render", None)
            if callable(schedule):
                schedule(self._activate_native_modal_once, remaining - 1)
        if click_ready is False:
            return False
        return activated

    def _apply_native_resize_policy_once(self, remaining=3):
        """Apply QDialog's resize policy to the actual Win32 viewport frame.

        ``ImGuiWindowFlags_NoResize`` prevents client-area resizing, but a
        DearUIQt native dialog also owns a decorated GLFW/Win32 viewport.  Its
        non-client frame must drop ``WS_THICKFRAME``/``WS_MAXIMIZEBOX`` as well
        or Windows will still show resize cursors and allow edge/title-bar
        resizing even though the retained dialog itself is fixed.
        """
        backend = self._native_window_backend
        if backend is None or not self.winfo_exists() or not self.isVisible():
            return
        try:
            resize_applied = backend.setResizable(self.tag, self._resizable)
            allow_minimize = bool(getattr(self, "ALLOW_MINIMIZE", False))
            allow_maximize_setting = getattr(self, "ALLOW_MAXIMIZE", None)
            allow_maximize = (
                self._resizable if allow_maximize_setting is None
                else bool(allow_maximize_setting) and self._resizable
            )
            caption_applied = backend.setCaptionButtons(
                self.tag, allow_minimize=allow_minimize,
                allow_maximize=allow_maximize)
            if resize_applied and caption_applied:
                # The frame metrics may have changed after removing caption
                # controls/resize borders. Recenter the decorated HWND once.
                if self.modal:
                    backend.centerOverOwner(self.tag)
                return
        except Exception:
            return
        if remaining > 0:
            schedule = getattr(self.view, "after_render", None)
            if callable(schedule):
                schedule(self._apply_native_resize_policy_once, remaining - 1)

    def _modal_parent_tag(self):
        """Resolve the owner's live renderer tag, with main-window fallback."""
        owner = self._modal_owner_candidate()
        options = (owner, getattr(self.view, "primary_window_tag", None))
        for candidate in options:
            tag = getattr(candidate, "tag", candidate)
            if tag is None or tag == self.tag or not isinstance(tag, (int, str)):
                continue
            try:
                if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                    return tag
            except Exception:
                continue
        return None

    def center(self):
        """Center a modal on its owner (not on the entire desktop/viewport).

        Native windows must receive their final client origin before their
        first render; centering a visible HWND afterwards causes a flash/jump.
        """
        if not self.modal or bool(getattr(self.view, "is_standalone_ui_host", False)):
            return super().center()
        self._native_center_prepared = False
        if self._native_window_backend is not None:
            owner = self._modal_native_parent()
            owner_hwnd = self._native_main_owner_hwnd() if owner is None else 0
            position = self._native_window_backend.centerBeforeShow(
                self.tag, width=self.width, height=self.height,
                owner=owner, owner_hwnd=owner_hwnd)
            if position is not None:
                self._native_center_prepared = True
                return position
        parent_tag = self._modal_parent_tag()
        if parent_tag is None:
            return super().center()
        try:
            x, y = dpg.get_item_rect_min(parent_tag)
            width, height = dpg.get_item_rect_size(parent_tag)
            if width <= 0 or height <= 0:
                return super().center()
            own_width = int(self.width or dpg.get_item_width(self.tag))
            own_height = int(self.height or dpg.get_item_height(self.tag))
            bounds = None
            if self._native_window_backend is None:
                bounds = (0, 0, dpg.get_viewport_client_width(),
                          dpg.get_viewport_client_height())
            pos = centered_over((x, y, width, height),
                                (own_width, own_height), bounds)
            dpg.set_item_pos(self.tag, pos)
            return pos
        except Exception:
            return super().center()

    def _schedule_native_modal_center(self):
        """Align the actual decorated HWND after its viewport is rendered."""
        if not self.modal or self._native_window_backend is None:
            return
        if getattr(self, "_native_center_prepared", False):
            return
        schedule = getattr(self.view, "after_render", None)
        if callable(schedule):
            schedule(self._center_native_modal_once, 2)

    def _center_native_modal_once(self, remaining=0):
        if getattr(self, "_native_center_prepared", False):
            return
        if not self.winfo_exists() or not self.isVisible():
            return
        try:
            self._native_window_backend.synchronizeOwner(self.tag)
            if self._native_window_backend.centerOverOwner(self.tag):
                return
        except Exception:
            return
        if remaining > 0:
            schedule = getattr(self.view, "after_render", None)
            if callable(schedule):
                schedule(self._center_native_modal_once, remaining - 1)

    def _should_defer_initial_show(self):
        """Use hidden construction only for the main QApplication context.

        Floating/native child runtimes intentionally retain their established
        startup contract.  Scoping this optimization to the QApplication owner
        gives lightweight in-process dialogs Qt-like construction semantics
        without changing process-host handshakes.
        """
        if bool(getattr(self.view, "is_standalone_ui_host", False)):
            return False
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            return bool(
                application is not None
                and getattr(self.view, "_qapplication", None) is application
                and application.threadId() == self.threadId()
            )
        except Exception:
            return False

    def isConstructing(self):
        return bool(self._construction_deferred and not self._construction_finished)

    def _queue_construction_widget_config(self, widget, values):
        if not self.isConstructing() or getattr(widget, "_deleted", False):
            return False
        pending = self._construction_widget_configs.setdefault(widget, {})
        pending.update(values)
        return True

    def _flush_construction_widget_configs(self):
        pending = self._construction_widget_configs
        self._construction_widget_configs = {}
        flushed = 0
        for widget, values in tuple(pending.items()):
            if getattr(widget, "_deleted", False) or not values:
                continue
            try:
                if widget.backend.does_item_exist(widget.tag):
                    commit = getattr(widget, "_commit_native_config", None)
                    if callable(commit):
                        if commit(values):
                            flushed += 1
                    else:
                        widget.backend.configure_item(widget.tag, **values)
                        widget._pending_native_config.clear()
                        flushed += 1
            except Exception:
                # A form may dispose/reparent a provisional control before first
                # show.  Construction commit is best-effort and must never keep
                # the top-level hidden because one provisional item disappeared.
                continue
        return flushed

    def _finish_initial_construction(self):
        """Polish/layout the complete tree once, then expose the top-level.

        The method is idempotent because explicit owner ``show()`` calls may
        finish construction before the queued fallback callback is drained.
        """
        if self._construction_finished or self._closed or self._deleted:
            return False
        self._construction_finished = True
        self._initial_show_scheduled = False
        # Commit each retained QWidget once before polish/layout. Geometry/style
        # setters issued throughout the subclass constructor therefore cost one
        # configure_item() crossing per touched widget rather than one per setter.
        self._flush_construction_widget_configs()
        # Polish the complete tree before activating its layout, matching Qt's
        # first-show ordering.  The single complete-tree layout pass replaces
        # any number of invalidations issued while the dialog was hidden.
        try:
            self.sendEvent(QEvent(QEvent.Polish))
        except Exception:
            pass
        if self._construction_layout_dirty:
            self._construction_layout_dirty = False
            self.sendEvent(QEvent(QEvent.LayoutRequest))
        if self._initial_visibility_requested:
            return self._show_now()
        return True

    def _configure_layout_item(self, item, **values):
        """Apply dialog-owned layout properties only when their value changed."""
        state = self._layout_native_state.setdefault(item, {})
        changed = {key: value for key, value in values.items()
                   if state.get(key, object()) != value}
        if not changed:
            return False
        dpg.configure_item(item, **changed)
        state.update(changed)
        return True

    def _apply_layout(self):
        if self.winfo_exists():
            layout = self.layout()
            if layout is not None:
                try:
                    layout.activate()
                except Exception:
                    pass
            self._configure_layout_item(
                self.content, width=-1,
                height=-(DialogMetrics.FOOTER_HEIGHT+1) if self.has_footer else -1)
            if self.has_footer:
                self._configure_layout_item(
                    self.footer_shell, width=-1, height=DialogMetrics.FOOTER_HEIGHT)
            status = getattr(self, "_footer_status", None)
            if status is not None:
                try:
                    dialog_width = int(dpg.get_item_width(self.tag) or 0)
                except Exception:
                    dialog_width = 0
                # A hidden, not-yet-rendered DPG window may report width=0.
                # Use the retained Qt geometry so the first complete-tree layout
                # does not collapse status wrapping and then reflow one frame later.
                dialog_width = max(dialog_width, int(self.width or 0))
                wrap = max(
                    80,
                    dialog_width
                    - getattr(self, "_footer_left_width", 0)
                    - self._footer_right_width - 60,
                )
                self._configure_layout_item(status, wrap=wrap)

    def after_first_present(self, callback, *args):
        """Start initial data work after the dialog's first visible frame.

        Native hosts distinguish hidden settle frames from real presentation.
        The main application supplies a normal after-render barrier instead.
        Closing/hiding before delivery discards the work, not just its results.
        """
        def deliver():
            if not self.winfo_exists():
                return
            if self.isConstructing():
                # The bounded main dispatcher can finish construction one turn
                # after this render barrier. Do not lose initial directory/data
                # loading merely because that first frame was still hidden.
                if self._initial_visibility_requested:
                    schedule = getattr(self.view, "after_render", None)
                    if callable(schedule):
                        schedule(deliver)
                    else:
                        self.view.after(16, deliver)
                return
            if (not self.isVisible()
                    or not getattr(self.view, "_presentation_visible", True)):
                return
            callback(*args)

        schedule = (getattr(self.view, "after_first_present", None)
                    or getattr(self.view, "after_render", None))
        if callable(schedule):
            return schedule(deliver)
        return self.view.after(0, deliver)

    def updateGeometry(self):
        """Post one compressed Qt-style layout request per application turn.

        In-process QDialogs now share QApplication's posted-event queue, so resize
        storms across several retained windows require one scheduler wake-up rather
        than one LatestCallQueue wake-up per dialog.  Process-hosted dialogs keep
        the historical dialog-local queue as a compatibility fallback.
        """
        if self._closed or self._deleted:
            return False
        if self.isConstructing():
            self._construction_layout_dirty = True
            return True
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                # Retained hidden dialogs do not need native layout traffic until
                # their next visibility lease. Collapse any number of hidden-state
                # invalidations into one LayoutRequest immediately before show().
                if not self.isVisible():
                    self._retained_layout_dirty = True
                    return True
                return application.postEvent(self, QEvent(QEvent.LayoutRequest))
        except Exception:
            pass
        return self._latest_updates.post("layout-request", self._deliver_layout_request)

    def _on_native_resize(self, sender=None, app_data=None, user_data=None):
        self.updateGeometry()

    def _deliver_layout_request(self):
        if self._closed or self._deleted:
            return
        if threading.get_ident() != self._ui_thread:
            raise RuntimeError("layout requests require the dialog's UI thread")
        if self.winfo_exists():
            self.sendEvent(QEvent(QEvent.LayoutRequest))

    def _sync_owned_widget_visibility(self):
        """Propagate top-level visibility to retained QWidget descendants.

        QDialog is historically not a QWidget subclass in this bridge, but its
        owned controls still need QWidget effective-visibility semantics.  Walk
        through the ownership helper QObject and emit logical Show/Hide edges
        without changing each child's explicit native ``show`` flag.
        """
        try:
            from ..widgets.widget import QWidget
            for child in QWidget._direct_widget_children(self._widget_owner):
                child._sync_effective_visibility(cleanup=False)
        except Exception:
            pass

    def _cancel_native_owner_repair(self):
        """Invalidate a queued close repair when this dialog becomes visible again."""
        self._native_owner_repair_generation += 1
        self._native_owner_close_lease = None

    def _disarm_native_modal_before_hide(self):
        """Release renderer/Win32 modality before the native viewport vanishes.

        DearUIQt native windows disable their owner from the renderer's modal
        registry.  Waiting until the following platform render to reconcile that
        registry can leave the main WinUx HWND disabled after a dialog closes.
        Disarm this top-level synchronously once QApplication has removed it from
        the modal stack.  A sibling modal, when present, remains authoritative.
        """
        backend = self._native_window_backend
        if backend is None or not self.modal:
            return False
        enable_owner = True
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                other = application.activeModalWidget()
                if other is not None and other is not self:
                    visible = getattr(other, "isVisible", None)
                    enable_owner = not (callable(visible) and bool(visible()))
        except Exception:
            pass
        try:
            return bool(backend.disarmModalBeforeHide(
                self.tag, enable_owner=enable_owner))
        except Exception:
            return False

    def _begin_native_owner_close(self):
        """Capture the Win32 owner while this native HWND still exists.

        Do not rely only on DearPyGui's focused-item bookkeeping here. A
        modeless native dialog can own the OS foreground through its caption or
        non-DPG chrome while ImGui still reports an older focused child. The
        backend's HWND foreground snapshot is authoritative and is safe for
        background closes because its lease explicitly disables activation.
        """
        backend = self._native_window_backend
        if backend is None:
            return None
        try:
            lease = backend.beginOwnerClose(self.tag)
        except Exception:
            lease = None
        if lease is not None:
            if getattr(lease, "return_foreground", False):
                self._restore_focus_on_hide = True
            # Preserve an earlier hide() lease if a subsequent terminal
            # destroy() runs after the renderer has already dropped the HWND
            # and can no longer resolve a fresh lease.
            self._native_owner_close_lease = lease
        return lease

    def _schedule_native_owner_repair(self, lease):
        """Repair z-order only after ImGui/GLFW has torn down the child viewport.

        ``hide_item`` only changes renderer state; the secondary HWND is removed
        during a later render.  A pre-hide SetForegroundWindow can therefore be
        undone by platform-window destruction.  Verify after the rendered frame,
        retrying only while the child is still visible or the owner is still
        legitimately disabled by native modal bookkeeping.
        """
        backend = self._native_window_backend
        if backend is None or lease is None:
            return False
        self._native_owner_repair_generation += 1
        generation = self._native_owner_repair_generation
        self._native_owner_close_lease = lease

        def attempt(attempt_index=0):
            if (generation != self._native_owner_repair_generation
                    or self._native_owner_close_lease is not lease):
                return
            try:
                result = backend.repairOwnerAfterHide(lease)
            except Exception:
                result = False
            if result is None and attempt_index < 8:
                schedule = getattr(self.view, "after_render", None)
                if callable(schedule):
                    schedule(attempt, attempt_index + 1)
                else:
                    self.view.after(16, attempt, attempt_index + 1)
                return
            if generation == self._native_owner_repair_generation:
                self._native_owner_close_lease = None

        schedule = getattr(self.view, "after_render", None)
        if callable(schedule):
            schedule(attempt, 0)
        else:
            self.view.after(0, attempt, 0)
        return True

    def show(self):
        if self.isConstructing():
            self._initial_visibility_requested = True
            return self._finish_initial_construction()
        return self._show_now()

    def _show_now(self):
        if not self.winfo_exists():
            return False
        self._cancel_native_owner_repair()
        # Match Qt modality: a modeless QDialog is still a foreground pointer
        # surface, but it must not globally disable background interaction.
        # Only an actually modal QDialog enters the modal registry.
        if self.modal:
            register_modal_window(self.tag)
        elif self._native_window_backend is not None:
            # A native modeless dialog may be visible *behind* the main WinUx
            # HWND. Protect only the HWND actually under the pointer, rather
            # than its rectangle projected over the main viewport.
            register_pointer_protected_item(
                self.tag,
                hit_test=lambda point: self._native_window_backend.containsGlobalPoint(
                    self.tag, point),
            )
        else:
            register_pointer_protected_item(self.tag)
        if not getattr(self, "_application_keyboard", False):
            register_escape_target(self.tag, self.reject, self._accepts_dialog_keys)
        if self in _DIALOGS:
            _DIALOGS.remove(self)
            _DIALOGS.append(self)
        already_visible = bool(self._visible_state)
        if not already_visible:
            self._initial_pointer_activity = False
            # Cancel focus repairs still queued for a previous visibility lease.
            self._pointer_interaction_serial += 1
            if self._retained_layout_dirty:
                self._retained_layout_dirty = False
                self.sendEvent(QEvent(QEvent.LayoutRequest))
            # Capture the launcher focus on every new visibility lease, not
            # only in __init__. A reusable QDialog shown from a different
            # control must return focus to that new launcher when it closes.
            try:
                current_focus = dpg.get_focused_item() or None
            except Exception:
                current_focus = None
            if current_focus != self.tag and not self._item_belongs_to(current_focus, self.tag):
                self._focus_restore_item = current_focus
            if self.modal and not bool(getattr(self.view, "is_standalone_ui_host", False)):
                # Resolve the launcher *before* making this dialog active;
                # otherwise activeWindow() would incorrectly point to self.
                self.center()
                if self._native_window_backend is not None:
                    self._native_window_backend.configure(
                        self.tag, owner=self._modal_native_parent(), modal=True,
                        owner_hwnd=self._native_main_owner_hwnd())
            dpg.show_item(self.tag)
            self._visible_state = True
            self._sync_owned_widget_visibility()
            # QWidget::show() emits Show only on the hidden->visible edge.
            self.sendEvent(QEvent(QEvent.Show))
        if not already_visible:
            if self._native_window_backend is not None:
                self.after_first_present(self._synchronize_native_owner_once)
                self.after_first_present(self._prepare_native_first_click_once)
                if self.modal:
                    self.after_first_present(self._activate_native_modal_once)
                if not self._resizable:
                    self.after_first_present(self._apply_native_resize_policy_once)
            self._schedule_native_modal_center()
        dpg.focus_item(self.tag)
        self._activation_owned = True
        # Like QWidget::show(), a re-shown QDialog restores child focus rather
        # than leaving keyboard navigation on the top-level container.
        # Focus child controls only after their first visible native frame.
        # after(0) can run in this same bounded dispatcher turn, before the
        # platform window/control geometry exists, leaving a queued focus request
        # to compete with the user's first mouse activation.
        self.after_first_present(self._apply_initial_focus_if_idle)
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                if self.modal:
                    application._register_modal(self)
                else:
                    application._unregister_modal(self)
                application._set_active_window(self)
                application._set_focus_widget(self)
                application.registerPointerTarget(self)
        except Exception:
            pass
        return True

    def raise_(self):
        """Qt-style raise/activate facade for a native-immediate-mode window."""
        return self.show()

    lift = raise_

    def _accepts_dialog_keys(self):
        """Return whether this top-level owns QDialog keyboard semantics."""
        return bool(self.modal or self.isActiveWindow())

    def setTheme(self, theme):
        """Bind a DearUIQt theme resource to the native dialog window."""
        native = theme.nativeId() if hasattr(theme, "nativeId") else theme
        try:
            dpg.bind_item_theme(self.tag, native)
        except Exception:
            return False
        self._bound_theme = theme
        return True

    def theme(self):
        return getattr(self, "_bound_theme", None)

    def activateWindow(self):
        if not self.winfo_exists():
            return False
        if not getattr(self, "_application_keyboard", False):
            register_escape_target(self.tag, self.reject, self._accepts_dialog_keys)
        if self in _DIALOGS:
            _DIALOGS.remove(self)
            _DIALOGS.append(self)
        try:
            dpg.focus_item(self.tag)
            self._activation_owned = True
            try:
                from ..core.application import QApplication
                application = QApplication.instance()
                if application is not None:
                    application._set_active_window(self)
                    application._set_focus_widget(self)
            except Exception:
                pass
            return True
        except Exception:
            return False

    activate = activateWindow
    focus = activateWindow
    setFocus = activateWindow

    def hide(self):
        if self.isConstructing():
            # A hide/close request before the queued first show must cancel that
            # visibility lease; otherwise the deferred callback could resurrect
            # a dialog that its owner already closed.  Finish the transaction
            # without emitting Show/Hide because the window was never exposed.
            self._initial_visibility_requested = False
            self._finish_initial_construction()
            return True
        if not self.winfo_exists():
            return False
        if not self._visible_state:
            return False
        # Decide focus ownership *before* hiding. Qt returns activation from a
        # foreground dialog, but closing a background/modeless window does not
        # pull focus away from another active window.
        try:
            focused_item = dpg.get_focused_item() or None
        except Exception:
            focused_item = None
        self._restore_focus_on_hide = bool(
            self.modal or self._item_belongs_to(focused_item, self.tag)
        )
        # Native multi-viewport dialogs are real owned HWNDs.  Transfer the
        # foreground slot to their owner *before* the foreground child is
        # hidden; otherwise Windows may activate an unrelated application while
        # the modal owner is still disabled.  The backend refuses this hand-off
        # when another application already owns foreground, preserving Alt-Tab.
        native_owner_lease = self._begin_native_owner_close()
        self._activation_owned = False
        guard_pointer_surface_release(self.tag)
        if self.modal:
            # A hidden/destroyed modal cannot retain an explicit mouse grab.
            # Qt releases QWidget mouse grabs as the top-level is deactivated.
            release_pointer_input()
        dpg.hide_item(self.tag)
        self._visible_state = False
        self._sync_owned_widget_visibility()
        unregister_escape_target(self.tag)
        unregister_modal_window(self.tag)
        unregister_pointer_protected_item(self.tag)
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                application._unregister_modal(self)
                application.unregisterPointerTarget(self)
                application._widget_hidden(self)
        except Exception:
            pass
        # Release the renderer-owned native modal relationship in this same UI
        # callback.  Do not make the next platform render responsible for
        # re-enabling the main WinUx HWND after Cancel/Close.
        self._disarm_native_modal_before_hide()
        # The native child HWND is destroyed/unmapped by the renderer, not by
        # dpg.hide_item() itself. Verify foreground only after that render so
        # platform teardown cannot push the owner behind another application.
        if native_owner_lease is not None:
            self._schedule_native_owner_repair(native_owner_lease)

        # QWidget::hide() returns focus only when this top-level actually owned
        # activation. Queue it so a sibling shown in the same UI transaction
        # wins naturally instead of producing a focus flash.
        if self._restore_focus_on_hide:
            self.view.after(0, self._restore_embedded_owner_focus)
        self.sendEvent(QEvent(QEvent.Hide))
        return True

    def _handle_key_event(self, event):
        if not self._accepts_dialog_keys():
            return False
        focused = self.focusWidget()
        if focused is None:
            # InputText can report the containing child-window as DPG's nav
            # focus item while its editor is active. The retained input target
            # still identifies the combo without scanning every table row.
            from ..core.application import QApplication
            application = QApplication.instance()
            target = application.focusObject() if application is not None else None
            candidate = target if isinstance(target, QComboBox) else getattr(target, "parent", None)
            if (isinstance(candidate, QComboBox)
                    and self._control_wrappers.get(candidate.tag) is candidate
                    and candidate._choice_field is not None and candidate._choice_field.hasFocus()):
                focused = candidate
        if (isinstance(focused, QComboBox) and focused._choice_field is not None
                and focused._choice_key_event(event)):
            return True
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)

        if key == getattr(dpg, "mvKey_Escape", None):
            self.reject()
            return True
        if key in tuple(value for value in (
                getattr(dpg, "mvKey_Return", None),
                getattr(dpg, "mvKey_Enter", None),
                getattr(dpg, "mvKey_NumPadEnter", None)) if value is not None):
            self.invoke_default()
            return True

        shortcut = self.shortcuts.get((key, ctrl))
        if shortcut:
            shortcut()
            return True
        if key == getattr(dpg, "mvKey_Tab", None) and not ctrl:
            self.focusNextPrevChild(next=not shift)
            return True
        table = self.active_table
        if table is not None and not _editor_is_active():
            table.navigate(key, ctrl=ctrl, shift=shift)
            return True
        return False

    def event(self, event):
        event_type = event.type()
        if isinstance(event, QMouseEvent) and event_type == QEvent.MouseButtonPress:
            # Persist the physical interaction through the after-render focus
            # callback; ImGui may already report mouse-up and focus=self.tag
            # by the time deferred initial focus is serviced.
            self._initial_pointer_activity = True
            self._pointer_interaction_serial = getattr(self, "_pointer_interaction_serial", 0) + 1
        if isinstance(event, QMouseEvent) and self._route_button_pointer(event):
            return True
        if event_type == QEvent.KeyPress and isinstance(event, QKeyEvent):
            return self._handle_key_event(event)
        if event_type == QEvent.Show:
            self.showEvent(event)
            return True
        if event_type == QEvent.Hide:
            target = getattr(self, "_button_pointer_target", None)
            self._button_pointer_target = None
            if target is not None and not target._deleted:
                target._end_pointer_click(False)
            self.hideEvent(event)
            return True
        if event_type == QEvent.Close:
            self.closeEvent(event)
            return True
        if event_type == QEvent.LayoutRequest:
            if threading.get_ident() != self._ui_thread:
                raise RuntimeError("layout requests require the dialog's UI thread")
            self._apply_layout()
            self.changeEvent(event)
            return True
        if event_type == QEvent.ParentChange:
            self.changeEvent(event)
            return True
        if event_type == QEvent.Polish:
            self.polishEvent(event)
            return True
        return QObject.event(self, event)

    def hitTest(self, position):
        """Register modeless dialogs without intercepting windows above them."""
        if not self.isVisible():
            return False
        x, y = position.x(), position.y()
        if self._native_window_backend is not None:
            return self._native_window_backend.containsGlobalPoint(self.tag, (x, y))
        if not self.isActiveWindow():
            return False
        left, top = dpg.get_item_rect_min(self.tag)
        width, height = dpg.get_item_rect_size(self.tag)
        return left <= x < left + width and top <= y < top + height

    def _button_contains_global_point(self, button, point):
        if (button._deleted or not self.isVisible()
                or not button.isVisible() or not button.isEnabled()):
            return False
        try:
            is_shown = getattr(dpg, "is_item_shown", None)
            if callable(is_shown) and not is_shown(button.tag):
                return False
            left, top = dpg.get_item_rect_min(button.tag)
            width, height = dpg.get_item_rect_size(button.tag)
            if hasattr(point, "x") and callable(point.x):
                px, py = float(point.x()), float(point.y())
            else:
                px, py = map(float, point[:2])
            return (width > 0 and height > 0 and left <= px < left + width
                    and top <= py < top + height)
        except Exception:
            return False

    def _button_contains_pointer(self, button, event):
        # ImGui's visible state is last-frame data; hit-test the current native
        # rectangle directly so first-frame clicks are not discarded.
        return self._button_contains_global_point(button, event.globalPosition())

    def _route_button_pointer(self, event):
        if event.button() != Qt.LeftButton:
            return False
        if event.type() == QEvent.MouseButtonPress:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.activePopupWidget() is not None:
                return False
            old = getattr(self, "_button_pointer_target", None)
            self._button_pointer_target = None
            if old is not None and not old._deleted:
                old._end_pointer_click(False)
            for button in reversed(tuple(self._control_wrappers.values())):
                if isinstance(button, QPushButton) and self._button_contains_pointer(button, event):
                    if button._begin_pointer_click():
                        self._button_pointer_target = button
                        return True
        elif event.type() == QEvent.MouseButtonRelease:
            button = getattr(self, "_button_pointer_target", None)
            self._button_pointer_target = None
            if button is not None and not button._deleted:
                button._end_pointer_click(self._button_contains_pointer(button, event))
                return True
        return False

    def polishEvent(self, event):
        pass

    def showEvent(self, event):
        pass

    def hideEvent(self, event):
        pass

    def changeEvent(self, event):
        pass

    def setVisible(self, visible):
        return self.show() if bool(visible) else self.hide()

    def isVisible(self):
        if not self.winfo_exists():
            return False
        if hasattr(self, "_visible_state"):
            return bool(self._visible_state)
        # Partial construction/test harnesses and recycled legacy forms may not
        # have primed retained visibility yet. Query the native tag only as a
        # compatibility fallback; normal dialogs stay entirely state-driven.
        try:
            return bool(dpg.is_item_shown(self.tag))
        except Exception:
            return True

    def isHidden(self):
        return not self.isVisible()

    def isActiveWindow(self):
        if not self.winfo_exists() or not self.isVisible():
            return False
        try:
            focused = dpg.get_focused_item() or None
            return bool(
                dpg.is_item_focused(self.tag)
                or self._item_belongs_to(focused, self.tag)
            )
        except Exception:
            return False

    def activateWindow(self):
        """Request activation/focus for this top-level dialog.

        Keeping this synchronization point in DearUIQt prevents application
        forms from calling renderer ``focus_item`` directly and lets future
        backends implement platform-specific activation semantics centrally.
        """
        if not self.winfo_exists() or not self.isVisible():
            return False
        try:
            dpg.focus_item(self.tag)
            self._activation_owned = True
            return True
        except Exception:
            return False

    def setWindowTitle(self, title):
        self._window_title = str(title or "")
        if self.winfo_exists():
            dpg.configure_item(self.tag, label=self._window_title)

    def windowTitle(self):
        return self._window_title

    def winId(self):
        """Native HWND for opt-in multi-viewport dialogs; zero for overlays."""
        native = getattr(self, "_native_window_backend", None)
        return native.winId(self.tag) if native is not None else 0

    def setMinimumSize(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        dpg.configure_item(self.tag, min_size=(max(0, size.width()), max(0, size.height())))

    def setFixedSize(self, width, height=None):
        """Fix the top-level dialog size, matching QWidget::setFixedSize()."""
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        self.width = max(0, size.width())
        self.height = max(0, size.height())
        self._resizable = False
        if self.winfo_exists():
            dpg.configure_item(
                self.tag, width=self.width, height=self.height, no_resize=True,
                min_size=(self.width, self.height),
                max_size=(self.width, self.height))
        if self._native_window_backend is not None and self.isVisible():
            self.after_first_present(self._apply_native_resize_policy_once)
        self.updateGeometry()

    def isResizable(self):
        return bool(self._resizable)

    def minimumSize(self):
        width, height = dpg.get_item_configuration(self.tag).get("min_size", (0, 0))
        return QSize(width, height)

    def resize(self, width, height=None):
        """Resize the retained top-level without moving or showing it."""
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        if not self.winfo_exists():
            return
        minimum = self.minimumSize()
        self.width = max(0, minimum.width(), size.width())
        self.height = max(0, minimum.height(), size.height())
        dpg.configure_item(self.tag, width=self.width, height=self.height)
        self.updateGeometry()

    def setLayout(self, layout):
        """Install one retained layout into the dialog body.

        This is the migration bridge from historical ``self.content`` parenting
        to Qt-style ``dialog.setLayout(layout)``. Existing direct DPG form code
        remains valid while new forms can use ownership-based layouts.
        """
        if self._closed:
            raise RuntimeError("cannot set a layout on a closed dialog")
        if layout is None:
            return self.takeLayout()
        if not getattr(layout, "_is_layout", False):
            raise TypeError("setLayout requires a QLayout")
        if getattr(layout, "backend", None) is not get_backend():
            raise ValueError("dialog and layout must use the same backend")
        if self._layout_manager is not None and self._layout_manager is not layout:
            raise RuntimeError("dialog already has a layout")
        dpg.move_item(layout._layout_tag(), parent=self.content)
        self.own_widget(layout)
        self._layout_manager = layout
        invalidate = getattr(layout, "invalidate", None)
        if callable(invalidate):
            invalidate()
        self.updateGeometry()
        return layout

    def layout(self):
        layout = self._layout_manager
        return None if layout is not None and layout._deleted else layout

    def takeLayout(self):
        layout = self.layout()
        if layout is None:
            self._layout_manager = None
            return None
        # Keep the layout live under the dialog body but transfer QObject
        # ownership to the caller, matching Qt's take-style ownership contract.
        layout.setParent(None)
        self._layout_manager = None
        self.updateGeometry()
        return layout

    def closeEvent(self, event):
        event.accept()

    def close(self):
        """Request QDialog close with QWidget lifetime semantics.

        Qt hides a top-level on an accepted close event and deletes the object
        only when WA_DeleteOnClose is set.  Historical forms may still call
        destroy() explicitly when they require terminal disposal.
        """
        if self._closed or self._destroy_scheduled:
            return True
        event = QCloseEvent()
        self.sendEvent(event)
        if not event.isAccepted():
            return False
        self.hide()
        if self.testAttribute(Qt.WA_DeleteOnClose):
            self.deleteLater()
        return True

    def setAttribute(self, attribute, on=True):
        value = int(attribute)
        if on:
            self._attributes.add(value)
        else:
            self._attributes.discard(value)

    def testAttribute(self, attribute):
        return int(attribute) in self._attributes

    def delete(self):
        self.destroy()

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

    def _note_button_activation(self, *_args):
        self._button_activation_serial = int(getattr(self, "_button_activation_serial", 0)) + 1

    def action(self, label, callback, role="secondary", default=False, parent=None,
               width=None, height=None):
        widget = self.own_widget(QPushButton(
            label,
            width=self.action_width(label) if width is None else int(width),
            height=DialogMetrics.BUTTON_HEIGHT if height is None else int(height),
            role=role, default=default, parent=self._qt_parent(parent or self.footer),
            after=self.view.after, backend=get_backend()))
        widget.clicked.connect(callback)
        button = widget.tag
        wrappers = getattr(self, "_control_wrappers", None)
        if wrappers is not None:
            wrappers[button] = widget
        # ImGuiPushButton owns the shared state/theme contract.  Avoid rebinding
        # a second dialog-local theme here so hover/disabled/default behavior is
        # identical in dialogs and non-dialog tool panels.  QDialog promotes the
        # first primary action to the default button even when the caller did not
        # spell out default=True; a focused push button still wins on Return.
        if default or (str(role or "secondary").lower() == "primary" and self._default_button is None):
            self._default, self._default_button = callback, button
            widget.setDefault(True)
        caption = str(label or "").strip().lower().replace("&", "")
        if caption in _DIALOG_REJECT_CAPTIONS and self._reject_button is None:
            self._reject, self._reject_button = callback, button
        self._remember_focusable(button)
        return button

    @staticmethod
    def action_width(label):
        return max(DialogMetrics.BUTTON_WIDTH, len(label) * 7 + 16)

    def button_box(self, actions, left_actions=(), status_item=None, status_left_padding=0, button_gap=None):
        """QDialogButtonBox-like layout with auxiliary actions on the left.

        The old footer placed status text and auxiliary buttons in the same
        horizontal group, so long status messages squeezed buttons and shifted
        the accept/cancel group between dialogs.  Qt keeps those roles in
        independent layout slots; mirror that here.
        """
        actions = list(actions or ())
        left_actions = list(left_actions or ())
        button_gap = DialogMetrics.BUTTON_GAP if button_gap is None else max(0, int(button_gap))

        def group_width(items):
            if not items:
                return 0
            return sum(self.action_width(item[0]) for item in items) + \
                button_gap * max(0, len(items) - 1)

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
            min_size=(minimum_width, getattr(
                self, "_minimum_dialog_height", DialogMetrics.MIN_DIALOG_HEIGHT)),
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
                    with dpg.group(horizontal=True, horizontal_spacing=button_gap) as left:
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
                with dpg.group(horizontal=True, horizontal_spacing=button_gap) as group:
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
        # This table participates in content-sized QGroupBox pages (Settings,
        # editors and small dialogs). Dear ImGui's default table height is the
        # remaining available space. Inside an always-auto-resize child window
        # that can feed back into the child's desired height and produce an
        # ever-growing outer scroll range. Height 0 sizes to actual rows.
        table = dpg.add_table(
            parent=parent or self.content,
            header_row=False, width=-1, height=0,
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
                always_use_window_padding=True,
            )
            dpg.bind_item_theme(label_cell, form_label_cell_theme(dpg))
            if label:
                dpg.add_text(str(label), parent=label_cell)
            with dpg.group() as editor_cell:
                return builder(editor_cell)

    def form_layout_editor_row(self, table, builder):
        """Append an unlabeled editor row to a shared form layout.

        This keeps the renderer-specific table row inside DearUIQt while letting
        application forms add compact full-editor rows (for example a checkbox)
        without reaching into the Dear PyGui table API directly.
        """
        with dpg.table_row(parent=table):
            dpg.add_spacer(width=1, height=0)
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
            height=0,  # Content-sized even inside an auto-height dialog section.
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
            column_widths=(DialogMetrics.LABEL_WIDTH, None), parent=self._qt_parent(parent or self.content),
            height=0, after=self.view.after, backend=get_backend()))
        try:
            dpg.bind_item_theme(grid.tag, form_row_theme(dpg))
            label_cell = grid.cell(0, 0)
            dpg.bind_item_theme(label_cell.tag, aligned_cell_theme(dpg))
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
        serial = getattr(self, "_pointer_interaction_serial", 0)

        def repair_focus_if_idle(*_args, **_kwargs):
            if (self.isVisible()
                    and getattr(self, "_pointer_interaction_serial", 0) == serial):
                self._focus_text_editor_now(item)

        try:
            frame = int(dpg.get_frame_count())
            for offset in (1, 2):
                dpg.set_frame_callback(frame + offset, repair_focus_if_idle)
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

    def contentWidget(self):
        """Return the retained QWidget facade for the dialog body surface."""
        return self._content_widget

    def setShortcut(self, key, callback, *, ctrl=False):
        """Bind a Qt key constant to this dialog's shortcut table.

        Application code can now use ``Qt.Key_*`` without importing renderer
        key symbols.  The established native-key shortcut table remains the
        compatibility storage used by standalone dialog dispatch.
        """
        if not callable(callback):
            raise TypeError("shortcut callback must be callable")
        from ..core.input import QGlobalInputBinding
        native = QGlobalInputBinding.nativeKeyFor(key, dpg)
        if native is None:
            return False
        self.shortcuts[(native, bool(ctrl))] = callback
        return True

    def clearShortcut(self, key, *, ctrl=False):
        from ..core.input import QGlobalInputBinding
        native = QGlobalInputBinding.nativeKeyFor(key, dpg)
        if native is None:
            return False
        return self.shortcuts.pop((native, bool(ctrl)), None) is not None

    def line_edit_widget(self, value="", parent=None, **kwargs):
        """Create and return the owned QLineEdit wrapper.

        New application code should prefer this method so text/focus/theme
        changes remain inside DearUIQt.  :meth:`line_edit` keeps returning the
        native id for source compatibility with older dialog forms.
        """
        options = dict(kwargs)
        requested_width = int(options.pop("width", -1))
        native_parent = options.pop("parent", parent)
        if bool(options.get("multiline", False)):
            raise ValueError("line_edit_widget is single-line; use QPlainTextEdit for multiline input")
        widget = self.own_widget(ImGuiLineEdit(
            str(value), parent=self._qt_parent(native_parent), after=self.view.after, backend=get_backend(),
            width=requested_width, **options))
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
        return widget

    def line_edit(self, value="", parent=None, **kwargs):
        """Compatibility helper returning the native id of an owned QLineEdit."""
        options = dict(kwargs)
        requested_width = int(options.get("width", -1))
        native_parent = options.get("parent", parent)
        if bool(options.get("multiline", False)):
            options.pop("multiline", None)
            options.pop("width", None)
            options.pop("parent", None)
            return self.plain_text_edit(
                value, parent=native_parent, width=requested_width, **options)
        return self.line_edit_widget(value, parent=parent, **kwargs).tag


    def plain_text_edit(self, value="", parent=None, *, width=-1, height=-1,
                        readonly=False, **kwargs):
        """Create a shared QPlainTextEdit-like multiline editor.

        The reusable native editor now lives in DearUIQt.QPlainTextEdit; this
        dialog helper only applies dialog chrome and registers Enter ownership.
        """
        widget = self.own_widget(QPlainTextEdit(
            str(value), parent=self._qt_parent(parent), after=self.view.after, backend=get_backend(),
            width=width, height=height, readonly=readonly, **kwargs,
        ))
        try:
            dpg.bind_item_theme(widget.tag, plain_text_edit_theme())
        except Exception:
            pass
        self._control_wrappers[widget.tag] = widget
        # QTextEdit/QPlainTextEdit own Return; QDialog must not translate it to
        # the default button while this editor has focus.
        self.enter_editors.add(widget.tag)
        self._remember_focusable(widget.tag)
        return widget.tag


    def spin_int(self, value=0, parent=None, *, minimum=None, maximum=None,
                 step=1, width=-1, callback=None):
        widget = self.own_widget(ImGuiSpinBox(
            value, parent=self._qt_parent(parent), after=self.view.after, backend=get_backend(),
            width=width, minimum=minimum, maximum=maximum,
            step=step, callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
        return widget.tag

    def spin_float(self, value=0.0, parent=None, *, minimum=None, maximum=None,
                   step=0.1, decimals=2, width=-1, callback=None):
        widget = self.own_widget(ImGuiDoubleSpinBox(
            value, parent=self._qt_parent(parent), after=self.view.after, backend=get_backend(),
            width=width, minimum=minimum, maximum=maximum,
            step=step, decimals=decimals, callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
        return widget.tag

    def checkbox(self, text="", *, checked=False, parent=None):
        """Create a retained native Dear ImGui checkbox with Qt-like states."""
        widget = self.own_widget(ImGuiCheckBox(
            text, checked=checked, parent=self._qt_parent(parent), after=self.view.after, backend=get_backend(),
        ))
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
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
            parent=self._qt_parent(parent),
            after=self.view.after,
            backend=get_backend(),
            callback=callback,
        ))
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
        return widget.tag

    def progress_bar(self, value=0.0, *, parent=None, overlay=None):
        """Create the shared retained progress-bar surface and return its tag."""
        widget = self.own_widget(ImGuiProgressBar(
            parent=self._qt_parent(parent), after=self.view.after, backend=get_backend(),
        ))
        widget.setValue(value)
        if overlay is not None:
            widget.setFormat(overlay)
        self._control_wrappers[widget.tag] = widget
        return widget.tag

    def combo(self, items=(), parent=None, **kwargs):
        """Create the shared Qt-style combo, retaining the historical tag API."""
        theme_provider = kwargs.pop('theme_provider', None)
        if theme_provider is not None and not callable(theme_provider):
            raise TypeError('theme_provider must be callable or None')
        callback = adapt_combo_callback(kwargs.pop("callback", None), kwargs.pop("user_data", None))
        current = kwargs.pop("default_value", None)
        enabled, visible = kwargs.pop("enabled", True), kwargs.pop("show", True)
        max_rows = kwargs.pop("max_visible_items", 8)
        widget = self.own_widget(QComboBox(
            list(items), current=current, parent=self._qt_parent(parent), after=self.view.after,
            backend=get_backend(), editable=kwargs.pop("editable", False),
            width=kwargs.pop("width", -1), callback=callback))
        widget.setMaxVisibleItems(max_rows)
        widget.setPopupParent(self.tag)
        # Native mvCombo theme providers cannot style the new composite field;
        # accept the legacy option while keeping all combo chrome consistent.
        if kwargs:
            dpg.configure_item(widget.tag, **kwargs)
        self._control_wrappers[widget.tag] = widget
        focus_item = widget._choice_field.button if widget._choice_field is not None else widget.tag
        self._control_wrappers[focus_item] = widget
        self._remember_focusable(focus_item)
        if not enabled:
            widget.setEnabled(False)
        if not visible:
            widget.hide()
        return widget.tag

    def runtime_running(self):
        """Return whether the retained GUI runtime is still processing frames.

        Dialog/form code should not need to import the renderer merely to guard
        a compatibility wait loop.  Keep that lifecycle query inside the
        DearUIQt dialog boundary.
        """
        try:
            return bool(dpg.is_dearpygui_running())
        except Exception:
            return False

    def control_wrapper(self, item):
        """Return the DearUIQt wrapper associated with a native control/tag."""
        if hasattr(item, "tag") and not isinstance(item, (int, str)):
            return item
        return self._control_wrappers.get(item)

    def control_value(self, item, default=None):
        """Read a control through its Qt-style API with a backend fallback."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            # Value semantics take precedence over display/label text.  In
            # particular QCheckBox exposes both text() (its caption) and
            # isChecked() (its actual value); returning the caption here would
            # silently turn every non-empty checkbox label into True.
            for name in ("isChecked", "currentText", "value", "toPlainText", "text"):
                method = getattr(wrapper, name, None)
                if callable(method):
                    try:
                        return method()
                    except TypeError:
                        continue
        tag = getattr(item, "tag", item)
        try:
            return dpg.get_value(tag)
        except Exception:
            return default

    def set_control_value(self, item, value):
        """Set a retained value without exposing renderer calls to form code."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            methods = []
            if isinstance(value, bool):
                methods.append("setChecked")
            methods.extend(("setCurrentText", "setText", "setValue", "setPlainText"))
            for name in methods:
                method = getattr(wrapper, name, None)
                if callable(method):
                    try:
                        method(value)
                        return True
                    except (TypeError, ValueError):
                        continue
        tag = getattr(item, "tag", item)
        try:
            dpg.set_value(tag, value)
            return True
        except Exception:
            return False

    def set_control_items(self, item, items, *, preserve_value=False):
        """Replace selectable/combo choices through a Qt-style facade."""
        values = [str(value) for value in items]
        previous = self.control_value(item) if preserve_value else None
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            clear = getattr(wrapper, "clear", None)
            add_items = getattr(wrapper, "addItems", None) or getattr(wrapper, "add_items", None)
            if callable(clear) and callable(add_items):
                clear()
                add_items(values)
                if preserve_value and previous in values:
                    self.set_control_value(item, previous)
                return True
        tag = getattr(item, "tag", item)
        try:
            dpg.configure_item(tag, items=values)
            if preserve_value and previous in values:
                dpg.set_value(tag, previous)
            return True
        except Exception:
            return False

    def control_visible(self, item):
        """Return the retained visibility state without exposing renderer queries."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            method = getattr(wrapper, "isVisible", None)
            if callable(method):
                try:
                    return bool(method())
                except Exception:
                    pass
        tag = getattr(item, "tag", item)
        try:
            return bool(dpg.is_item_shown(tag))
        except Exception:
            return False

    def set_control_visible(self, item, visible):
        """Show/hide a retained control through its QWidget facade when available."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            method = getattr(wrapper, "setVisible", None)
            if callable(method):
                try:
                    method(bool(visible))
                    return True
                except Exception:
                    pass
        tag = getattr(item, "tag", item)
        try:
            dpg.configure_item(tag, show=bool(visible))
            return True
        except Exception:
            return False

    def set_control_theme(self, item, theme):
        """Bind a DearUIQt/native theme without leaking renderer calls to forms."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            method = getattr(wrapper, "setTheme", None)
            if callable(method):
                try:
                    return bool(method(theme))
                except Exception:
                    pass
        tag = getattr(item, "tag", item)
        native = theme.nativeId() if hasattr(theme, "nativeId") else theme
        try:
            dpg.bind_item_theme(tag, native)
            return True
        except Exception:
            return False

    def focus_control(self, item):
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            method = getattr(wrapper, "setFocus", None)
            if callable(method):
                return method() is not False
        tag = getattr(item, "tag", item)
        try:
            dpg.focus_item(tag)
            return True
        except Exception:
            return False

    def control_exists(self, item):
        wrapper = self.control_wrapper(item)
        if wrapper is not None and getattr(wrapper, "_deleted", False):
            return False
        tag = getattr(item, "tag", item)
        try:
            return bool(dpg.does_item_exist(tag))
        except Exception:
            return False

    def delete_control(self, item):
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            delete = getattr(wrapper, "delete", None) or getattr(wrapper, "destroy", None)
            if callable(delete):
                delete()
                return True
        tag = getattr(item, "tag", item)
        try:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
            return True
        except Exception:
            return False

    def set_control_enabled(self, item, enabled):
        """Enable/disable a retained control as one visual/behavioral unit."""
        wrapper = self.control_wrapper(item)
        if wrapper is not None:
            wrapper.setEnabled(bool(enabled))
            return
        tag = getattr(item, "tag", item)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=bool(enabled))
            self.refresh_control_style(tag)

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
            from ..modelview.themes import qt_item_view_theme
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
            parent=parent, header_row=False, width=-1, height=0,
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
            title, parent=self._qt_parent(parent or self.content), after=self.view.after, backend=get_backend(),
            width=-1, auto_resize_y=True,
        ))
        # QGroupBox captions use the application/body font.  Reserve the
        # larger heading font for the page title above the separator; using it
        # for every Settings section made the page look like stacked ImGui
        # cards rather than a native Qt preferences page.
        with box:
            yield box.content

    def _remember_focusable(self, item):
        if item is not None and item not in self._focus_order:
            self._focus_order.append(item)
        return item

    def _item_is_focusable(self, item):
        if item is None:
            return False
        wrapper = self._control_wrappers.get(item)
        if isinstance(wrapper, QComboBox) and (not wrapper.isVisible() or not wrapper.isEnabled()):
            return False
        try:
            if not dpg.does_item_exist(item) or not dpg.is_item_shown(item):
                return False
            config = dpg.get_item_configuration(item) or {}
            return bool(config.get("enabled", True))
        except Exception:
            return False

    @staticmethod
    def _item_belongs_to(item, ancestor):
        if item is None or ancestor is None:
            return False
        try:
            current = item
            seen = set()
            for _ in range(64):
                if current == ancestor:
                    return True
                if not current or current in seen or not dpg.does_item_exist(current):
                    break
                seen.add(current)
                current = (dpg.get_item_info(current) or {}).get("parent")
            return False
        except Exception:
            return False

    def set_initial_focus(self, item):
        """Set the QWidget-style initial focus target for this dialog."""
        self._initial_focus_item = item
        self._remember_focusable(item)
        return item

    def _apply_initial_focus_if_idle(self):
        """Gate even forms that override _focus_initial (e.g. SSH Login).

        A first click can complete before the after-present callback. Checking
        only DPG's current active/mouse state cannot detect that gesture.
        """
        if getattr(self, "_initial_pointer_activity", False):
            return False
        return self._focus_initial()

    def _focus_initial(self):
        if getattr(self, "_initial_pointer_activity", False):
            return False
        if not self.winfo_exists() or not dpg.is_item_shown(self.tag):
            return False
        from ..core.application import QApplication
        application = QApplication.instance()
        if application is not None and not application.canFocusWidget(self):
            return False
        # Initial keyboard focus is a convenience, never a reason to cancel an
        # already-started physical click (button, checkbox, combo or editor).
        # On Windows, an activation press may reach the HWND before DPG's
        # input snapshot reflects it. Check physical state independently so a
        # backend error cannot skip the normal focus and press guards.
        try:
            if _mouse_button_down():
                return False
        except Exception:
            pass
        try:
            if any(dpg.is_mouse_button_down(button) for button in (
                    dpg.mvMouseButton_Left, dpg.mvMouseButton_Right,
                    dpg.mvMouseButton_Middle)):
                return False
        except Exception:
            pass
        try:
            focused = dpg.get_focused_item()
            # Native buttons may be focused but no longer `active` by the
            # time this after-first-present callback runs. Any focused child
            # belongs to the user, not deferred initial keyboard navigation.
            if focused != self.tag and self._item_belongs_to(focused, self.tag):
                return False
        except Exception:
            pass
        candidates = []
        if self._initial_focus_item is not None:
            candidates.append(self._initial_focus_item)
        # Editors/options precede dialog buttons, matching QDialog tab order.
        candidates.extend(item for item in self._focus_order if item != self._default_button)
        if self._default_button is not None:
            candidates.append(self._default_button)
        for item in candidates:
            if self._item_is_focusable(item):
                try:
                    focus = getattr(self, "focus_control", None)
                    if callable(focus):
                        if focus(item) is False:
                            continue
                    else:
                        dpg.focus_item(item)
                    return True
                except Exception:
                    continue
        try:
            dpg.focus_item(self.tag)
        except Exception:
            return False
        return True

    def focusWidget(self):
        """Return the retained wrapper currently focused inside the dialog.

        Qt returns a QWidget here. Legacy raw Dear PyGui controls have no
        retained wrapper, so they intentionally return ``None`` rather than
        leaking a backend item id through the Qt-style API.
        """
        try:
            item = dpg.get_focused_item() or None
        except Exception:
            return None
        if item is None or not self._item_belongs_to(item, self.tag):
            return None
        return self._control_wrappers.get(item)

    def setTabOrder(self, first, second):
        """Place *second* immediately after *first* in this dialog's chain."""
        first_item = getattr(first, "tag", first)
        second_item = getattr(second, "tag", second)
        if first_item is None or second_item is None or first_item == second_item:
            return False
        self._remember_focusable(first_item)
        self._remember_focusable(second_item)
        order = [item for item in self._focus_order if item != second_item]
        try:
            index = order.index(first_item) + 1
        except ValueError:
            return False
        order.insert(index, second_item)
        self._focus_order[:] = order
        return True

    def focusNextPrevChild(self, next=True):
        """Move keyboard focus through the explicit QDialog tab chain."""
        candidates = [item for item in self._focus_order if self._item_is_focusable(item)]
        if self._default_button is not None and self._item_is_focusable(self._default_button):
            if self._default_button not in candidates:
                candidates.append(self._default_button)
        if not candidates:
            return False
        try:
            current = dpg.get_focused_item() or None
        except Exception:
            current = None
        if current in candidates:
            index = candidates.index(current)
            index = (index + (1 if next else -1)) % len(candidates)
        else:
            index = 0 if next else len(candidates) - 1
        try:
            self.focus_control(candidates[index])
            self._activation_owned = True
            return True
        except Exception:
            return False

    def accept(self):
        """Run the acceptance action independently of keyboard/button focus."""
        if callable(self._default) and self._item_is_focusable(self._default_button):
            self._default()
            return True
        return False

    def reject(self):
        """QDialog-compatible reject action preserving subclass Escape semantics."""
        # Forms with a specialized Escape state machine (combo popup, inline
        # editor, progress cancellation, etc.) remain authoritative.  Plain
        # dialogs mirror QDialogButtonBox and invoke their registered reject
        # button so X/Escape/Cancel share exactly one code path.
        if type(self)._close_from_escape is DialogBase._close_from_escape:
            if callable(self._reject) and self._item_is_focusable(self._reject_button):
                self._reject()
                return
        self._close_from_escape()

    def invoke_default(self):
        # A choice confirmation/dismissal must not also press the dialog's
        # default button when legacy and central keyboard callbacks coexist.
        try:
            frame = int(dpg.get_frame_count())
        except Exception:
            frame = -2
        for wrapper in self._control_wrappers.values():
            if isinstance(wrapper, QComboBox) and (
                    wrapper.popupVisible() or wrapper._choice_popup_closed_frame == frame):
                return
        focused_combo = self.focusWidget()
        if (isinstance(focused_combo, QComboBox) and focused_combo._choice_field is not None
                and not focused_combo.isEditable()):
            focused_combo.showPopup()
            return
        # Multiline editors and result views own Enter; single-line forms use
        # QDialog's default action, with no duplicate on_enter callback.
        if any(self._item_is_focusable(item)
               and (dpg.is_item_focused(item) or dpg.is_item_active(item))
               for item in self.enter_editors):
            return
        # QPushButton::autoDefault semantics: Return activates the focused push
        # button before falling back to the dialog's default button.
        try:
            focused = dpg.get_focused_item()
        except Exception:
            focused = None
        wrapper = self._control_wrappers.get(focused)
        if isinstance(wrapper, QPushButton):
            try:
                if wrapper.isEnabled():
                    wrapper.click()
                    return
            except Exception:
                pass

        # Retained item-view focus may outlive a Tab/programmatic move to a
        # button. Honour the actual focused push button before the view flag.
        table = self.active_table
        if table is not None:
            try:
                if table.hasFocus():
                    table.activateCurrent()
                    return
            except Exception:
                pass

        if not callable(self._default) or self._default_button is None:
            return
        if not self._item_is_focusable(self._default_button):
            return
        self._default()

    def canReuseHost(self):
        """Return whether the native host may be recycled after this lease.

        Forms opt in with ``REUSABLE_HOST`` and may override this method for a
        final dynamic audit (for example, to reject reuse while native or
        non-cooperative background work is still draining).
        """
        return bool(self.REUSABLE_HOST)

    def own_dialog(self, dialog):
        if isinstance(dialog, QObject) and dialog.parent is not self:
            dialog.setParent(self)
        if dialog not in self._owned_dialogs:
            self._owned_dialogs.append(dialog)
        return dialog

    def _qt_parent(self, native_parent):
        if native_parent is None or isinstance(native_parent, QObject):
            return native_parent
        proxy = self._native_parent_owners.get(native_parent)
        if proxy is None or proxy._deleted:
            proxy = QObject(parent=self._widget_owner, after=self.view.after)
            proxy.tag = native_parent
            proxy.backend = get_backend()
            self._native_parent_owners[native_parent] = proxy
        return proxy

    def own_widget(self, widget):
        if isinstance(widget, QPushButton):
            widget._dialog_pointer_routing = True
            self._control_wrappers[widget.tag] = widget
            widget.clicked.connect(self._note_button_activation)
        ancestor = widget.parent
        while ancestor is not None:
            if ancestor is self._widget_owner:
                return widget
            ancestor = ancestor.parent
        widget.setParent(self._widget_owner)
        return widget

    def create_timer(self, milliseconds, callback, *, single_shot=False, start=True):
        """Create an event-loop timer automatically disposed with this dialog."""
        if not self.winfo_exists():
            raise RuntimeError("cannot create a timer for a closed dialog")
        from ..core.timer import QTimer
        timer = QTimer(self._widget_owner)
        try:
            timer.setInterval(milliseconds)
            timer.setSingleShot(single_shot)
            timer.timeout.connect(callback)
            if start:
                timer.start()
        except Exception:
            timer.delete()
            raise
        return timer

    def runAsync(self, callback, *args, on_result=None, on_error=None,
                 on_finished=None, pool=None, **kwargs):
        """Run work on a shared ``QThreadPool`` and marshal completion to this dialog.

        This is the preferred replacement for dialog-local ``threading.Thread``
        workers. The watcher is QObject-owned by the dialog, so closing/recycling
        the form disconnects late worker signals automatically.
        """
        if not self.winfo_exists():
            raise RuntimeError("cannot start background work for a closed dialog")
        from ..core.concurrent import QFutureWatcher, QThreadPool, QtConcurrent
        from ..core.object import QPointer
        future = QtConcurrent.run(
            callback, *args, pool=pool or QThreadPool.globalInstance(), **kwargs)
        self._async_futures.add(future)
        watcher = QFutureWatcher(self._widget_owner)
        dialog_guard = QPointer(self)

        def dialog_alive(callback):
            if not callable(callback):
                return None
            def guarded(*values):
                dialog = dialog_guard.data()
                if (dialog is not None and dialog.winfo_exists()
                        and not dialog._destroy_scheduled):
                    callback(*values)
            return guarded

        result_callback = dialog_alive(on_result)
        error_callback = dialog_alive(on_error)
        finished_callback = dialog_alive(on_finished)
        if result_callback is not None:
            watcher.resultReady.connect(result_callback)
        if error_callback is not None:
            watcher.failed.connect(error_callback)
        if finished_callback is not None:
            watcher.finished.connect(finished_callback)

        def release_future():
            self._async_futures.discard(future)
            watcher.deleteLater()

        watcher.finished.connect(release_future)
        watcher.setFuture(future)
        return future

    run_async = runAsync

    def _restore_embedded_owner_focus(self):
        """Restore focus using Qt parent/activation semantics.

        A nested QDialog returns to its logical parent, never an arbitrary
        visible sibling. A modeless dialog closed in the background is not
        allowed to steal focus. If the logical parent is already gone, fall
        back to the top-most live dialog and finally the launcher/main window.
        """
        if getattr(self.view, "_floating_focus_suppressed", False):
            return
        if not self._restore_focus_on_hide and not self.modal:
            return
        try:
            def visible(dialog):
                return (dialog is not self and dialog.winfo_exists()
                        and dpg.does_item_exist(dialog.tag)
                        and dpg.is_item_shown(dialog.tag))

            # QObject ownership is authoritative for nested QDialog focus.
            parent = self.parent
            while parent is not None and not isinstance(parent, QtDialog):
                parent = getattr(parent, "parent", None)
            if isinstance(parent, QtDialog) and visible(parent):
                target = self._focus_restore_item
                if (self._item_is_focusable(target)
                        and self._item_belongs_to(target, parent.tag)):
                    dpg.focus_item(target)
                else:
                    parent._focus_initial()
                parent._activation_owned = True
                self._restore_focus_on_hide = False
                return

            remaining = [dialog for dialog in tuple(_DIALOGS) if visible(dialog)]
            if remaining:
                fallback_dialog = remaining[-1]
                target = self._focus_restore_item
                if (self._item_is_focusable(target)
                        and self._item_belongs_to(target, fallback_dialog.tag)):
                    dpg.focus_item(target)
                else:
                    fallback_dialog._focus_initial()
                fallback_dialog._activation_owned = True
                self._restore_focus_on_hide = False
                return

            target = self._focus_restore_item
            if self._item_is_focusable(target):
                dpg.focus_item(target)
            else:
                fallback = getattr(self.view, "primary_window_tag", None)
                if callable(fallback):
                    fallback = fallback()
                if fallback is not None and dpg.does_item_exist(fallback):
                    dpg.focus_item(fallback)
        except Exception:
            pass
        finally:
            self._restore_focus_on_hide = False

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

    def _dispose_logical_state(self):
        """Dispose the retained QObject tree after the native surface is gone.

        Qt closes a top-level synchronously from the user's perspective, while
        deferred object deletion is drained by the event loop afterwards.  A
        large DearPyGui form can own hundreds of wrappers/handlers; deleting
        that tree before the HWND is hidden makes Close look frozen.  Keep the
        close path O(1-ish), then perform the expensive ownership teardown only
        after the final visible frame has been removed from the desktop.
        """
        if self._logical_cleanup_done:
            return
        self._logical_cleanup_done = True
        registry = self._resize_registry
        self._resize_registry = None
        control_registries = tuple(self._control_handler_registries)
        self._control_handler_registries.clear()
        self._line_edit_shells.clear()
        self._control_wrappers.clear()
        try:
            if not self._widget_owner._deleted:
                self._widget_owner.delete()
        except Exception:
            # Destruction is best-effort once the native surface has closed.
            # One stale backend item must never prevent host close/idle ACK.
            pass
        try:
            # QObject.delete() recursively disconnects signals/event filters.
            # Run it only after children have been released so a large wrapper
            # tree never delays the native close hand-off.
            if not self._deleted:
                QObject.delete(self)
        except Exception:
            pass
        try:
            if registry and dpg.does_item_exist(registry):
                dpg.delete_item(registry)
        except Exception:
            pass
        for item in control_registries:
            try:
                if item and dpg.does_item_exist(item):
                    dpg.delete_item(item)
            except Exception:
                pass

    def _finalize_visual_destroy(self, *_args, **_kwargs):
        """Delete visual/native items first, then drain deferred QObject state."""
        try:
            super()._finalize_visual_destroy(*_args, **_kwargs)
        finally:
            self._dispose_logical_state()

    def destroy(self):
        if threading.get_ident() != self._ui_thread:
            self.view.after(0, self.destroy)
            return
        if self._destroy_scheduled:
            return
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                # Terminal close must release modal/pointer ownership before
                # the native window disappears.  _clear_widget purges modal,
                # pointer-target, focus and mouse-grab state synchronously.
                application._clear_widget(self)
        except Exception:
            pass
        self._latest_updates.close()
        # Never wait for worker shutdown on the UI thread. Cancellation is
        # cooperative; running work may finish in the pool, but all UI-facing
        # callbacks are owned by this dialog and are discarded after close.
        for future in tuple(self._async_futures):
            try:
                future.cancel()
            except Exception:
                pass
        self._async_futures.clear()
        self._layout_manager = None
        # Child top-levels receive their close request now, but their own heavy
        # QObject teardown is deferred by the same lifecycle rule.
        for child in tuple(self._owned_dialogs):
            child.destroy()
        self._owned_dialogs.clear()
        if self in _DIALOGS:
            _DIALOGS.remove(self)
        if self.modal:
            release_pointer_input()

        try:
            focused_item = dpg.get_focused_item() or None
        except Exception:
            focused_item = None
        self._restore_focus_on_hide = bool(
            self.modal or self._item_belongs_to(focused_item, self.tag)
        )
        native_owner_lease = self._begin_native_owner_close()
        self._activation_owned = False

        self._visible_state = False
        # Do not leave a hidden/deleting dialog in DearUIQt's legacy modal
        # registry for another frame. Explorer/ListView global handlers consult
        # this registry before dispatching any pointer event.
        unregister_modal_window(self.tag)
        unregister_pointer_protected_item(self.tag)
        self._disarm_native_modal_before_hide()

        # This is intentionally before wrapper/QObject destruction. For a
        # process-isolated dialog it marks the form closed immediately so the
        # runtime can SW_HIDE the HWND; for an embedded dialog it queues visual
        # deletion for the next UI turn. _finalize_visual_destroy() performs
        # retained-object cleanup only after that visual transition.
        super().destroy()

        if native_owner_lease is not None:
            self._schedule_native_owner_repair(native_owner_lease)

        # A later dialog show will be detected and blocks this restoration.
        if self._restore_focus_on_hide:
            self.view.after(0, self._restore_embedded_owner_focus)


QDialog = QtDialog


class QtTable(QtDataGridView):
    # The reusable QtDataGridView owns the actual DPG table contract, including
    # freeze_rows=1, alternating rows, QHeaderView-like chrome and row focus.
    """Backward-compatible QTableView wrapper for existing dialog forms.

    New code should use :class:`DearUIQt.QtDataGridView` directly. This
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
        if isinstance(parent, QObject):
            ancestor = parent
            while ancestor is not None:
                if isinstance(ancestor, QtDialog):
                    self.owner = ancestor
                    break
                ancestor = ancestor.parent
        else:
            ancestor = parent
            while ancestor:
                self.owner = next((dialog for dialog in _DIALOGS if dialog.tag == ancestor), None)
                if self.owner is not None:
                    break
                ancestor = dpg.get_item_parent(ancestor)
        if self.owner is not None:
            if self.owner.active_table is None:
                self.owner.active_table = self
            # Raw native parents predate QObject layouts and still need explicit
            # ownership. A QWidget/QLayout parent already owns this view through
            # the QObject tree and must not be flattened back to _widget_owner.
            if not isinstance(parent, QObject):
                self.owner.own_widget(self)

    def _row_clicked(self, sender, value, key):
        if self.owner is not None:
            self.owner.active_table = self
        super()._row_clicked(sender, value, key)
