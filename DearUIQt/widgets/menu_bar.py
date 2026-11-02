"""Qt-like application menu bar backed by :class:`QMenu` popups.

Unlike Dear PyGui's native ``menu_bar/menu`` pair, this wrapper keeps popup
input ownership inside DearUIQt.  That is important for applications which
have geometry-polled/global pointer handlers: when a menu is open, the shared
QMenu popup ownership prevents those handlers from receiving hover/click
through the popup without introducing a viewport-sized visual blocker.
"""
from __future__ import annotations

from ..core.object import QObject
from .menu import QMenu
from ..gui.palette import QtFusionMetrics, QtFusionPalette


_MENU_BAR_THEME_TAG = "dearuiqt.qt.menubar.buttons.rev1"
_MENU_BAR_ACTIVE_THEME_TAG = "dearuiqt.qt.menubar.buttons.active.rev1"


def _theme(backend, *, active=False):
    tag = _MENU_BAR_ACTIVE_THEME_TAG if active else _MENU_BAR_THEME_TAG
    try:
        if backend.does_item_exist(tag):
            return tag
    except Exception:
        pass
    p = QtFusionPalette
    with backend.theme(tag=tag):
        with backend.theme_component(backend.mvButton):
            base = p.HIGHLIGHT_SOFT if active else p.TOOLBAR
            backend.add_theme_color(backend.mvThemeCol_Button, base)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, p.HIGHLIGHT_SOFT)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 6, 2)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
    return tag


class QMenuBar(QObject):
    """Small QMenuBar-style wrapper using retained :class:`QMenu` popups.

    Menus switch on hover while one root menu is already open, matching the
    desktop QMenuBar interaction model.  QApplication popup ownership keeps the
    menu bar switchable while background/global pointer handlers are excluded
    until the popup closes.
    """

    def __init__(self, parent=None, *, backend=None, after=None, height=20):
        super().__init__(parent, after=after)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.height = max(18, int(height))
        self._menus = []
        self._buttons = {}
        self._handlers = []
        self._active_menu = None
        self._active_button = None
        options = {}
        native_parent = getattr(parent, "tag", None)
        if native_parent is not None:
            options["parent"] = native_parent
        self.tag = backend.add_group(horizontal=True, horizontal_spacing=0, **options)

    def addMenu(self, title, menu_or_actions=()):
        if isinstance(menu_or_actions, QMenu):
            menu = menu_or_actions
        else:
            menu = QMenu(menu_or_actions, backend=self.backend, after=self._after)
        button = self.backend.add_button(
            label=str(title), parent=self.tag, height=self.height,
            callback=self._button_clicked, user_data=menu,
        )
        try:
            self.backend.bind_item_theme(button, _theme(self.backend, active=False))
        except Exception:
            pass
        try:
            with self.backend.item_handler_registry() as registry:
                self.backend.add_item_hover_handler(
                    callback=self._button_hovered, user_data=menu)
            self.backend.bind_item_handler_registry(button, registry)
            self._handlers.append(registry)
        except Exception:
            pass
        menu.aboutToHide.connect(
            lambda _context=None, root=menu: self._menu_hidden(root),
            receiver=self,
        )
        self._menus.append(menu)
        self._buttons[menu] = button
        return menu

    def menus(self):
        return tuple(self._menus)

    def _menu_is_shown(self, menu):
        try:
            return bool(self.backend.is_item_shown(menu.tag))
        except Exception:
            return False

    def _set_button_active(self, button, active):
        if button is None:
            return
        try:
            if self.backend.does_item_exist(button):
                self.backend.bind_item_theme(button, _theme(self.backend, active=bool(active)))
        except Exception:
            pass

    def _button_anchor_rect(self, button):
        """Return a stable renderer-space rectangle for a menu-bar button.

        Dear PyGui can transiently report a stale ``rect_min`` for a sibling
        button while a popup window is taking/releasing focus.  In practice the
        stale value is often the first menu item's x-coordinate, which makes a
        later menu (for example ``View``) open at the far-left edge of the menu
        bar.  The bar itself is a zero-spacing horizontal group, so its button
        positions are deterministic from the first button plus the rendered
        widths of the preceding siblings.  Reconstructing the anchor this way
        avoids depending on the volatile per-button ``rect_min``.
        """
        try:
            width, height = self.backend.get_item_rect_size(button)
            width = float(width)
            height = float(height)
            if width <= 0.0 or height <= 0.0:
                raise ValueError("menu button has no rendered geometry")

            ordered_buttons = [
                self._buttons.get(menu) for menu in self._menus
                if self._buttons.get(menu) is not None
            ]
            if button not in ordered_buttons:
                raise ValueError("menu button is not owned by this menu bar")

            first = ordered_buttons[0]
            try:
                origin_x, origin_y = self.backend.get_item_rect_min(first)
                origin_x = float(origin_x)
                origin_y = float(origin_y)
            except Exception:
                origin_x, origin_y = self.backend.get_item_rect_min(self.tag)
                origin_x = float(origin_x)
                origin_y = float(origin_y)

            x = origin_x
            for sibling in ordered_buttons:
                sibling_width, sibling_height = self.backend.get_item_rect_size(sibling)
                sibling_width = float(sibling_width)
                sibling_height = float(sibling_height)
                if sibling is button or sibling == button:
                    return x, origin_y, width, max(height, sibling_height)
                if sibling_width > 0.0:
                    x += sibling_width
        except Exception:
            pass

        # Compatibility fallback for minimal/test backends and unusual custom
        # layouts.  This is intentionally second choice because the direct
        # rect is the value that can become stale during popup focus changes.
        try:
            x, y = self.backend.get_item_rect_min(button)
            width, height = self.backend.get_item_rect_size(button)
            return float(x), float(y), float(width), float(height)
        except Exception:
            return None

    def _button_anchor_screen_rect(self, rect):
        """Map the anchor through its owner, including programmatic opens."""
        x, y, width, height = map(float, rect)
        try:
            from ..gui.placement import item_screen_rect
            first = next(self._buttons[menu] for menu in self._menus
                         if self._buttons.get(menu) is not None)
            sx, sy, _right, _bottom = item_screen_rect(self.backend, first)
            rx, ry = self.backend.get_item_rect_min(first)
            return x + sx - rx, y + sy - ry, width, height
        except Exception:
            pass
        return x, y, width, height

    def _button_clicked(self, sender=None, app_data=None, user_data=None):
        menu = user_data
        if menu is self._active_menu and self._menu_is_shown(menu):
            menu.hide(consume_pointer=True)
            return
        self._open_menu(menu)

    def _button_hovered(self, sender=None, app_data=None, user_data=None):
        # Qt switches top-level roots on hover only after menu navigation has
        # started.  Plain hover with no open popup must remain passive.
        menu = user_data
        if self._active_menu is None or menu is self._active_menu:
            return
        # Item-hover callbacks are queued. A native popup/focus change can
        # leave stale callbacks for a previously hovered sibling in the queue;
        # only switch to the button physically under the cursor now.
        button = self._buttons.get(menu)
        rect = self._button_anchor_rect(button) if button is not None else None
        if rect is None:
            return
        from ..gui.system import QCursor
        x, y, width, height = self._button_anchor_screen_rect(rect)
        point = QCursor.screenPos(backend=self.backend)
        if not (x <= point.x() < x + width and y <= point.y() < y + height):
            return
        if self._menu_is_shown(self._active_menu):
            self._open_menu(menu)

    def _open_menu(self, menu):
        button = self._buttons.get(menu)
        if button is None:
            return False
        if menu is self._active_menu and self._menu_is_shown(menu):
            return True
        old_menu = self._active_menu
        old_button = self._active_button
        if old_menu is not None and old_menu is not menu:
            old_menu.hide(consume_pointer=False)
            self._set_button_active(old_button, False)
        try:
            rect = self._button_anchor_rect(button)
            if rect is None:
                raise RuntimeError("menu button geometry is unavailable")
            x, y, _width, height = rect
            popup_y = float(y) + float(height)
            # Top-level popup windows on the Windows multi-viewport backend use
            # desktop coordinates.  Convert the renderer/client-space button
            # anchor once and keep the whole popup tree in global space.
            gx, gy, _gwidth, gheight = self._button_anchor_screen_rect(rect)
            global_popup_y = float(gy) + float(gheight)
            popup_below = getattr(menu, "popupBelow", None)
            popup_global = getattr(menu, "popupGlobal", None)
            if callable(popup_below):
                def anchor():
                    from ..gui.placement import visible_item_screen_rect
                    if visible_item_screen_rect(self.backend, button) is None:
                        return None
                    current = self._button_anchor_rect(button)
                    if current is None:
                        return None
                    ax, ay, aw, ah = self._button_anchor_screen_rect(current)
                    return ax, ay, ax + aw, ay + ah
                shown = bool(popup_below(
                    (gx, gy, gx + _gwidth, global_popup_y), anchor_provider=anchor))
            elif callable(popup_global):
                shown = bool(popup_global((gx, global_popup_y)))
            else:
                # Compatibility for lightweight/test menus without popupGlobal.
                shown = bool(menu.popup((x, popup_y)))
        except Exception:
            shown = bool(menu.popup())
        if shown:
            self._active_menu = menu
            self._active_button = button
            self._set_button_active(button, True)
        return shown

    def _menu_hidden(self, menu):
        if menu is not self._active_menu:
            return
        button = self._active_button
        self._active_menu = None
        self._active_button = None
        self._set_button_active(button, False)

    def closeActiveMenu(self):
        menu = self._active_menu
        if menu is None:
            return False
        return bool(menu.hide(consume_pointer=True))

    def delete(self):
        if self._deleted:
            return
        for menu in tuple(self._menus):
            try:
                menu.delete()
            except Exception:
                pass
        self._menus.clear()
        self._buttons.clear()
        for handler in tuple(self._handlers):
            try:
                if self.backend.does_item_exist(handler):
                    self.backend.delete_item(handler)
            except Exception:
                pass
        self._handlers.clear()
        try:
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)
        except Exception:
            pass
        super().delete()


__all__ = ["QMenuBar"]
