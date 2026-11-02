"""Explorer-style inline rename textbox for Dear PyGui.

Dear PyGui's ``add_input_text`` does not expose a public API for setting an
arbitrary selection range or caret position.  That makes the exact Windows
Explorer rename gesture (select basename but leave the extension unselected)
impossible to implement with the Dear PyGui widget alone.

``ExplorerRenameTextBox`` hides that limitation behind one reusable control:

* On Windows it prefers a native owned-popup ``EDIT`` hosted above the Dear
  PyGui viewport.  Activation is deliberately deferred by one UI pump so native
  focus is never changed from the callback that requested rename.
* If the native editor is unavailable, it creates a normal Dear PyGui
  ``InputText`` with matching geometry/theme and keeps all lifecycle handling
  in one place.
* The public API is intentionally small: ``begin()``, ``pump()``, ``text()``,
  ``refocus()``, ``contains_mouse()`` and ``close()``.

The class is UI-framework focused only.  It does not rename files itself and
therefore can also be reused for tree nodes, history features, assembly names,
or any other Explorer-like inline label editor.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Optional

from DearUIQt.gui import QFontMetrics
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.widgets import QWidget, QInlineEditPanel
from .native_rename import (
    NativeRenameEditor,
    basename_select_end,
    split_rename_name,
)


@dataclass
class _RenameRequest:
    text: str
    is_directory: bool
    left: float
    top: float
    initial_width: int
    max_width: int
    height: int
    source_text_tag: Any
    font: Any
    editor_fill: tuple
    editor_border: tuple
    text_color: tuple
    selection_color: tuple
    native_hwnd: int
    native_scale: float
    font_px: int
    font_face: str


class ExplorerRenameTextBox:
    """Reusable one-line rename editor with Explorer-compatible semantics.

    The control is *logical* immediately after :meth:`begin` returns, but its
    native/DPG visual editor is created on a later :meth:`pump` call.  This is
    important for Dear PyGui applications that use manual callback management:
    creating a native editor and calling ``SetFocus`` from the callback that
    initiated rename can re-enter the GLFW/ImGui message path and freeze the
    viewport on some builds.
    """

    def __init__(
        self,
        uid: str,
        *,
        bind_font: Optional[Callable[[Any, Any], None]] = None,
        measure_text: Optional[Callable[[str, Any], tuple]] = None,
        native_enabled: bool = True,
        native_factory: Callable[[], NativeRenameEditor] = NativeRenameEditor,
    ):
        self.uid = str(uid)
        self.window_tag = f"{self.uid}_window"
        self.input_tag = f"{self.uid}_input"
        self.extension_input_tag = f"{self.uid}_extension_input"
        self._base_editor_control = None
        self._extension_editor_control = None
        self._fallback_editor = None
        self._source_widget = None
        self.theme_tag = f"{self.uid}_theme"

        self._bind_font = bind_font
        self._measure_text = measure_text
        self._native_enabled = bool(native_enabled)
        self._native_factory = native_factory

        self._active = False
        self._backend = None
        self._request: Optional[_RenameRequest] = None
        self._defer_pumps = 0
        self._focus_retries = 0
        self._native_editor: Optional[NativeRenameEditor] = None
        self._native_reselect_pending = False
        self._native_selection_verify_pumps = 0
        self._native_selection_good_pumps = 0
        self._native_last_text = ""
        self._dpg_extension = ""
        self._source_hidden = False

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return bool(self._active)

    @property
    def backend(self) -> Optional[str]:
        """Return ``'native'``, ``'dpg'`` or ``None`` while pending/inactive."""
        return self._backend

    @property
    def pending(self) -> bool:
        return bool(self._active and self._request is not None and not self._backend)

    def set_native_enabled(self, enabled: bool) -> None:
        self._native_enabled = bool(enabled)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(
        self,
        text: str,
        *,
        is_directory: bool = False,
        left: float,
        top: float,
        initial_width: int,
        max_width: int,
        height: int,
        source_text_tag: Any = None,
        font: Any = None,
        editor_fill=(255, 255, 255, 255),
        editor_border=(0, 120, 215, 255),
        text_color=(0, 0, 0, 255),
        selection_color=(0, 120, 215, 255),
        native_hwnd: int = 0,
        native_scale: float = 1.0,
        font_px: int = 15,
        font_face: str = "Segoe UI",
    ) -> bool:
        """Queue one rename editor.

        Visual creation is deferred until a later :meth:`pump` call.  The old
        label remains visible during that defer interval, so there is no blank
        one-frame flash.
        """
        self.close()

        max_width = max(24, int(round(max_width)))
        initial_width = max(24, min(max_width, int(round(initial_width))))
        height = max(16, int(round(height)))
        scale = float(native_scale or 1.0)
        if scale <= 0.0:
            scale = 1.0

        self._request = _RenameRequest(
            text=str(text or ""),
            is_directory=bool(is_directory),
            left=float(left),
            top=float(top),
            initial_width=initial_width,
            max_width=max_width,
            height=height,
            source_text_tag=source_text_tag,
            font=font,
            editor_fill=tuple(editor_fill),
            editor_border=tuple(editor_border),
            text_color=tuple(text_color),
            selection_color=tuple(selection_color),
            native_hwnd=int(native_hwnd or 0),
            native_scale=scale,
            font_px=max(8, int(round(font_px))),
            font_face=str(font_face or "Segoe UI"),
        )
        self._active = True
        self._backend = None
        # The first pump commonly occurs later in the same update iteration as
        # the callback that requested rename.  Skip it; activation then happens
        # only after at least one complete Dear PyGui frame has been rendered.
        self._defer_pumps = 1
        self._focus_retries = 0
        return True

    def pump(self) -> Optional[str]:
        """Advance deferred activation and return a native key action.

        Return value is ``'commit'``/``'cancel'`` only when the native editor
        consumed Enter/Escape.  Dear PyGui keyboard handlers can continue to
        own those keys for the fallback backend.
        """
        if not self._active:
            return None

        editor = self._native_editor
        if editor is not None and editor.is_active():
            self._stabilize_native_editor(editor)
            self._sync_native_width(editor)
            try:
                return editor.consume_pending()
            except Exception:
                return None

        if self._backend == "dpg":
            self._retry_dpg_focus()
            return None

        request = self._request
        if request is None:
            return None

        if self._defer_pumps > 0:
            self._defer_pumps -= 1
            return None

        if self._try_activate_native(request):
            return None
        self._activate_dpg(request)
        return None

    def close(self) -> None:
        """Destroy the active editor and restore the original label."""
        editor, self._native_editor = self._native_editor, None
        if editor is not None:
            try:
                editor.destroy()
            except Exception:
                pass

        fallback, self._fallback_editor = self._fallback_editor, None
        if fallback is not None:
            try:
                fallback.delete()
            except Exception:
                pass
        self._base_editor_control = None
        self._extension_editor_control = None
        self._restore_source_label()

        self._active = False
        self._backend = None
        self._request = None
        self._defer_pumps = 0
        self._focus_retries = 0
        self._native_reselect_pending = False
        self._native_selection_verify_pumps = 0
        self._native_selection_good_pumps = 0
        self._native_last_text = ""
        self._dpg_extension = ""

    # ------------------------------------------------------------------
    # Editor operations
    # ------------------------------------------------------------------
    def text(self, default: str = "") -> str:
        editor = self._native_editor
        if editor is not None and editor.is_active():
            try:
                return str(editor.get_text())
            except Exception:
                return str(default or "")
        fallback = self._fallback_editor
        if fallback is not None and self._backend == "dpg":
            try:
                return fallback.text()
            except Exception:
                pass
        request = self._request
        return str(request.text if request is not None else default or "")

    def refocus(self) -> bool:
        editor = self._native_editor
        if editor is not None and editor.is_active():
            try:
                return bool(editor.refocus())
            except Exception:
                return False
        if self._backend != "dpg":
            # Pending editor: keep it pending; pump() will focus it when shown.
            return bool(self._active)
        fallback = self._fallback_editor
        if fallback is None:
            return False
        try:
            focused = bool(fallback.refocus())
            if focused:
                self._focus_retries = 4
            return focused
        except Exception:
            return False

    def contains_mouse(self) -> bool:
        """Return whether the mouse is over the Dear PyGui fallback editor.

        Native popup clicks are consumed by Win32 before Dear PyGui's
        global mouse handler runs, so no native rectangle test is needed here.
        """
        if self._backend != "dpg":
            return False
        fallback = self._fallback_editor
        if fallback is None:
            return False
        try:
            return bool(fallback.containsMouse())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Activation backends
    # ------------------------------------------------------------------
    def _try_activate_native(self, request: _RenameRequest) -> bool:
        if (
            not self._native_enabled
            or os.name != "nt"
            or not request.native_hwnd
        ):
            return False

        # Normalize renderer coordinates to the owner's client space first.
        # Multi-viewports use screen coordinates; stock DPG uses client space.
        # Neither path needs another DPI scale.
        editor = self._native_factory()
        select_end = basename_select_end(request.text, request.is_directory)
        try:
            left, top = self._native_position(request)
            ok = editor.begin(
                request.native_hwnd,
                left,
                top,
                max(24, int(round(request.initial_width))),
                max(16, int(round(request.height))),
                request.text,
                select_end,
                max(8, int(round(request.font_px))),
                request.font_face,
            )
        except Exception:
            ok = False
        if not ok:
            try:
                editor.destroy()
            except Exception:
                pass
            return False

        self._native_editor = editor
        self._backend = "native"
        # Verify the initial basename selection for several rendered frames.
        # GLFW can deliver a delayed focus transition after the EDIT was
        # created; on affected systems that transition changes the range back
        # to select-all.  We only repair known focus-generated states, and stop
        # immediately if the user makes a different selection.
        self._native_reselect_pending = True
        self._native_selection_verify_pumps = 8
        self._native_selection_good_pumps = 0
        self._native_last_text = request.text
        self._hide_source_label(request.source_text_tag)
        return True

    def _stabilize_native_editor(self, editor: NativeRenameEditor) -> None:
        """Make the initial basename selection survive delayed focus messages.

        A single delayed ``EM_SETSEL`` is not reliable with a GLFW/Win32
        viewport: a later focus message can still restore the EDIT control's
        select-all state.  For a short startup window we inspect the *actual*
        selection returned by ``EM_GETSEL``.  We repair only focus-generated
        states (select-all or a collapsed edge caret), and stop as soon as the
        expected range is stable or the user has made a different selection.
        """
        if not self._native_reselect_pending:
            return
        if getattr(editor, "_selection_interacted", False) is True:
            # Arrow/mouse input is intentional, including a caret collapsed
            # exactly at the basename end. Never restore selection over it.
            self._native_reselect_pending = False
            return
        request = self._request
        if request is None:
            self._native_reselect_pending = False
            return

        try:
            value = str(editor.get_text())
            if value != str(request.text):
                # Typing already started; never fight the user's caret.
                self._native_reselect_pending = False
                return

            expected_end = basename_select_end(
                request.text, request.is_directory)
            expected = (0, expected_end)
            total = len(str(request.text).encode("utf-16-le")) // 2
            actual = editor.get_selection()

            if actual == expected:
                self._native_selection_good_pumps += 1
                # Two consecutive rendered frames are enough to prove that
                # delayed GLFW focus handling is finished.
                if self._native_selection_good_pumps >= 2:
                    self._native_reselect_pending = False
                return

            self._native_selection_good_pumps = 0
            self._native_selection_verify_pumps -= 1
            if self._native_selection_verify_pumps <= 0:
                self._native_reselect_pending = False
                return

            # States commonly produced by EDIT focus transitions.  Anything
            # else is treated as an intentional mouse/keyboard selection.
            repairable = {
                (0, total),          # select-all
                (0, 0),              # caret at start
                (total, total),      # caret at end
                (expected_end, expected_end),
            }
            if actual in repairable or actual is None:
                editor.set_selection(*expected)
            else:
                self._native_reselect_pending = False
        except Exception:
            self._native_reselect_pending = False

    @staticmethod
    def _native_position(request):
        """Translate renderer coordinates into the EDIT owner's client space.

        Stock DPG reports viewport-client coordinates. ImGui multi-viewports
        report desktop coordinates instead. NativeRenameEditor always expects
        client coordinates (it converts its popup position with ClientToScreen).
        Keep the original renderer coordinates for the DPG fallback.
        """
        left, top = int(round(request.left)), int(round(request.top))
        if os.name == "nt" and NativeWindowBackend().isEnabled():
            import ctypes
            from ctypes import wintypes
            point = wintypes.POINT(left, top)
            user32 = ctypes.windll.user32
            user32.ScreenToClient.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user32.ScreenToClient.restype = wintypes.BOOL
            if not user32.ScreenToClient(
                    wintypes.HWND(request.native_hwnd), ctypes.byref(point)):
                raise OSError("Cannot map rename editor to its owner window")
            return int(point.x), int(point.y)
        return left, top

    def _sync_native_width(self, editor: NativeRenameEditor) -> None:
        """Keep native edit width tight to the label, Explorer-style."""
        request = self._request
        if request is None:
            return
        try:
            value = str(editor.get_text())
        except Exception:
            return
        if value == self._native_last_text:
            return
        self._native_last_text = value
        width = self._measure(value or " ", request.font)
        width = max(24, min(request.max_width, int(round(width + 10.0))))
        try:
            left, top = self._native_position(request)
            editor.set_bounds(
                left,
                top,
                width,
                max(16, int(round(request.height))),
            )
        except Exception:
            pass

    def _activate_dpg(self, request: _RenameRequest) -> None:
        """Build the portable fallback through DearUIQt's inline editor."""
        self._delete_stale_dpg_items()
        base, extension = split_rename_name(request.text, request.is_directory)
        self._dpg_extension = extension
        editor = QInlineEditPanel(
            base, extension,
            position=(int(round(request.left)), int(round(request.top))),
            max_width=request.max_width, height=request.height, font=request.font,
            text_color=request.text_color, selection_color=request.selection_color,
            source_item=request.source_text_tag, callback=self._on_dpg_edited,
            tag=self.window_tag, input_tag=self.input_tag,
            suffix_tag=self.extension_input_tag, measure=self._measure_text,
            font_binder=self._bind_font,
        )
        self._fallback_editor = editor
        self._base_editor_control = editor.baseEditor
        self._extension_editor_control = editor.suffixEditor
        self._backend = "dpg"
        # QInlineEditPanel owns source-label visibility and pointer protection.
        self._source_hidden = False
        self._focus_retries = 4

    def _delete_stale_dpg_items(self) -> None:
        editor, self._fallback_editor = self._fallback_editor, None
        if editor is not None:
            try:
                editor.delete()
            except Exception:
                pass
        self._base_editor_control = None
        self._extension_editor_control = None

    # ------------------------------------------------------------------
    # DPG fallback behavior
    # ------------------------------------------------------------------
    def _on_dpg_edited(self, sender=None, app_data=None, user_data=None) -> None:
        if not self._active or self._backend != "dpg":
            return
        editor = self._fallback_editor
        if editor is not None:
            try:
                editor.resizeToContents()
            except Exception:
                pass

    def _measure(self, text: str, font: Any) -> float:
        if callable(self._measure_text):
            try:
                result = self._measure_text(text, font)
                return float(result[0] if isinstance(result, (tuple, list)) else result)
            except Exception:
                pass
        try:
            return float(QFontMetrics(font).horizontalAdvance(text))
        except Exception:
            return float(max(16, len(text) * 8))

    def _retry_dpg_focus(self) -> None:
        if self._focus_retries <= 0:
            return
        self._focus_retries -= 1
        editor = self._fallback_editor
        if editor is not None:
            try:
                editor.refocus()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Source-label visibility
    # ------------------------------------------------------------------
    def _hide_source_label(self, tag: Any) -> None:
        self._source_hidden = False
        self._source_widget = None
        if not tag:
            return
        try:
            widget = QWidget(tag)
            if widget.exists():
                widget.hide()
                self._source_widget = widget
                self._source_hidden = True
        except Exception:
            self._source_hidden = False
            self._source_widget = None

    def _restore_source_label(self) -> None:
        widget, self._source_widget = self._source_widget, None
        if self._source_hidden and widget is not None:
            try:
                if widget.exists():
                    widget.show()
            except Exception:
                pass
        self._source_hidden = False
