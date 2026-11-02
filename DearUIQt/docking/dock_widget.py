"""Reusable Qt-like dock chrome for Dear PyGui tool panels.

The implementation deliberately mirrors the interaction contract and compact
visual language of ``QDockWidget`` without introducing a Qt dependency.  The
host still owns the actual docking geometry; this class owns only the framed
panel, title chrome, float/close controls and state transitions.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..backends import dpg

from ..gui.palette import QtFusionPalette
from ..gui.action import QAction
from ..widgets.menu import QMenu
from ..widgets.widget import QWidget
from ..core.object import Signal
from ..gui.style import (
    dock_content_theme, dock_control_theme, dock_frame_theme, dock_title_theme,
)
from ..tooltip import add_styled_tooltip

from ..input_gate import (
    register_pointer_protected_item,
    unregister_pointer_protected_item,
)


class DockWidgetFeatures(int):
    """QFlags-like integer that remains compatible with legacy attribute use.

    Historical DearUIQt callers read ``dock.features`` as an integer, while
    Qt callers expect ``dock.features()``.  Making the flag value callable
    supports both contracts without a breaking rename.
    """

    def __new__(cls, value=0):
        return int.__new__(cls, int(value))

    def __call__(self):
        return int(self)


class DockWidget:
    """Compact dock container modelled after Qt/Fusion ``QDockWidget``.

    A docked instance has a one-pixel neutral frame, a 24 px title strip, small
    right-aligned float/close buttons and a content widget that is flush with
    the chrome.  When the host tears the dock out into a top-level window, the
    embedded title strip is normally hidden so the native floating window owns
    movement and title-bar chrome, just like a floating ``QDockWidget``.  A
    custom ``titleBarWidget`` remains embedded while floating, matching Qt.
    """

    # QDockWidget-style feature flags.  Keeping them local avoids a Qt
    # dependency while still exposing the same useful behaviour contract to
    # Qt-style tool panels.
    NoDockWidgetFeatures = 0x00
    DockWidgetClosable = 0x01
    DockWidgetMovable = 0x02
    DockWidgetFloatable = 0x04
    DockWidgetVerticalTitleBar = 0x08
    # Preserve the historical DearUIQt default: closable + movable + floatable.
    # Qt treats VerticalTitleBar as an opt-in presentation feature rather than
    # part of the default feature set.
    AllDockWidgetFeatures = (
        DockWidgetClosable | DockWidgetMovable | DockWidgetFloatable)

    # QMainWindow/QDockWidget-style dock areas.  These are deliberately kept
    # dependency-free so host applications can expose the familiar Qt contract while still
    # rendering with Dear PyGui.
    LeftDockWidgetArea = 0x01
    RightDockWidgetArea = 0x02
    TopDockWidgetArea = 0x04
    BottomDockWidgetArea = 0x08
    # Dependency-free counterpart of Qt::NoDockLocation (Qt 6.9+). ``None``
    # is intentionally outside the string dock-area vocabulary.
    NoDockLocation = None
    AllDockWidgetAreas = (
        LeftDockWidgetArea | RightDockWidgetArea
        | TopDockWidgetArea | BottomDockWidgetArea)
    _AREA_NAME_TO_FLAG = {
        "left": LeftDockWidgetArea,
        "right": RightDockWidgetArea,
        "top": TopDockWidgetArea,
        "bottom": BottomDockWidgetArea,
    }

    FRAME = 1
    TITLE_HEIGHT = 20
    CONTROL_SIZE = 18
    CONTROL_GAP = 0
    TITLE_LEFT_PADDING = 7
    TITLE_TOP_PADDING = 3
    TITLE_TEXT_HEIGHT = 13
    TITLE_TEXT_OPTICAL_Y = -3
    TITLE_TEXT_RIGHT_PADDING = 6

    # Text/glyph colors remain local geometry details; surface/state colors are
    # supplied by the shared Dear ImGui Qt/Fusion style foundation.
    TEXT_COLOR = QtFusionPalette.TEXT
    GLYPH_COLOR = (55, 55, 55, 255)

    def __init__(
            self,
            parent,
            title: str,
            tag: str,
            on_float_change: Optional[Callable[[bool], None]] = None,
            on_close: Optional[Callable[[], None]] = None,
            features: Optional[int] = None,
            dock_area: str = "right",
            allowed_areas: Optional[int] = None,
            on_dock_area_change: Optional[Callable[[str], None]] = None,
            on_visibility_change: Optional[Callable[[bool], None]] = None,
            visible: bool = True):
        self.parent = parent
        self.title = str(title or "")
        self.tag = str(tag)
        self.on_float_change = on_float_change
        self.on_close = on_close
        self.on_dock_area_change = on_dock_area_change
        self.on_visibility_change = on_visibility_change

        # QDockWidget exposes state transitions as signals.  Keep callback
        # hooks for host compatibility, but make the reusable wrapper usable
        # with ordinary Qt-style signal/slot wiring as well.
        self.allowedAreasChanged = Signal()
        self.dockLocationChanged = Signal()
        self.featuresChanged = Signal()
        self.objectNameChanged = Signal()
        self.topLevelChanged = Signal()
        self.visibilityChanged = Signal()
        self.windowTitleChanged = Signal()

        # QMainWindow::saveState identifies each dock by QObject::objectName.
        # Use the stable Dear PyGui tag as the default identity so every dock
        # can participate in state persistence without a second required id.
        self._object_name = self.tag

        self.features = DockWidgetFeatures(
            self.AllDockWidgetFeatures if features is None else int(features))
        self.allowed_areas = (
            self.AllDockWidgetAreas if allowed_areas is None
            else int(allowed_areas))
        self.dock_area = self._normalize_dock_area(dock_area)
        if not self.is_area_allowed(self.dock_area):
            self.dock_area = self._first_allowed_area()
        self.floating = False
        self._visible = bool(visible)
        self._effective_visible = bool(visible)
        self._last_layout_size = (0, 0)
        self._title_menu = None
        self._widget = None
        self._title_bar_widget = None

        # As in Qt, the dock owns one persistent checkable action suitable for
        # a View/Tool Windows menu.  This replaces duplicate host QAction state
        # and keeps programmatic visibility and menu check state synchronized.
        self._toggle_view_action = QAction(
            self.title, checkable=True, checked=self._visible)
        self._toggle_view_action.setToolTip(
            "Show or hide {}".format(self.title or "dock widget"))
        self._toggle_view_action.triggered.connect(
            self._toggle_view_action_triggered)

        self._build_themes()

        # Do not use Dear PyGui's native child border here.  Its thickness and
        # colour can vary with the global theme and produced the heavy black
        # outline seen in earlier builds.  Instead the root uses the frame
        # colour as its background and the title/content are inset by 1 px.
        self.root = dpg.add_child_window(
            parent=self.parent,
            tag=self.tag,
            width=-1,
            height=-1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
            show=self._visible,
        )
        dpg.bind_item_theme(self.root, self._frame_theme)
        # Do NOT register the embedded dock root as a global foreground
        # surface while it is docked. A docked panel is a normal sibling in
        # the main layout, not an overlay. Treating its large child-window
        # rectangle as a global input shield can make unrelated panes (most
        # visibly the Local Explorer list) non-interactive on DPG builds that
        # report child rect_min in parent-local coordinates.
        #
        # Click-through protection is still complete where it is needed:
        # * the title drag handle below is protected for tear-off gestures;
        # * the host registers the top-level floating window when detached;
        # * dialogs/popups register their own actual overlay surfaces.

        self.title_bar = dpg.add_child_window(
            parent=self.root,
            pos=(self.FRAME, self.FRAME),
            width=1,
            height=self.TITLE_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.title_bar, self._title_theme)

        # Transparent button used as the drag/double-click target.  It extends
        # from the left edge up to the title controls and therefore behaves like
        # the free title area in QDockWidget.
        self.drag_handle = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=1,
            height=self.TITLE_HEIGHT,
            callback=lambda: None,
        )
        self._drag_handle_widget = QWidget(self.drag_handle, backend=dpg)
        dpg.bind_item_theme(self.drag_handle, self._drag_theme)
        # Global DPG mouse handlers continue firing for widgets underneath a
        # dragged dock. Register the title handle as a protected foreground
        # surface so background views never start selection/rubber-band work.
        register_pointer_protected_item(self.drag_handle)

        self.title_text = dpg.add_text(
            self.title,
            parent=self.title_bar,
            pos=(self.TITLE_LEFT_PADDING, self.TITLE_TOP_PADDING),
            color=self.TEXT_COLOR,
        )

        with dpg.item_handler_registry() as self._title_handlers:
            dpg.add_item_double_clicked_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._title_double_clicked)
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                callback=self._show_title_menu)
        dpg.bind_item_handler_registry(self.drag_handle, self._title_handlers)

        # Buttons are hit areas only.  The small line glyphs are rendered in a
        # title overlay so their appearance does not depend on Unicode glyphs
        # being present in the Dear PyGui default font.
        self.float_button = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=self.CONTROL_SIZE,
            height=self.CONTROL_SIZE,
            callback=self._float_clicked,
        )
        self.close_button = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=self.CONTROL_SIZE,
            height=self.CONTROL_SIZE,
            callback=self._close_clicked,
        )
        dpg.bind_item_theme(self.float_button, self._float_control_theme)
        dpg.bind_item_theme(self.close_button, self._close_control_theme)

        add_styled_tooltip(self.float_button, "Float")
        add_styled_tooltip(self.close_button, "Close")

        # Qt exposes dock actions from the title area.  Reuse the retained
        # QMenu renderer instead of maintaining a second hand-written popup.
        # This keeps row metrics, checked dock-area state, keyboard navigation
        # and pointer shielding identical to every other context menu in the host application.
        self._title_menu_obj = QMenu((), backend=dpg, min_width=166)
        self._title_menu_obj.triggered.connect(self._title_menu_triggered)
        self._title_menu = self._title_menu_obj.tag
        register_pointer_protected_item(self._title_menu)
        self._rebuild_title_menu_actions()

        self.title_overlay = dpg.add_drawlist(
            parent=self.title_bar,
            pos=(0, 0),
            width=1,
            height=self.TITLE_HEIGHT,
        )
        # Floating glyph = two overlapping tiny windows.
        self._float_back = dpg.draw_rectangle(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.0,
            parent=self.title_overlay)
        self._float_front = dpg.draw_rectangle(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.0,
            parent=self.title_overlay)
        # Close glyph = crisp 8 px cross rather than a large window-style X.
        self._close_line_a = dpg.draw_line(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.15,
            parent=self.title_overlay)
        self._close_line_b = dpg.draw_line(
            (0, 1), (1, 0), color=self.GLYPH_COLOR, thickness=1.15,
            parent=self.title_overlay)
        with dpg.item_handler_registry() as self._close_visual_handlers:
            dpg.add_item_visible_handler(callback=self._sync_close_glyph_visual)
        dpg.bind_item_handler_registry(self.close_button, self._close_visual_handlers)

        self.content = dpg.add_child_window(
            parent=self.root,
            pos=(self.FRAME, self.TITLE_HEIGHT + 2 * self.FRAME),
            width=1,
            height=1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.content, self._content_theme)
        self._content_widget = QWidget(self.content, backend=dpg)

        self.sync_layout(force=True)

    def _build_themes(self):
        # The dock chrome now comes from the same Dear ImGui Qt/Fusion style
        # foundation as dialogs, toolbars and item views.  Keep only the
        # transparent drag target local because it is interaction geometry, not
        # a visible control.
        self._frame_theme = dock_frame_theme(dpg)
        self._title_theme = dock_title_theme(dpg, active=True)
        self._content_theme = dock_content_theme(dpg)
        self._float_control_theme = dock_control_theme(dpg, close=False)
        self._close_control_theme = dock_control_theme(dpg, close=True)

        with dpg.theme() as self._drag_theme:
            with dpg.theme_component(dpg.mvButton):
                transparent = (0, 0, 0, 0)
                dpg.add_theme_color(dpg.mvThemeCol_Button, transparent)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, transparent)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, transparent)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

    @classmethod
    def _normalize_dock_area(cls, area):
        name = str(area or "right").strip().lower()
        return name if name in cls._AREA_NAME_TO_FLAG else "right"

    def _first_allowed_area(self):
        for name in ("right", "left", "bottom", "top"):
            if self.is_area_allowed(name):
                return name
        return "right"

    def is_area_allowed(self, area):
        name = self._normalize_dock_area(area)
        return bool(int(self.allowed_areas) & int(self._AREA_NAME_TO_FLAG[name]))

    def set_allowed_areas(self, areas):
        areas = int(areas)
        if areas == int(self.allowed_areas):
            return False
        self.allowed_areas = areas
        previous_area = self.dock_area
        if not self.is_area_allowed(self.dock_area):
            self.dock_area = self._first_allowed_area()
        self._sync_action_visibility()
        self.allowedAreasChanged.emit(int(self.allowed_areas))
        if previous_area != self.dock_area:
            self.dockLocationChanged.emit(self.dock_area)
        return True

    def set_dock_area(self, area, notify=False):
        name = self._normalize_dock_area(area)
        if not self.is_area_allowed(name):
            return False
        changed = name != self.dock_area
        self.dock_area = name
        self._sync_action_visibility()
        if changed:
            self.dockLocationChanged.emit(name)
        if changed and notify and callable(self.on_dock_area_change):
            self.on_dock_area_change(name)
        return True

    # ------------------------------------------------------------------
    # QDockWidget-compatible retained state API
    # ------------------------------------------------------------------
    def windowTitle(self):
        return self.title

    def setWindowTitle(self, title):
        self.set_title(title)

    def objectName(self):
        return self._object_name

    def setObjectName(self, name):
        name = str(name or "")
        if name == self._object_name:
            return False
        self._object_name = name
        self.objectNameChanged.emit(name)
        return True

    def allowedAreas(self):
        return int(self.allowed_areas)

    def setAllowedAreas(self, areas):
        return self.set_allowed_areas(areas)

    def isAreaAllowed(self, area):
        return self.is_area_allowed(area)

    def dockWidgetArea(self):
        return self.dock_area

    # Qt 6.9+ QDockWidget property aliases.  ``dockWidgetArea`` remains as a
    # compatibility spelling used by older DearUIQt host code.
    def dockLocation(self):
        # Qt 6.9+: a floating QDockWidget has Qt::NoDockLocation.  ``None`` is
        # DearUIQt's dependency-free equivalent while ``dockWidgetArea()``
        # intentionally keeps returning the last dock area for legacy hosts.
        return self.NoDockLocation if self.floating else self.dock_area

    def setDockLocation(self, area):
        # Qt 6.9: setting Qt::NoDockLocation is equivalent to setFloating(true).
        if area is self.NoDockLocation:
            return self.setFloating(True)
        return self.set_dock_area(area, notify=True)

    def featuresFlags(self):
        """Return enabled dock features without colliding with legacy attribute."""
        return int(self.features)

    def setFeatures(self, features):
        return self.set_features(features)

    def isFloating(self):
        return bool(self.floating)

    def setFloating(self, floating):
        desired = bool(floating)
        if desired == self.floating:
            return False
        if callable(self.on_float_change):
            self.on_float_change(desired)
            return True
        return self.set_floating(desired)

    def isVisible(self):
        return bool(self._visible)

    def exists(self):
        """Return whether the retained dock root still exists in the renderer."""
        try:
            return bool(dpg.does_item_exist(self.root))
        except Exception:
            return not bool(getattr(self, "_closed", False))

    def setFocus(self):
        """Focus the dock root without exposing renderer focus APIs to callers."""
        if not self.exists():
            return False
        try:
            dpg.focus_item(self.root)
            return True
        except Exception:
            return False

    def setVisible(self, visible):
        return self.set_visible(visible, notify=True)

    def show(self):
        return self.set_visible(True, notify=True)

    def hide(self):
        return self.set_visible(False, notify=True)

    def toggleViewAction(self):
        return self._toggle_view_action

    def widget(self):
        """Return the client widget/tag installed with :meth:`setWidget`."""
        return self._widget if self._widget is not None else self.content

    def contentWidget(self):
        """Return a QWidget facade for the dock's native client surface."""
        return self._content_widget

    def dragHandleWidget(self):
        """Return a QWidget facade for the title-bar drag hit target."""
        return self._drag_handle_widget

    def setWidget(self, widget):
        """Install one Dear PyGui item as the dock client, Qt-style.

        Existing host panels may continue to build directly under ``content``;
        new reusable components can pass an already-created DPG item here.
        """
        if widget is None:
            self._widget = None
            return None
        try:
            if not dpg.does_item_exist(widget):
                raise ValueError("dock widget client does not exist")
            dpg.move_item(widget, parent=self.content)
        except AttributeError:
            # Very old Dear PyGui runtimes do not expose move_item.  Retain the
            # logical client reference rather than breaking compatibility.
            pass
        self._widget = widget
        return widget

    def takeWidget(self):
        """Detach the logical client reference and return it.

        Dear PyGui does not guarantee native reparenting to a null parent on all
        bundled versions, so ownership of the underlying item is intentionally
        left to the caller.
        """
        widget = self._widget
        self._widget = None
        return widget

    def titleBarWidget(self):
        """Return the custom title-bar widget, matching ``QDockWidget``."""
        return self._title_bar_widget

    def setTitleBarWidget(self, widget):
        """Install a custom title bar using the QDockWidget ownership contract.

        The custom item is reparented into the retained title-bar container and
        receives the complete title-bar geometry.  Passing ``None`` removes the
        previous custom bar from active use without deleting it and restores the
        built-in Fusion-like chrome.
        """
        if widget == self._title_bar_widget:
            return False
        if widget is not None:
            try:
                if not dpg.does_item_exist(widget):
                    raise ValueError("dock title-bar widget does not exist")
                dpg.move_item(widget, parent=self.title_bar)
            except AttributeError:
                # Keep the logical contract on older Dear PyGui builds that do
                # not expose move_item; the caller may have created it below
                # title_bar already.
                pass
        previous = self._title_bar_widget
        self._title_bar_widget = widget
        if previous is not None and previous != widget:
            try:
                if dpg.does_item_exist(previous):
                    dpg.configure_item(previous, show=False)
            except Exception:
                pass
        self._last_layout_size = (0, 0)
        self._sync_action_visibility()
        self.sync_layout(force=True)
        return True

    def _toggle_view_action_triggered(self, checked=False):
        self.set_visible(bool(checked), notify=True)

    def _sync_toggle_view_action(self):
        action = getattr(self, "_toggle_view_action", None)
        if action is None or action._deleted:
            return
        if action.isChecked() != bool(self._visible):
            action.setChecked(bool(self._visible))

    def _feature_enabled(self, feature):
        return bool(int(self.features) & int(feature))

    @property
    def movable(self):
        return self._feature_enabled(self.DockWidgetMovable)

    @property
    def floatable(self):
        return self._feature_enabled(self.DockWidgetFloatable)

    @property
    def closable(self):
        return self._feature_enabled(self.DockWidgetClosable)

    @property
    def vertical_title_bar(self):
        return self._feature_enabled(self.DockWidgetVerticalTitleBar)

    def set_features(self, features):
        features = int(features)
        if features == int(self.features):
            return False
        self.features = DockWidgetFeatures(features)
        self._last_layout_size = (0, 0)
        self._sync_action_visibility()
        self.sync_layout(force=True)
        self.featuresChanged.emit(int(self.features))
        return True

    def set_feature_enabled(self, feature, enabled=True):
        features = int(self.features)
        if enabled:
            features |= int(feature)
        else:
            features &= ~int(feature)
        self.set_features(features)

    def _sync_action_visibility(self):
        custom = self._title_bar_widget is not None
        try:
            # A custom QDockWidget titleBarWidget owns the complete chrome; the
            # built-in label, drag target and controls must not paint through it.
            for item in (self.drag_handle, self.title_text, self.title_overlay):
                if dpg.does_item_exist(item):
                    dpg.configure_item(item, show=not custom)
            if self._title_bar_widget is not None and dpg.does_item_exist(
                    self._title_bar_widget):
                dpg.configure_item(
                    self._title_bar_widget, show=True)
            if dpg.does_item_exist(self.float_button):
                dpg.configure_item(
                    self.float_button, show=bool(self.floatable and not custom))
            if dpg.does_item_exist(self.close_button):
                dpg.configure_item(
                    self.close_button, show=bool(self.closable and not custom))
            # Keep vector glyphs in lock-step with their hit buttons.
            for glyph in (self._float_back, self._float_front):
                if dpg.does_item_exist(glyph):
                    dpg.configure_item(
                        glyph, show=bool(self.floatable and not custom))
            for glyph in (self._close_line_a, self._close_line_b):
                if dpg.does_item_exist(glyph):
                    dpg.configure_item(
                        glyph, show=bool(self.closable and not custom))
            if self._title_menu and dpg.does_item_exist(self._title_menu):
                self._rebuild_title_menu_actions()
        except Exception:
            pass

    def _title_double_clicked(self, sender=None, app_data=None, user_data=None):
        # QDockWidget title-bar double click toggles top-level state when the
        # dock is floatable.  Floating native hosts may also route their own
        # title-bar double click back through setFloating(False).
        if self.floatable:
            self._float_clicked()

    def _dock_title_menu_actions(self):
        actions = []
        if self.floatable:
            actions.append({
                "id": "toggle_float",
                "label": "Dock" if self.floating else "Float",
                "action": "toggle_float",
            })
        dock_actions = []
        if self.movable:
            for area_name in ("left", "right", "top", "bottom"):
                if not self.is_area_allowed(area_name):
                    continue
                dock_actions.append({
                    "id": "dock_{}".format(area_name),
                    "label": "Dock {}".format(area_name.title()),
                    "action": "dock_{}".format(area_name),
                    "checkable": True,
                    "checked": bool(not self.floating and self.dock_area == area_name),
                })
        if dock_actions:
            if actions:
                actions.append({"separator": True, "label": "---", "action": "sep_dock"})
            actions.extend(dock_actions)
        if self.closable:
            if actions:
                actions.append({"separator": True, "label": "---", "action": "sep_close"})
            actions.append({"id": "close", "label": "Close", "action": "close"})
        return actions

    def _rebuild_title_menu_actions(self):
        menu = getattr(self, "_title_menu_obj", None)
        if menu is not None:
            menu.setActions(self._dock_title_menu_actions())

    def _show_title_menu(self, sender=None, app_data=None, user_data=None):
        menu = getattr(self, "_title_menu_obj", None)
        if menu is None:
            return
        self._sync_action_visibility()
        if not self.floatable and not self.closable and not self.movable:
            return
        try:
            menu.popupGlobal(context=self, owner=self.root)
        except Exception:
            menu.popup(context=self)

    def _hide_title_menu(self):
        menu = getattr(self, "_title_menu_obj", None)
        if menu is not None:
            menu.hide()

    def _title_menu_triggered(self, action, _context=None):
        action = str(action or "")
        if action == "toggle_float":
            self._float_clicked()
            return
        if action == "close":
            self._close_clicked()
            return
        if action.startswith("dock_"):
            area = self._normalize_dock_area(action[5:])
            if not self.movable or not self.is_area_allowed(area):
                return
            callback = self.on_dock_area_change
            if callable(callback):
                callback(area)
            else:
                self.set_dock_area(area)

    def _float_clicked(self, sender=None, app_data=None, user_data=None):
        if not self.floatable:
            return
        desired = not self.floating
        callback = self.on_float_change
        if callable(callback):
            callback(desired)
        else:
            self.set_floating(desired)

    def _close_clicked(self, sender=None, app_data=None, user_data=None):
        if not self.closable:
            return
        # QDockWidget close semantics first update visibility/action state, then
        # let the host persist or destroy the tool window as appropriate.
        self.set_visible(False)
        callback = self.on_close
        if callable(callback):
            callback()
        elif callable(self.on_visibility_change):
            self.on_visibility_change(False)

    @staticmethod
    def _elide_title(title: str, available_px: int):
        """Approximate Qt::ElideRight for the compact default DPG font."""
        text = str(title or "")
        available_px = max(0, int(available_px))
        # Default Dear PyGui text is close to seven pixels per average glyph at
        # typical desktop-tool scale. This intentionally errs on the conservative
        # side so long job names never paint underneath the dock controls.
        max_chars = max(0, available_px // 7)
        if len(text) <= max_chars:
            return text
        if max_chars <= 1:
            return ""
        if max_chars <= 4:
            return "." * max_chars
        return text[:max_chars - 3].rstrip() + "..."

    def set_title(self, title: str):
        title = str(title or "")
        if self.title == title:
            return False
        self.title = title
        self.windowTitleChanged.emit(title)
        action = getattr(self, "_toggle_view_action", None)
        if action is not None and not action._deleted:
            action.setText(title)
            action.setToolTip("Show or hide {}".format(title or "dock widget"))
        self.sync_layout(force=True)
        return True

    def _set_effective_visibility(self, visible: bool):
        """Update presentation visibility without changing toggleViewAction.

        QDockWidget emits ``visibilityChanged`` when tabification hides or
        reveals a dock, even though the user has not unchecked its view action.
        DockManager uses this hook for active-tab changes.
        """
        visible = bool(visible)
        if self._effective_visible == visible:
            return False
        self._effective_visible = visible
        self.visibilityChanged.emit(visible)
        return True

    def set_visible(self, visible: bool, notify=False):
        visible = bool(visible)
        changed = self._visible != visible
        self._visible = visible
        try:
            if dpg.does_item_exist(self.root):
                dpg.configure_item(self.root, show=visible)
        except Exception:
            pass
        self._sync_toggle_view_action()
        self._set_effective_visibility(visible)
        if changed and notify and callable(self.on_visibility_change):
            self.on_visibility_change(visible)
        return changed

    def set_floating(self, floating: bool, *, sync=True):
        """Set top-level state, optionally deferring the expensive layout pass.

        Dock/undock hand-offs usually perform a full host layout immediately
        afterwards.  Allowing that caller to defer this local relayout avoids
        duplicate Dear PyGui geometry work during the same UI turn while
        preserving the historical eager behaviour for normal callers.
        """
        floating = bool(floating)
        if self.floating == floating:
            if sync:
                self.sync_layout(force=True)
            return
        self.floating = floating
        self._hide_title_menu()
        self._sync_action_visibility()
        self.topLevelChanged.emit(floating)
        self.dockLocationChanged.emit(None if floating else self.dock_area)
        if dpg.does_item_exist(self.title_bar):
            dpg.configure_item(
                self.title_bar,
                show=bool(not floating or self._title_bar_widget is not None))
        if sync:
            self.sync_layout(force=True)

    def _sync_close_glyph_visual(self, sender=None, app_data=None, user_data=None):
        """Keep the vector X readable over the red close-button hover state."""
        try:
            hovered = bool(dpg.is_item_hovered(self.close_button))
            active = bool(dpg.is_item_active(self.close_button))
            color = (255, 255, 255, 255) if (hovered or active) else self.GLYPH_COLOR
            dpg.configure_item(self._close_line_a, color=color)
            dpg.configure_item(self._close_line_b, color=color)
        except Exception:
            pass

    def _update_title_glyphs(self, float_x: int, close_x: int, control_y: int):
        """Position vector glyphs over the right-aligned title buttons."""
        # Coordinates are relative to title_overlay/title_bar.  Derive every
        # glyph from the control centre so changing title-button metrics cannot
        # leave the symbols visually off-centre (a common ImGui-vs-Qt tell).
        fy = control_y
        half = self.CONTROL_SIZE / 2.0
        float_cx = float_x + half
        close_cx = close_x + half
        cy = fy + half
        try:
            dpg.configure_item(
                self._float_back,
                pmin=(float_cx - 5, cy - 2), pmax=(float_cx + 1, cy + 4))
            dpg.configure_item(
                self._float_front,
                pmin=(float_cx - 2, cy - 5), pmax=(float_cx + 4, cy + 1))
            dpg.configure_item(
                self._close_line_a,
                p1=(close_cx - 4, cy - 4), p2=(close_cx + 4, cy + 4))
            dpg.configure_item(
                self._close_line_b,
                p1=(close_cx + 4, cy - 4), p2=(close_cx - 4, cy + 4))
        except Exception:
            # Older DPG builds can be stricter about draw-item reconfiguration;
            # losing a glyph is preferable to breaking the dock layout.
            pass

    def _vertical_title_value(self, available_px):
        """Return a compact vertical fallback label for DPG's unrotated text."""
        text = str(self.title or "")
        # The default font is roughly 14 px high. Reserve a little breathing
        # room around the stacked glyphs and use an ellipsis when necessary.
        max_chars = max(0, int(max(0, available_px) // 14))
        if max_chars <= 0:
            return ""
        if len(text) > max_chars:
            if max_chars <= 3:
                text = "." * max_chars
            else:
                text = text[:max_chars - 3].rstrip() + "..."
        return "\n".join(text)

    @classmethod
    def _horizontal_title_text_y(cls, title_height):
        """Return a visually centered baseline offset for the default dock title.

        Dear PyGui positions text by its top edge while the dock controls are
        centered from their full button geometry.  Keeping a small nominal
        text-height estimate here avoids the title sitting 1-2 px too high in
        the compact 20 px Fusion-style title strip.
        """
        try:
            height = max(1, int(title_height))
        except Exception:
            height = cls.TITLE_HEIGHT
        geometric = int(round((height - cls.TITLE_TEXT_HEIGHT) * 0.5))
        # Dear ImGui/DPG font metrics include internal top leading that is not
        # visible glyph ink.  Compensate optically so the visible title glyphs
        # align with the centered dock controls rather than sitting low.
        return max(0, geometric + int(cls.TITLE_TEXT_OPTICAL_Y))

    def sync_layout(self, width=None, height=None, force=False):
        """Keep Qt-like chrome aligned while the host/splitter is resized.

        Explicit dimensions are the hot path used by DockManager.  Do not ask
        Dear PyGui for rect/configuration data in that case: those native
        queries are comparatively expensive and were previously repeated for
        every dock during each attach/detach layout commit.
        """
        if not dpg.does_item_exist(self.root):
            return

        actual_w = actual_h = 0
        cfg = {}
        if width is None or height is None:
            try:
                actual_w, actual_h = dpg.get_item_rect_size(self.root)
                actual_w, actual_h = int(actual_w), int(actual_h)
            except Exception:
                actual_w, actual_h = 0, 0
            if ((width is None and actual_w <= 1)
                    or (height is None and actual_h <= 1)):
                try:
                    cfg = dpg.get_item_configuration(self.root)
                except Exception:
                    cfg = {}

        if width is None:
            width = actual_w if actual_w > 1 else int(cfg.get("width", 1) or 1)
        if height is None:
            height = actual_h if actual_h > 1 else int(cfg.get("height", 1) or 1)
        width = max(1, int(width))
        height = max(1, int(height))

        if not force and self._last_layout_size == (width, height):
            return
        self._last_layout_size = (width, height)

        inner_w = max(1, width - 2 * self.FRAME)
        inner_h = max(1, height - 2 * self.FRAME)
        custom = self._title_bar_widget is not None
        vertical = bool(self.vertical_title_bar)

        # A default floating QDockWidget uses the native top-level title bar.
        # Installing a custom titleBarWidget suppresses native decorations in
        # Qt, so retain the custom chrome while floating as well.
        if self.floating and not custom:
            dpg.configure_item(self.title_bar, show=False)
            dpg.configure_item(
                self.content,
                pos=(self.FRAME, self.FRAME),
                width=inner_w,
                height=inner_h,
            )
            return

        title_extent = min(self.TITLE_HEIGHT, inner_w if vertical else inner_h)
        if vertical:
            title_pos = (self.FRAME, self.FRAME)
            title_w, title_h = title_extent, inner_h
            content_x = self.FRAME + title_w + self.FRAME
            content_y = self.FRAME
            content_w = max(1, width - content_x - self.FRAME)
            content_h = inner_h
        else:
            title_pos = (self.FRAME, self.FRAME)
            title_w, title_h = inner_w, title_extent
            content_x = self.FRAME
            content_y = self.FRAME + title_h + self.FRAME
            content_w = inner_w
            content_h = max(1, height - content_y - self.FRAME)

        dpg.configure_item(
            self.title_bar, pos=title_pos, width=title_w, height=title_h, show=True)

        if custom:
            # Qt removes all standard title-bar buttons/label when a custom
            # titleBarWidget is installed.  Give that widget the exact chrome
            # rect in either horizontal or vertical-title mode.
            self._sync_action_visibility()
            try:
                if dpg.does_item_exist(self._title_bar_widget):
                    dpg.configure_item(
                        self._title_bar_widget, pos=(0, 0), width=title_w,
                        height=title_h, show=True)
            except Exception:
                pass
            dpg.configure_item(
                self.content, pos=(content_x, content_y),
                width=content_w, height=content_h)
            return

        # Built-in title chrome.  In horizontal mode controls pack from the
        # right edge; VerticalTitleBar packs them from the bottom edge.
        visible_controls = []
        if self.floatable:
            visible_controls.append(self.float_button)
        if self.closable:
            visible_controls.append(self.close_button)
        controls_extent = (
            len(visible_controls) * self.CONTROL_SIZE
            + max(0, len(visible_controls) - 1) * self.CONTROL_GAP)

        close_x = title_w
        float_x = title_w
        control_y = 0
        if vertical:
            control_x = max(0, (title_w - self.CONTROL_SIZE) // 2)
            bottom_y = title_h
            close_y = title_h
            float_y = title_h
            if self.closable:
                bottom_y -= self.CONTROL_SIZE
                close_y = bottom_y
                dpg.configure_item(
                    self.close_button, pos=(control_x, close_y),
                    width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
                bottom_y -= self.CONTROL_GAP
            else:
                dpg.configure_item(self.close_button, show=False)
            if self.floatable:
                bottom_y -= self.CONTROL_SIZE
                float_y = bottom_y
                dpg.configure_item(
                    self.float_button, pos=(control_x, float_y),
                    width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
            else:
                dpg.configure_item(self.float_button, show=False)
            drag_h = max(1, title_h - controls_extent)
            dpg.configure_item(
                self.drag_handle, pos=(0, 0), width=title_w, height=drag_h, show=True)
            available = max(0, drag_h - 2 * self.TITLE_LEFT_PADDING)
            if dpg.does_item_exist(self.title_text):
                dpg.set_value(self.title_text, self._vertical_title_value(available))
                dpg.configure_item(
                    self.title_text, pos=(self.TITLE_TOP_PADDING, self.TITLE_LEFT_PADDING),
                    show=True)
            dpg.configure_item(
                self.title_overlay, pos=(0, 0), width=title_w, height=title_h, show=True)
            # Reuse the glyph renderer by passing the control's x coordinate
            # and each button's y coordinate via two small local updates.
            half = self.CONTROL_SIZE // 2
            cy_close = close_y + half
            cy_float = float_y + half
            cx = control_x + half
            try:
                dpg.configure_item(
                    self._float_back, pmin=(cx - 4, cy_float - 4),
                    pmax=(cx + 3, cy_float + 3), show=self.floatable)
                dpg.configure_item(
                    self._float_front, pmin=(cx - 2, cy_float - 2),
                    pmax=(cx + 5, cy_float + 5), show=self.floatable)
                dpg.configure_item(
                    self._close_line_a, p1=(cx - 4, cy_close - 4),
                    p2=(cx + 4, cy_close + 4), show=self.closable)
                dpg.configure_item(
                    self._close_line_b, p1=(cx + 4, cy_close - 4),
                    p2=(cx - 4, cy_close + 4), show=self.closable)
            except Exception:
                pass
        else:
            controls_w = controls_extent
            drag_w = max(1, title_w - controls_w)
            control_y = max(0, (title_h - self.CONTROL_SIZE) // 2)
            dpg.configure_item(
                self.drag_handle, pos=(0, 0), width=drag_w, height=title_h, show=True)

            right_x = title_w
            if self.closable:
                right_x -= self.CONTROL_SIZE
                close_x = right_x
                dpg.configure_item(
                    self.close_button, pos=(close_x, control_y),
                    width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
                right_x -= self.CONTROL_GAP
            else:
                dpg.configure_item(self.close_button, show=False)
            if self.floatable:
                right_x -= self.CONTROL_SIZE
                float_x = right_x
                dpg.configure_item(
                    self.float_button, pos=(float_x, control_y),
                    width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
            else:
                dpg.configure_item(self.float_button, show=False)

            title_available = max(
                0, drag_w - self.TITLE_LEFT_PADDING - self.TITLE_TEXT_RIGHT_PADDING)
            if dpg.does_item_exist(self.title_text):
                dpg.set_value(
                    self.title_text, self._elide_title(self.title, title_available))
                dpg.configure_item(
                    self.title_text,
                    pos=(self.TITLE_LEFT_PADDING,
                         self._horizontal_title_text_y(title_h)), show=True)
            dpg.configure_item(
                self.title_overlay, pos=(0, 0), width=title_w,
                height=title_h, show=True)
            if self.floatable or self.closable:
                self._update_title_glyphs(float_x, close_x, control_y)

        dpg.configure_item(
            self.content, pos=(content_x, content_y),
            width=content_w, height=content_h)

    def close(self):
        # root is intentionally not a protected surface while docked; keep the
        # unregister call harmless for compatibility with instances created by
        # an older build before an in-process update/reload.
        unregister_pointer_protected_item(getattr(self, "root", None))
        unregister_pointer_protected_item(getattr(self, "drag_handle", None))
        unregister_pointer_protected_item(getattr(self, "_title_menu", None))
        for handlers in (
                getattr(self, "_title_handlers", None),
                getattr(self, "_close_visual_handlers", None)):
            if handlers and dpg.does_item_exist(handlers):
                try:
                    dpg.delete_item(handlers)
                except Exception:
                    pass
        menu = getattr(self, "_title_menu_obj", None)
        if menu is not None:
            try:
                menu.delete()
            except Exception:
                pass
            self._title_menu_obj = None
        action = getattr(self, "_toggle_view_action", None)
        if action is not None and not action._deleted:
            try:
                action.delete()
            except Exception:
                pass
        for signal in (
                self.allowedAreasChanged, self.dockLocationChanged,
                self.featuresChanged, self.objectNameChanged,
                self.topLevelChanged,
                self.visibilityChanged, self.windowTitleChanged):
            signal.disconnect()
        if dpg.does_item_exist(self.root):
            dpg.delete_item(self.root)


class DockDropPreview:
    """Polished Visual-Studio/Qt-like docking guide overlay.

    Hit testing remains based on ``zone_rectangles`` and
    ``outer_zone_rectangles``. Rendering is deliberately richer: each guide is
    a compact white tile with a mini-layout diagram and a small directional
    triangle, closely matching common IDE docking affordances.
    """

    BORDER = (54, 151, 229, 235)
    FILL = (80, 165, 236, 44)
    INNER_BORDER = (78, 165, 231, 105)
    INNER_FILL = (120, 188, 241, 14)
    SCRIM_FILL = (190, 194, 200, 16)
    PANEL_BORDER = (205, 210, 216, 225)
    PANEL_FILL = (248, 249, 250, 218)
    SHADOW = (25, 35, 45, 28)

    ZONE_BORDER = (193, 199, 206, 255)
    ZONE_FILL = (253, 253, 254, 252)
    ZONE_ACTIVE_BORDER = (41, 149, 232, 255)
    ZONE_ACTIVE_FILL = (239, 248, 255, 255)

    FRAME = (128, 139, 150, 255)
    FRAME_ACTIVE = (44, 151, 235, 255)
    TARGET = (76, 174, 242, 255)
    TARGET_ACTIVE = (30, 148, 235, 255)
    ARROW = (118, 126, 135, 255)
    ARROW_ACTIVE = (36, 143, 226, 255)
    CENTER_BORDER = (195, 201, 208, 245)
    CENTER_FILL = (252, 253, 254, 248)
    ZONES = ("left", "right", "top", "bottom")

    def __init__(self, tag="dearuiqt_dock_drop_preview"):
        self.tag = str(tag)
        self._layer = None
        self._scrim = None
        self._panel = None
        self._rect = None
        self._inner = None
        self._center_shadow = None
        self._center_item = None
        self._center_frame = None
        self._zone_shadows = {}
        self._outer_zone_shadows = {}
        self._zone_items = {}
        self._outer_zone_items = {}
        self._zone_frames = {}
        self._outer_zone_frames = {}
        self._zone_targets = {}
        self._outer_zone_targets = {}
        self._zone_arrows = {}
        self._outer_zone_arrows = {}
        self._last_rect = None
        self._last_inset = None
        self._last_zone_bounds = None
        self._active_zone = None
        self._active_scope = None

    @staticmethod
    def zone_rectangles(bounds):
        x, y, width, height = map(float, bounds)
        width, height = max(1.0, width), max(1.0, height)
        cx, cy = x + width * 0.5, y + height * 0.5
        base = min(width, height)
        center = min(40.0, max(32.0, base * 0.092))
        gap = min(9.0, max(6.0, center * 0.18))
        side_w = min(27.0, max(20.0, center * 0.60))
        side_h = min(40.0, max(30.0, center * 0.94))
        return {
            "left": (cx - center * 0.5 - gap - side_w, cy - side_h * 0.5,
                     side_w, side_h),
            "right": (cx + center * 0.5 + gap, cy - side_h * 0.5,
                      side_w, side_h),
            "top": (cx - side_h * 0.5, cy - center * 0.5 - gap - side_w,
                    side_h, side_w),
            "bottom": (cx - side_h * 0.5, cy + center * 0.5 + gap,
                       side_h, side_w),
        }

    @staticmethod
    def outer_zone_rectangles(bounds):
        x, y, width, height = map(float, bounds)
        width, height = max(1.0, width), max(1.0, height)
        cx, cy = x + width * 0.5, y + height * 0.5
        margin_x = min(52.0, max(22.0, width * 0.095))
        margin_y = min(48.0, max(20.0, height * 0.10))
        box_w = min(21.0, max(16.0, min(width, height) * 0.043))
        box_h = min(31.0, max(23.0, min(width, height) * 0.066))
        return {
            "left": (x + margin_x, cy - box_h * 0.5, box_w, box_h),
            "right": (x + width - margin_x - box_w, cy - box_h * 0.5,
                      box_w, box_h),
            "top": (cx - box_h * 0.5, y + margin_y, box_h, box_w),
            "bottom": (cx - box_h * 0.5, y + height - margin_y - box_w,
                       box_h, box_w),
        }

    @staticmethod
    def panel_geometry(bounds):
        rects = DockDropPreview.zone_rectangles(bounds)
        xs = [r[0] for r in rects.values()]
        ys = [r[1] for r in rects.values()]
        x2s = [r[0] + r[2] for r in rects.values()]
        y2s = [r[1] + r[3] for r in rects.values()]
        pad = 9.0
        return (min(xs) - pad, min(ys) - pad,
                max(x2s) - min(xs) + 2.0 * pad,
                max(y2s) - min(ys) + 2.0 * pad)

    @staticmethod
    def center_rect(bounds):
        x, y, width, height = DockDropPreview.panel_geometry(bounds)
        cx, cy = x + width * 0.5, y + height * 0.5
        size = min(38.0, max(30.0, min(width, height) * 0.22))
        return (cx - size * 0.5, cy - size * 0.5, size, size)

    @staticmethod
    def zone_at(point, bounds, tolerance=0.0):
        if point is None or bounds is None:
            return None
        mx, my = map(float, point)
        tolerance = max(0.0, float(tolerance))
        for zone, rect in DockDropPreview.zone_rectangles(bounds).items():
            x, y, w, h = rect
            if (x - tolerance <= mx <= x + w + tolerance
                    and y - tolerance <= my <= y + h + tolerance):
                return zone
        return None

    @staticmethod
    def outer_zone_at(point, bounds, tolerance=0.0):
        if point is None or bounds is None:
            return None
        mx, my = map(float, point)
        tolerance = max(0.0, float(tolerance))
        for zone, rect in DockDropPreview.outer_zone_rectangles(bounds).items():
            x, y, w, h = rect
            if (x - tolerance <= mx <= x + w + tolerance
                    and y - tolerance <= my <= y + h + tolerance):
                return zone
        return None

    @staticmethod
    def zone_hit(point, bounds, tolerance=0.0):
        if point is None or bounds is None:
            return None, None
        mx, my = map(float, point)

        # The center tile is intentionally neutral.  It is a visual anchor for
        # the four-way guide, not a drop target.  Check it before applying any
        # tolerance to the surrounding zones so their expanded hitboxes can
        # never steal the center and resolve to a nearest dock direction.
        cx, cy, cw, ch = DockDropPreview.center_rect(bounds)
        center_guard = 2.0
        if (cx - center_guard <= mx <= cx + cw + center_guard
                and cy - center_guard <= my <= cy + ch + center_guard):
            return None, None

        # Keep the central directional guides precise.  Outer edge guides may
        # use the caller's larger tolerance because they are isolated and are
        # intended to be easy edge targets.
        inner_tolerance = min(max(0.0, float(tolerance)), 2.0)
        zone = DockDropPreview.zone_at(point, bounds, inner_tolerance)
        if zone is not None:
            return zone, "inner"
        zone = DockDropPreview.outer_zone_at(point, bounds, tolerance)
        if zone is not None:
            return zone, "outer"
        return None, None

    @staticmethod
    def _configure_rect(item, rect, **kwargs):
        x, y, w, h = map(float, rect)
        dpg.configure_item(item, pmin=(x, y), pmax=(x + w, y + h), **kwargs)

    @staticmethod
    def _shadow_rect(rect):
        x, y, w, h = map(float, rect)
        return (x + 1.2, y + 1.8, w, h)

    @staticmethod
    def _mini_frame_rect(rect, zone=None):
        """Reserve a dedicated gutter for the directional arrow.

        Keeping the miniature layout and arrow in separate visual regions
        prevents the icon overlap that made the previous guide look cramped.
        """
        x, y, w, h = map(float, rect)
        zone = str(zone or "").lower()
        if zone == "left":
            arrow_w = max(6.0, w * 0.28)
            return (x + max(3.0, w * 0.12), y + max(4.0, h * 0.19),
                    max(6.0, w - arrow_w - max(6.0, w * 0.26)),
                    max(7.0, h - 2.0 * max(4.0, h * 0.19)))
        if zone == "right":
            arrow_w = max(6.0, w * 0.28)
            left_pad = arrow_w + max(3.0, w * 0.14)
            return (x + left_pad, y + max(4.0, h * 0.19),
                    max(6.0, w - left_pad - max(3.0, w * 0.12)),
                    max(7.0, h - 2.0 * max(4.0, h * 0.19)))
        if zone == "top":
            arrow_h = max(6.0, h * 0.30)
            return (x + max(4.0, w * 0.18), y + max(3.0, h * 0.10),
                    max(8.0, w - 2.0 * max(4.0, w * 0.18)),
                    max(6.0, h - arrow_h - max(5.0, h * 0.24)))
        if zone == "bottom":
            arrow_h = max(6.0, h * 0.30)
            top_pad = arrow_h + max(3.0, h * 0.14)
            return (x + max(4.0, w * 0.18), y + top_pad,
                    max(8.0, w - 2.0 * max(4.0, w * 0.18)),
                    max(6.0, h - top_pad - max(3.0, h * 0.10)))
        px = max(5.0, w * 0.22)
        py = max(5.0, h * 0.22)
        return (x + px, y + py, max(8.0, w - 2 * px), max(8.0, h - 2 * py))

    @staticmethod
    def _target_rect(frame_rect, zone):
        x, y, w, h = map(float, frame_rect)
        edge = max(2.0, min(w, h) * 0.28)
        if zone == "left":
            return (x, y, min(edge, w), h)
        if zone == "right":
            return (x + max(0.0, w - edge), y, min(edge, w), h)
        if zone == "top":
            return (x, y, w, min(edge, h))
        return (x, y + max(0.0, h - edge), w, min(edge, h))

    @staticmethod
    def _arrow_points(rect, zone):
        x, y, w, h = map(float, rect)
        s = max(1.8, min(w, h) * 0.085)
        if zone == "left":
            cx, cy = x + w * 0.86, y + h * 0.5
            return ((cx - s, cy), (cx + s, cy - s), (cx + s, cy + s))
        if zone == "right":
            cx, cy = x + w * 0.14, y + h * 0.5
            return ((cx + s, cy), (cx - s, cy - s), (cx - s, cy + s))
        if zone == "top":
            cx, cy = x + w * 0.5, y + h * 0.87
            return ((cx, cy - s), (cx - s, cy + s), (cx + s, cy + s))
        cx, cy = x + w * 0.5, y + h * 0.13
        return ((cx, cy + s), (cx - s, cy - s), (cx + s, cy - s))

    @staticmethod
    def _configure_triangle(item, points, **kwargs):
        p1, p2, p3 = points
        dpg.configure_item(item, p1=p1, p2=p2, p3=p3, **kwargs)

    def _ensure_built(self):
        if self._layer and dpg.does_item_exist(self._layer):
            return True
        self._layer = None
        self._scrim = None
        self._panel = None
        self._rect = None
        self._inner = None
        self._center_shadow = None
        self._center_item = None
        self._center_frame = None
        self._zone_shadows = {}
        self._outer_zone_shadows = {}
        self._zone_items = {}
        self._outer_zone_items = {}
        self._zone_frames = {}
        self._outer_zone_frames = {}
        self._zone_targets = {}
        self._outer_zone_targets = {}
        self._zone_arrows = {}
        self._outer_zone_arrows = {}
        if dpg.does_item_exist(self.tag):
            try:
                dpg.delete_item(self.tag)
            except Exception:
                pass
        try:
            self._layer = dpg.add_viewport_drawlist(front=True, tag=self.tag)
        except TypeError:
            try:
                self._layer = dpg.add_viewport_drawlist(tag=self.tag)
            except Exception:
                self._layer = None
                return False
        except Exception:
            self._layer = None
            return False
        try:
            self._scrim = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=(0, 0, 0, 0), fill=self.SCRIM_FILL, thickness=0.0, show=False)
            self._rect = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=self.BORDER, fill=self.FILL, thickness=1.5, rounding=0.0, show=False)
            self._inner = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=self.INNER_BORDER, fill=self.INNER_FILL, thickness=1.0, rounding=0.0, show=False)
            self._panel = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=self.PANEL_BORDER, fill=self.PANEL_FILL, thickness=1.0, rounding=2.0, show=False)
            self._center_shadow = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=(0, 0, 0, 0), fill=self.SHADOW, thickness=0.0, rounding=1.5, show=False)
            self._center_item = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=self.CENTER_BORDER, fill=self.CENTER_FILL, thickness=1.0, rounding=1.5, show=False)
            self._center_frame = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                color=self.FRAME_ACTIVE, fill=(0, 0, 0, 0), thickness=1.1, rounding=0.0, show=False)
            for zone in self.ZONES:
                self._zone_shadows[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=(0, 0, 0, 0), fill=self.SHADOW, thickness=0.0, rounding=1.5, show=False)
                self._outer_zone_shadows[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=(0, 0, 0, 0), fill=self.SHADOW, thickness=0.0, rounding=1.5, show=False)
                self._zone_items[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.ZONE_BORDER, fill=self.ZONE_FILL, thickness=1.0, rounding=1.5, show=False)
                self._outer_zone_items[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.ZONE_BORDER, fill=self.ZONE_FILL, thickness=1.0, rounding=1.5, show=False)
                self._zone_frames[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.FRAME, fill=(0, 0, 0, 0), thickness=1.0, rounding=0.0, show=False)
                self._outer_zone_frames[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.FRAME, fill=(0, 0, 0, 0), thickness=1.0, rounding=0.0, show=False)
                self._zone_targets[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.TARGET, fill=self.TARGET, thickness=1.0, rounding=0.0, show=False)
                self._outer_zone_targets[zone] = dpg.draw_rectangle((0, 0), (1, 1), parent=self._layer,
                    color=self.TARGET, fill=self.TARGET, thickness=1.0, rounding=0.0, show=False)
                self._zone_arrows[zone] = dpg.draw_triangle((0, 0), (1, 1), (0, 1), parent=self._layer,
                    color=self.ARROW, fill=self.ARROW, thickness=1.0, show=False)
                self._outer_zone_arrows[zone] = dpg.draw_triangle((0, 0), (1, 1), (0, 1), parent=self._layer,
                    color=self.ARROW, fill=self.ARROW, thickness=1.0, show=False)
        except Exception:
            self.destroy()
            return False
        return True

    def prepare(self):
        return bool(self._ensure_built())

    def show(self, x, y, width, height, *, inset=True):
        if not self._ensure_built():
            return False
        self._hide_guides()
        return self._show_result((x, y, width, height), inset=inset)

    def _show_result(self, geometry, *, inset=True):
        x, y, width, height = map(float, geometry)
        width, height = max(1.0, width), max(1.0, height)
        x2, y2 = x + width, y + height
        try:
            dpg.configure_item(self._rect, pmin=(x, y), pmax=(x2, y2), show=True)
            if inset and width > 24 and height > 24:
                pad = min(9.0, width * 0.065, height * 0.065)
                dpg.configure_item(self._inner, pmin=(x + pad, y + pad),
                                   pmax=(x2 - pad, y2 - pad), show=True)
            else:
                dpg.configure_item(self._inner, show=False)
            self._last_rect = (x, y, width, height)
            self._last_inset = bool(inset)
            return True
        except Exception:
            return False

    def _configure_guide(self, rect, zone, active, shadow, item, frame, target, arrow):
        border = self.ZONE_ACTIVE_BORDER if active else self.ZONE_BORDER
        fill = self.ZONE_ACTIVE_FILL if active else self.ZONE_FILL
        frame_color = self.FRAME_ACTIVE if active else self.FRAME
        target_color = self.TARGET_ACTIVE if active else self.TARGET
        arrow_color = self.ARROW_ACTIVE if active else self.ARROW
        self._configure_rect(shadow, self._shadow_rect(rect), show=True)
        self._configure_rect(item, rect, show=True, color=border, fill=fill,
                             thickness=(1.35 if active else 1.0), rounding=1.5)
        mini = self._mini_frame_rect(rect, zone)
        self._configure_rect(frame, mini, show=True, color=frame_color,
                             fill=(0, 0, 0, 0), thickness=(1.15 if active else 1.0), rounding=0.0)
        self._configure_rect(target, self._target_rect(mini, zone), show=True,
                             color=target_color, fill=target_color, thickness=1.0, rounding=0.0)
        self._configure_triangle(arrow, self._arrow_points(rect, zone), show=True,
                                 color=arrow_color, fill=arrow_color, thickness=1.0)

    def show_zones(self, bounds, *, active=None, active_scope=None, preview_rect=None):
        if not self._ensure_built():
            return False
        active = str(active or "").strip().lower() or None
        if active not in self.ZONES:
            active = None
        active_scope = str(active_scope or "").strip().lower() or None
        if active_scope not in ("inner", "outer"):
            active_scope = None
        try:
            dpg.configure_item(self._scrim, pmin=(bounds[0], bounds[1]),
                               pmax=(bounds[0] + bounds[2], bounds[1] + bounds[3]), show=True)
            self._configure_rect(self._panel, self.panel_geometry(bounds), show=True)
            center = self.center_rect(bounds)
            self._configure_rect(self._center_shadow, self._shadow_rect(center), show=True)
            self._configure_rect(self._center_item, center, show=True)
            self._configure_rect(self._center_frame, self._mini_frame_rect(center, None), show=True,
                                 color=self.FRAME_ACTIVE, fill=(0, 0, 0, 0), thickness=1.1, rounding=0.0)
            rects = self.zone_rectangles(bounds)
            outer = self.outer_zone_rectangles(bounds)
            for zone in self.ZONES:
                self._configure_guide(rects[zone], zone,
                    zone == active and active_scope == "inner",
                    self._zone_shadows[zone], self._zone_items[zone],
                    self._zone_frames[zone], self._zone_targets[zone], self._zone_arrows[zone])
                self._configure_guide(outer[zone], zone,
                    zone == active and active_scope == "outer",
                    self._outer_zone_shadows[zone], self._outer_zone_items[zone],
                    self._outer_zone_frames[zone], self._outer_zone_targets[zone], self._outer_zone_arrows[zone])
            self._last_zone_bounds = tuple(map(float, bounds))
            self._active_zone = active
            self._active_scope = active_scope
            if active is not None and preview_rect is not None:
                self._show_result(preview_rect, inset=True)
            else:
                dpg.configure_item(self._rect, show=False)
                dpg.configure_item(self._inner, show=False)
                self._last_rect = None
                self._last_inset = None
            return True
        except Exception:
            return False

    def _hide_guides(self):
        items = [self._scrim, self._panel, self._center_shadow,
                 self._center_item, self._center_frame]
        for mapping in (self._zone_shadows, self._outer_zone_shadows,
                        self._zone_items, self._outer_zone_items,
                        self._zone_frames, self._outer_zone_frames,
                        self._zone_targets, self._outer_zone_targets,
                        self._zone_arrows, self._outer_zone_arrows):
            items.extend(mapping.values())
        for item in items:
            if item and dpg.does_item_exist(item):
                try:
                    dpg.configure_item(item, show=False)
                except Exception:
                    pass
        self._last_zone_bounds = None
        self._active_zone = None
        self._active_scope = None

    def hide(self):
        for item in (self._rect, self._inner):
            if item and dpg.does_item_exist(item):
                try:
                    dpg.configure_item(item, show=False)
                except Exception:
                    pass
        self._hide_guides()
        self._last_rect = None
        self._last_inset = None

    def destroy(self):
        layer = self._layer
        self._layer = None
        self._scrim = None
        self._panel = None
        self._rect = None
        self._inner = None
        self._center_shadow = None
        self._center_item = None
        self._center_frame = None
        self._zone_shadows = {}
        self._outer_zone_shadows = {}
        self._zone_items = {}
        self._outer_zone_items = {}
        self._zone_frames = {}
        self._outer_zone_frames = {}
        self._zone_targets = {}
        self._outer_zone_targets = {}
        self._zone_arrows = {}
        self._outer_zone_arrows = {}
        self._last_rect = None
        self._last_inset = None
        self._last_zone_bounds = None
        self._active_zone = None
        self._active_scope = None
        if layer and dpg.does_item_exist(layer):
            try:
                dpg.delete_item(layer)
            except Exception:
                pass
