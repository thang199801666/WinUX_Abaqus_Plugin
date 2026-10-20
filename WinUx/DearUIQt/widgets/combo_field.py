"""Native button-backed combo field with a separate Qt-style arrow subcontrol."""
from ..core import QItemInputBinding, Qt
from ..gui.palette import QtFusionPalette
from ..gui.style import METRICS


class ComboField:
    def __init__(self, backend, parent, width, text, open_popup, focus_received,
                 *, editable=False, text_changed=None):
        self.backend = b = backend
        self._open = open_popup
        self._focus_received = focus_received
        self._text = text
        self.editable = bool(editable)
        self._text_changed = text_changed
        self._width = 0
        self._enabled = True
        self._popup_visible = False
        self._deleted = False
        self._refresh_signature = None
        self._themes = {}
        self._bindings = []
        self.height = METRICS.control_height
        self.tag = b.add_child_window(parent=parent or 0, width=width, height=self.height,
                                      border=True, no_scrollbar=True, no_scroll_with_mouse=True)
        self.button = b.add_button(parent=self.tag, label=text, pos=(1, 1), width=-2,
                                   height=self.height - 2, callback=self._clicked)
        # An editable preview must never share its mouse hit area with a
        # full-field drawlist. Give the arrow its own narrow child viewport.
        self._arrow_host = (b.add_child_window(
            parent=self.tag, width=METRICS.arrow_width, height=self.height - 2,
            pos=(1, 1), border=False, no_scrollbar=True, no_scroll_with_mouse=True)
            if self.editable else None)
        self.arrow = b.add_drawlist(parent=self._arrow_host or self.tag, width=1,
                                    height=self.height - 2,
                                    pos=(0, 0) if self.editable else (1, 1))
        self._arrow_bg = b.draw_rectangle((0, 0), (METRICS.arrow_width, self.height - 2),
                                          parent=self.arrow, fill=QtFusionPalette.BASE,
                                          color=(0, 0, 0, 0))
        self._separator = b.draw_line((0, 0), (0, self.height - 2), parent=self.arrow,
                                      color=QtFusionPalette.BORDER_LIGHT)
        cx, cy = METRICS.arrow_width / 2, (self.height - 2) / 2
        self._chevron = b.draw_triangle(
            (cx - 3.5, cy - 1.5), (cx + 3.5, cy - 1.5), (cx, cy + 2.5),
            parent=self.arrow, color=QtFusionPalette.TEXT, fill=QtFusionPalette.TEXT)
        if self.editable:
            # Submit the editor after the arrow canvas so typing/selection in
            # the preview stays native; only the uncovered arrow opens history.
            b.delete_item(self.button)
            self.button = b.add_input_text(
                parent=self.tag, default_value=text, pos=(1, 1), width=1,
                height=self.height - 2, callback=self._edited, on_enter=False,
                readonly=False, auto_select_all=False)
        self._bindings.append(QItemInputBinding(self.arrow, backend=b).onClick(Qt.LeftButton, self._clicked)
                              .onVisible(self._refresh).activate())
        self._bindings.append(QItemInputBinding(self.button, backend=b).onFocus(self._focused)
                              .onActivated(self._refresh).onDeactivated(self._refresh).activate())
        self._bindings.append(QItemInputBinding(self.tag, backend=b).onResize(self.syncGeometry).activate())
        self.syncGeometry()
        self._refresh()

    def _theme(self, disabled=False, focused=False, hovered=False):
        key = disabled, focused, hovered, self._popup_visible
        if key in self._themes:
            return self._themes[key]
        b, p = self.backend, QtFusionPalette
        base = self._surface(disabled, focused, hovered)
        with b.theme() as theme:
            with b.theme_component(b.mvAll):
                b.add_theme_color(b.mvThemeCol_ChildBg, base)
                border = (p.BORDER_LIGHT if disabled else p.FOCUS if focused else
                          p.BORDER_DARK if hovered else p.BORDER)
                b.add_theme_color(b.mvThemeCol_Border, border)
                # Do not inherit the application border shadow. Rounded child
                # borders blend it into the corners, making the outline hazy.
                b.add_theme_color(b.mvThemeCol_BorderShadow, (0, 0, 0, 0))
                b.add_theme_style(b.mvStyleVar_WindowPadding, 0, 0)
                b.add_theme_style(b.mvStyleVar_ItemSpacing, 0, 0)
                b.add_theme_style(b.mvStyleVar_ChildRounding, 0)
                b.add_theme_style(b.mvStyleVar_ChildBorderSize, 1)
            with b.theme_component(b.mvButton, enabled_state=not disabled):
                b.add_theme_color(b.mvThemeCol_Button, base)
                b.add_theme_color(b.mvThemeCol_ButtonHovered, base)
                b.add_theme_color(b.mvThemeCol_ButtonActive, base)
                b.add_theme_color(b.mvThemeCol_Text, p.TEXT_DISABLED if disabled else p.TEXT)
                b.add_theme_style(b.mvStyleVar_ButtonTextAlign, 0, 0.5)
                b.add_theme_style(b.mvStyleVar_FramePadding, 7, 0)
                b.add_theme_style(b.mvStyleVar_FrameRounding, 0)
                b.add_theme_style(b.mvStyleVar_FrameBorderSize, 0)
            if self.editable:
                with b.theme_component(b.mvInputText, enabled_state=not disabled):
                    for role in (b.mvThemeCol_FrameBg, b.mvThemeCol_FrameBgHovered, b.mvThemeCol_FrameBgActive):
                        b.add_theme_color(role, base)
                    b.add_theme_color(b.mvThemeCol_Text, p.TEXT_DISABLED if disabled else p.TEXT)
                    b.add_theme_color(b.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
                    b.add_theme_color(b.mvThemeCol_TextSelectedBg, p.SELECTION_ACTIVE)
                    cursor_role = getattr(b, "mvThemeCol_InputTextCursor", None)
                    if cursor_role is not None:
                        b.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
                    b.add_theme_style(b.mvStyleVar_FramePadding, 7, METRICS.combo_editor_frame_pad_y)
                    b.add_theme_style(b.mvStyleVar_FrameBorderSize, 0)
                    b.add_theme_style(b.mvStyleVar_FrameRounding, 0)
        self._themes[key] = theme
        return theme

    def _surface(self, disabled=False, focused=False, hovered=False):
        p = QtFusionPalette
        if disabled:
            return p.BUTTON_DISABLED
        if self.editable:
            return p.BASE
        # Fusion's fixed-choice combo is a button, not a white line editor.
        # Focus changes the outline only; hover/press use quiet neutral fills.
        return ((225, 225, 225, 255) if self._popup_visible else
                (248, 248, 248, 255) if hovered else p.BUTTON)

    def _clicked(self, *_args):
        if self._enabled and not self._deleted:
            self.focus()
            self._open()

    def _edited(self, sender=None, value=None, user_data=None):
        if not self._deleted and self._enabled and callable(self._text_changed):
            self._text = str(value or "")
            self._text_changed(sender, str(value or ""), user_data)

    def _focused(self, *_args):
        if self._deleted:
            return
        self._focus_received()
        self._refresh()

    def _item_exists(self, item):
        if self._deleted or item is None:
            return False
        try:
            return bool(self.backend.does_item_exist(item))
        except Exception:
            return False

    def _item_state(self, item):
        # Item-handler callbacks can already be queued when a dialog/popup begins
        # teardown.  Dear PyGui raises Error 1005 if get_item_state() receives
        # such a stale id, so never query state until ownership is still live.
        if not self._item_exists(item):
            return {}
        try:
            return self.backend.get_item_state(item) or {}
        except Exception:
            return {}

    def hasFocus(self):
        state = self._item_state(self.button)
        return bool(state.get("focused") or state.get("active"))

    def _refresh(self, *_args):
        if self._deleted or not self._item_exists(self.tag) or not self._item_exists(self.button):
            return
        b, p = self.backend, QtFusionPalette
        editor_state = self._item_state(self.button)
        focused = bool(editor_state.get("focused") or editor_state.get("active") or self._popup_visible)
        arrow_hovered = bool(self._item_state(self.arrow).get("hovered", False))
        hovered = arrow_hovered or bool(editor_state.get("hovered", False))
        signature = self._enabled, focused, hovered, arrow_hovered, self._popup_visible
        if signature == self._refresh_signature:
            return
        self._refresh_signature = signature
        try:
            theme = self._theme(not self._enabled, focused, hovered)
            for item in (self.tag, self.button, self._arrow_host):
                if self._item_exists(item):
                    b.bind_item_theme(item, theme)
            arrow_fill = (self._surface(not self._enabled, focused, hovered)
                          if not self.editable else
                          (225, 225, 225, 255) if self._popup_visible else
                          (248, 248, 248, 255) if arrow_hovered else p.BUTTON)
            if self._item_exists(self._arrow_bg):
                b.configure_item(self._arrow_bg, fill=arrow_fill if self._enabled else p.BUTTON_DISABLED)
            if self._item_exists(self._separator):
                b.configure_item(self._separator, color=(p.BORDER if self.editable else (0, 0, 0, 0)))
            if self._item_exists(self._chevron):
                ink = p.TEXT if self._enabled else p.TEXT_DISABLED
                b.configure_item(self._chevron, color=ink, fill=ink)
        except Exception:
            # A late visible/focus callback must be a no-op once any native
            # subcontrol disappears; never let it escape into WinUx's error UI.
            return

    def setPopupVisible(self, visible):
        self._popup_visible = bool(visible)
        self._refresh()

    def focus(self):
        if self._deleted or not self._enabled or not self._item_exists(self.button):
            return
        try:
            self.backend.focus_item(self.button)
        except Exception:
            return
        self._focus_received()

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)
        if self._item_exists(self.button):
            try:
                self.backend.configure_item(self.button, enabled=self._enabled)
            except Exception:
                pass
        self._refresh()

    def setText(self, text):
        self._text = str(text)
        if self.editable:
            if self._item_exists(self.button):
                try:
                    self.backend.set_value(self.button, self._text)
                except Exception:
                    pass
            return
        available = max(1, self._width - METRICS.arrow_width - 14)
        label = self._text
        try:
            measure = self.backend.get_text_size
            if measure(label)[0] > available:
                lo, hi = 0, len(label)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if measure(label[:mid] + "…")[0] <= available:
                        lo = mid
                    else:
                        hi = mid - 1
                label = label[:lo] + "…"
        except Exception:
            pass
        self.backend.configure_item(self.button, label=label)

    def syncGeometry(self, *_args):
        if self._deleted or not self._item_exists(self.tag):
            return
        b = self.backend
        try:
            width, height = map(int, b.get_item_rect_size(self.tag))
        except Exception:
            width, height = 0, self.height
        if width <= 0:
            width = max(24, int(b.get_item_configuration(self.tag).get("width", 120)))
        height = max(18, height if height > 0 else self.height)
        if self._width == width and self.height == height:
            return
        self._width, self.height = width, height
        if self.editable:
            b.configure_item(
                self.button,
                width=max(1, width - METRICS.arrow_width - 2),
                height=max(1, height - 2),
            )
            b.configure_item(self._arrow_host, pos=(width - METRICS.arrow_width - 1, 1),
                             width=METRICS.arrow_width, height=height - 2)
        else:
            b.configure_item(self.button, height=height - 2)
        # Keep one field-sized overlay at a stable origin. Some renderer builds
        # retain a drawlist's original draw origin after configure_item(pos=...).
        # Position the arrow primitives themselves, not the drawlist viewport.
        overlay_width = METRICS.arrow_width if self.editable else max(1, width - 2)
        b.configure_item(self.arrow, width=overlay_width, height=height - 2)
        arrow_x = max(0, overlay_width - METRICS.arrow_width)
        b.configure_item(self._arrow_bg, pmin=(arrow_x, 0), pmax=(overlay_width, height - 2))
        b.configure_item(self._separator, p1=(arrow_x, 0), p2=(arrow_x, height - 2))
        cx, cy = arrow_x + METRICS.arrow_width / 2, (height - 2) / 2
        b.configure_item(self._chevron, p1=(cx - 3.5, cy - 1.5),
                         p2=(cx + 3.5, cy - 1.5), p3=(cx, cy + 2.5))
        if not self.editable:
            self.setText(self._text)

    def delete(self):
        if self._deleted:
            return
        self._deleted = True
        for binding in self._bindings:
            binding.delete()
        for theme in self._themes.values():
            if self.backend.does_item_exist(theme):
                self.backend.delete_item(theme)
