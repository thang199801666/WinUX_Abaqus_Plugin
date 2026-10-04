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

import dearpygui.dearpygui as dpg

from .interaction_gate import (
    register_pointer_protected_item,
    unregister_pointer_protected_item,
)
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
        unregister_pointer_protected_item(self.window_tag)
        editor, self._native_editor = self._native_editor, None
        if editor is not None:
            try:
                editor.destroy()
            except Exception:
                pass

        self._restore_source_label()

        for tag in (self.window_tag, self.input_tag, self.extension_input_tag):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass
        try:
            if dpg.does_item_exist(self.theme_tag):
                dpg.delete_item(self.theme_tag)
        except Exception:
            pass

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
        try:
            if dpg.does_item_exist(self.input_tag):
                base = str(dpg.get_value(self.input_tag))
                extension = ""
                if dpg.does_item_exist(self.extension_input_tag):
                    extension = str(dpg.get_value(self.extension_input_tag))
                elif self._backend == "dpg":
                    extension = str(self._dpg_extension or "")
                return base + extension
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
        try:
            if not dpg.does_item_exist(self.input_tag):
                return False
            dpg.focus_item(self.input_tag)
            self._focus_retries = 4
            return True
        except Exception:
            return False

    def contains_mouse(self) -> bool:
        """Return whether the mouse is over the Dear PyGui fallback editor.

        Native popup clicks are consumed by Win32 before Dear PyGui's
        global mouse handler runs, so no native rectangle test is needed here.
        """
        if self._backend != "dpg":
            return False
        try:
            return bool(
                dpg.does_item_exist(self.window_tag)
                and dpg.is_item_hovered(self.window_tag)
            )
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

        # Coordinates are supplied in DPG viewport-client space.  The native
        # editor converts them to screen space for its owned popup.  Do not
        # apply a second DPI scale here; that would shrink/offset the editor.
        editor = self._native_factory()
        select_end = basename_select_end(request.text, request.is_directory)
        try:
            ok = editor.begin(
                request.native_hwnd,
                int(round(request.left)),
                int(round(request.top)),
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
            editor.set_bounds(
                int(round(request.left)),
                int(round(request.top)),
                width,
                max(16, int(round(request.height))),
            )
        except Exception:
            pass

    def _activate_dpg(self, request: _RenameRequest) -> None:
        """Build an Explorer-like Dear PyGui editor as the portable fallback.

        Dear ImGui cannot expose a basename-only selection range through
        Dear PyGui.  Instead the fallback uses two borderless InputText fields
        inside one white, one-pixel bordered editor: the basename field is
        focused with auto-select-all, while the extension field remains
        unselected.  The combined value is still returned as one filename.
        """
        self._delete_stale_dpg_items()
        self._build_theme(request)

        base, extension = split_rename_name(
            request.text, request.is_directory)
        self._dpg_extension = extension

        base_width = max(12, int(round(self._measure(base or " ", request.font) + 4.0)))
        ext_width = (
            max(8, int(round(self._measure(extension, request.font) + 4.0)))
            if extension else 0
        )
        total_width = max(24, min(
            request.max_width, base_width + ext_width + 4))
        if base_width + ext_width + 4 > total_width:
            base_width = max(12, total_width - ext_width - 4)

        with dpg.window(
            tag=self.window_tag,
            pos=(int(round(request.left)), int(round(request.top))),
            width=total_width,
            height=request.height,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_collapse=True,
            no_saved_settings=True,
            no_background=False,
            modal=False,
            show=True,
        ):
            dpg.add_input_text(
                tag=self.input_tag,
                default_value=base,
                width=base_width,
                pos=(2, 0),
                auto_select_all=True,
                callback=self._on_dpg_edited,
            )
            if extension:
                dpg.add_input_text(
                    tag=self.extension_input_tag,
                    default_value=extension,
                    width=ext_width,
                    pos=(2 + base_width, 0),
                    auto_select_all=False,
                    callback=self._on_dpg_edited,
                )

        register_pointer_protected_item(self.window_tag)
        dpg.bind_item_theme(self.window_tag, self.theme_tag)
        dpg.bind_item_theme(self.input_tag, self.theme_tag)
        if extension and dpg.does_item_exist(self.extension_input_tag):
            dpg.bind_item_theme(self.extension_input_tag, self.theme_tag)

        if callable(self._bind_font) and request.font is not None:
            for tag in (self.input_tag, self.extension_input_tag):
                try:
                    if dpg.does_item_exist(tag):
                        self._bind_font(tag, request.font)
                except Exception:
                    pass

        self._backend = "dpg"
        self._hide_source_label(request.source_text_tag)
        self._focus_retries = 4
        try:
            dpg.focus_item(self.input_tag)
        except Exception:
            pass

    def _build_theme(self, request: _RenameRequest) -> None:
        # Match the native Explorer label editor instead of the application's
        # general rounded/blue input styling.
        border = (72, 72, 72, 255)
        with dpg.theme(tag=self.theme_tag):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (255, 255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (255, 255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (255, 255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (255, 255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (255, 255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, request.text_color)
                dpg.add_theme_color(
                    dpg.mvThemeCol_TextSelectedBg, request.selection_color)
                dpg.add_theme_color(dpg.mvThemeCol_Border, border)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 1, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)

            input_component = getattr(dpg, "mvInputText", None)
            if input_component is not None:
                with dpg.theme_component(input_component):
                    options = {}
                    core_category = getattr(dpg, "mvThemeCat_Core", None)
                    if core_category is not None:
                        options["category"] = core_category
                    dpg.add_theme_color(
                        dpg.mvThemeCol_FrameBg, (255, 255, 255, 255), **options)
                    dpg.add_theme_color(
                        dpg.mvThemeCol_FrameBgHovered, (255, 255, 255, 255), **options)
                    dpg.add_theme_color(
                        dpg.mvThemeCol_FrameBgActive, (255, 255, 255, 255), **options)
                    dpg.add_theme_color(
                        dpg.mvThemeCol_Text, request.text_color, **options)
                    dpg.add_theme_color(
                        dpg.mvThemeCol_TextSelectedBg,
                        request.selection_color,
                        **options,
                    )
                    dpg.add_theme_style(
                        dpg.mvStyleVar_FrameBorderSize, 0, **options)
                    dpg.add_theme_style(
                        dpg.mvStyleVar_FrameRounding, 0, **options)

    def _delete_stale_dpg_items(self) -> None:
        unregister_pointer_protected_item(self.window_tag)
        for tag in (self.window_tag, self.input_tag, self.extension_input_tag, self.theme_tag):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DPG fallback behavior
    # ------------------------------------------------------------------
    def _on_dpg_edited(self, sender=None, app_data=None, user_data=None) -> None:
        request = self._request
        if not self._active or self._backend != "dpg" or request is None:
            return
        try:
            base = (str(dpg.get_value(self.input_tag))
                    if dpg.does_item_exist(self.input_tag) else "")
            extension = (str(dpg.get_value(self.extension_input_tag))
                         if dpg.does_item_exist(self.extension_input_tag) else "")
        except Exception:
            return

        base_width = max(12, int(round(self._measure(base or " ", request.font) + 4.0)))
        ext_width = (
            max(8, int(round(self._measure(extension, request.font) + 4.0)))
            if extension else 0
        )
        total_width = max(24, min(
            request.max_width, base_width + ext_width + 4))
        if base_width + ext_width + 4 > total_width:
            available = max(12, total_width - 4)
            if extension:
                ext_width = min(ext_width, max(8, available // 2))
            base_width = max(12, available - ext_width)

        try:
            if dpg.does_item_exist(self.input_tag):
                dpg.configure_item(self.input_tag, width=base_width, pos=(2, 0))
            if dpg.does_item_exist(self.extension_input_tag):
                dpg.configure_item(
                    self.extension_input_tag,
                    width=ext_width,
                    pos=(2 + base_width, 0),
                )
            if dpg.does_item_exist(self.window_tag):
                dpg.configure_item(self.window_tag, width=total_width)
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
            width, _height = dpg.get_text_size(text, font=font)
            return float(width)
        except Exception:
            try:
                width, _height = dpg.get_text_size(text)
                return float(width)
            except Exception:
                return float(max(16, len(text) * 8))

    def _retry_dpg_focus(self) -> None:
        if self._focus_retries <= 0:
            return
        self._focus_retries -= 1
        try:
            if dpg.does_item_exist(self.input_tag):
                dpg.focus_item(self.input_tag)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Source-label visibility
    # ------------------------------------------------------------------
    def _hide_source_label(self, tag: Any) -> None:
        self._source_hidden = False
        if not tag:
            return
        try:
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)
                self._source_hidden = True
        except Exception:
            self._source_hidden = False

    def _restore_source_label(self) -> None:
        request = self._request
        if not self._source_hidden or request is None or not request.source_text_tag:
            self._source_hidden = False
            return
        try:
            if dpg.does_item_exist(request.source_text_tag):
                dpg.configure_item(request.source_text_tag, show=True)
        except Exception:
            pass
        self._source_hidden = False
