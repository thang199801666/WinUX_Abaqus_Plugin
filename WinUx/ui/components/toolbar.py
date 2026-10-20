from __future__ import annotations

from pathlib import Path
import os

from ...resources import RESOURCE_DIR, icon_path
from DearUIQt.tooltip import add_styled_tooltip, reset_tooltip_runtime_resources
from DearUIQt.gui import QtFusionMetrics, QtFusionPalette
from DearUIQt.widgets import QMenu, QLineEdit, QPushButton, QToolButton, QFrame, QSpacer, QImageView, QRetainedItem
from DearUIQt.layouts import QGridLayout, QHBoxLayout
from DearUIQt.themes import (
    ThemeTarget, ThemeColor, ThemeStyle, theme_component, make_theme, QTheme,
    tool_bar_theme as imgui_tool_bar_theme,
    tool_button_theme as imgui_tool_button_theme,
    path_bar_theme as imgui_path_bar_theme,
    status_bar_theme as imgui_status_bar_theme,
    status_text_theme as imgui_status_text_theme,
    menu_bar_theme as imgui_menu_bar_theme,
    command_button_theme as imgui_command_button_theme,
)
from DearUIQt.input_gate import register_pointer_protected_item
from DearUIQt.gui import QFontDatabase, QTextureRegistry
from DearUIQt import QGuiRuntime

_TOOLBAR_ICON_THEME = None
_PLOT_PANEL_ICON_THEME = None
_TOOLBAR_FITTED_ICON_THEME = None
_PATH_BUTTON_THEME = None
_MENU_THEME = None
_TOOLBAR_TABLE_THEME = None
_SEARCH_POPUP_THEME = None
_SEARCH_INPUT_THEME = None
_SEARCH_CLOSE_THEME = None
_SEARCH_SHELL_THEME = None
_SEARCH_EDITOR_THEME = None
_PATH_BUTTON_FONT = None
_PATH_FONT_DB = None
_RESOURCE_TEXTURE_REGISTRY = None

DEFAULT_UI_TEXTURE_SIZE = 32
TOOLBAR_TEXTURE_SIZE = 48

# Qt-style toolbar geometry.  The visible icon stays compact while the
# clickable QToolButton-like frame fills the 32 px toolbar cell.
TOOLBAR_BUTTON_WIDTH = 30
TOOLBAR_BUTTON_HEIGHT = 28
TOOLBAR_ICON_SIZE = 22
TOOLBAR_VERTICAL_OFFSET = 2



def _theme_alive(theme):
    if theme is None:
        return False
    try:
        return bool(theme.exists()) if hasattr(theme, "exists") else True
    except Exception:
        return False

def _owned_theme(native, *, owns=False):
    if isinstance(native, QTheme):
        return native
    return QTheme(theme_id=native, owns=owns)

def path_button_font():
    """Return the normal Windows UI font used by Qt-style path fields.

    Earlier builds used a 16 px bold face, which made the path selector read
    like a toolbar heading.  A QLineEdit/QComboBox path field uses the normal
    application font, so prefer Segoe UI regular at 14 px and retain bold
    fonts only as a compatibility fallback on stripped Windows images.
    """
    global _PATH_BUTTON_FONT, _PATH_FONT_DB
    if _PATH_BUTTON_FONT is not None and _PATH_BUTTON_FONT.exists():
        return _PATH_BUTTON_FONT

    windir = Path(os.environ.get("WINDIR", r"C:\\Windows"))
    candidates = (
        windir / "Fonts" / "segoeui.ttf",
        windir / "Fonts" / "segoeuib.ttf",
        windir / "Fonts" / "seguisb.ttf",
        windir / "Fonts" / "arial.ttf",
    )
    try:
        font_path = next((path for path in candidates if path.is_file()), None)
        if font_path is None:
            return None
        if _PATH_FONT_DB is None:
            _PATH_FONT_DB = QFontDatabase()
        _PATH_BUTTON_FONT = _PATH_FONT_DB.addApplicationFont(str(font_path), 14)
    except Exception:
        _PATH_BUTTON_FONT = None
    return _PATH_BUTTON_FONT


def toolbar_table_theme():
    """Compact QToolBar table: no card-like cell padding around actions."""
    global _TOOLBAR_TABLE_THEME
    if _theme_alive(_TOOLBAR_TABLE_THEME):
        return _TOOLBAR_TABLE_THEME
    _TOOLBAR_TABLE_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.TABLE, styles={ThemeStyle.CELL_PADDING: (1, 2)},
    )), owns=True)
    return _TOOLBAR_TABLE_THEME




def search_popup_theme():
    """Qt/Fusion-like inline search surface shared by both file panes."""
    global _SEARCH_POPUP_THEME
    if _theme_alive(_SEARCH_POPUP_THEME):
        return _SEARCH_POPUP_THEME
    p = QtFusionPalette
    _SEARCH_POPUP_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.WINDOW_BACKGROUND: p.TOOLBAR, ThemeColor.CHILD_BACKGROUND: p.TOOLBAR,
            ThemeColor.BORDER: p.BORDER, ThemeColor.BORDER_SHADOW: p.SHADOW,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (6, 3), ThemeStyle.WINDOW_ROUNDING: 0,
            ThemeStyle.CHILD_ROUNDING: 0, ThemeStyle.WINDOW_BORDER_SIZE: 0,
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.ITEM_SPACING: (5, 0),
        },
    )), owns=True)
    return _SEARCH_POPUP_THEME

def search_input_theme():
    """Compact QLineEdit-like search field."""
    global _SEARCH_INPUT_THEME
    if _theme_alive(_SEARCH_INPUT_THEME):
        return _SEARCH_INPUT_THEME
    p = QtFusionPalette
    _SEARCH_INPUT_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: p.BASE, ThemeColor.FRAME_BACKGROUND_HOVERED: p.BASE,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: p.BASE, ThemeColor.TEXT: p.TEXT,
            ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
            ThemeColor.TEXT_SELECTED_BACKGROUND: (0, 120, 215, 105), ThemeColor.BORDER: p.BORDER,
        },
        styles={
            ThemeStyle.FRAME_PADDING: (6, 3),
            ThemeStyle.FRAME_ROUNDING: QtFusionMetrics.FRAME_ROUNDING,
            ThemeStyle.FRAME_BORDER_SIZE: 1,
        },
    )), owns=True)
    return _SEARCH_INPUT_THEME

def search_shell_theme():
    """One QLineEdit-like frame around icon, editor and clear action."""
    global _SEARCH_SHELL_THEME
    if _theme_alive(_SEARCH_SHELL_THEME):
        return _SEARCH_SHELL_THEME
    p = QtFusionPalette
    _SEARCH_SHELL_THEME = _owned_theme(make_theme(
        theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: p.BORDER},
            styles={
                ThemeStyle.WINDOW_PADDING: (4, 1), ThemeStyle.ITEM_SPACING: (0, 0),
                ThemeStyle.CHILD_BORDER_SIZE: 1,
                ThemeStyle.CHILD_ROUNDING: QtFusionMetrics.FRAME_ROUNDING,
            },
        ),
        theme_component(ThemeTarget.TABLE, styles={ThemeStyle.CELL_PADDING: (0, 0)}),
    ), owns=True)
    return _SEARCH_SHELL_THEME


def search_editor_theme():
    """Borderless editor used inside :func:`search_shell_theme`."""
    global _SEARCH_EDITOR_THEME
    if _theme_alive(_SEARCH_EDITOR_THEME):
        return _SEARCH_EDITOR_THEME
    p = QtFusionPalette
    _SEARCH_EDITOR_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: p.BASE, ThemeColor.FRAME_BACKGROUND_HOVERED: p.BASE,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: p.BASE, ThemeColor.TEXT: p.TEXT,
            ThemeColor.TEXT_SELECTED_BACKGROUND: (0, 120, 215, 105),
            ThemeColor.BORDER: (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.FRAME_PADDING: (3, 3), ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.FRAME_ROUNDING: 0,
        },
    )), owns=True)
    return _SEARCH_EDITOR_THEME


def search_close_theme():
    global _SEARCH_CLOSE_THEME
    if _theme_alive(_SEARCH_CLOSE_THEME):
        return _SEARCH_CLOSE_THEME
    p = QtFusionPalette
    _SEARCH_CLOSE_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors={
            ThemeColor.BUTTON: (0, 0, 0, 0), ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE, ThemeColor.TEXT: p.TEXT,
            ThemeColor.BORDER: (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.FRAME_PADDING: (3, 2),
            ThemeStyle.FRAME_ROUNDING: QtFusionMetrics.FRAME_ROUNDING,
            ThemeStyle.FRAME_BORDER_SIZE: 0,
        },
    )), owns=True)
    return _SEARCH_CLOSE_THEME

def toolbar_icon_theme():
    global _TOOLBAR_ICON_THEME
    if _theme_alive(_TOOLBAR_ICON_THEME):
        return _TOOLBAR_ICON_THEME
    _TOOLBAR_ICON_THEME = _owned_theme(imgui_tool_button_theme())
    return _TOOLBAR_ICON_THEME


def plot_panel_icon_theme():
    """Raised icon-button theme for the Job Viewer Plots side panel.

    The generic toolbar icon theme is intentionally almost transparent so it can
    blend into dense toolbars.  In the Plots side panel this made the icon
    actions feel visually sunken into the light surface.  Give them a subtle
    Qt-like block surface with a real border and stronger hover/pressed states
    so the tools read as actionable controls without becoming glossy.
    """
    global _PLOT_PANEL_ICON_THEME
    if _theme_alive(_PLOT_PANEL_ICON_THEME):
        return _PLOT_PANEL_ICON_THEME
    p = QtFusionPalette
    _PLOT_PANEL_ICON_THEME = _owned_theme(make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors={
            ThemeColor.BUTTON: p.BUTTON,
            ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
            ThemeColor.TEXT: p.TEXT,
            ThemeColor.BORDER: p.BORDER,
        },
        styles={
            ThemeStyle.FRAME_PADDING: (4, 3),
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_ROUNDING: max(2, QtFusionMetrics.FRAME_ROUNDING),
        },
    ), theme_component(
        ThemeTarget.IMAGE_BUTTON,
        colors={
            ThemeColor.BUTTON: p.BUTTON,
            ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
            ThemeColor.BORDER: p.BORDER,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_ROUNDING: max(2, QtFusionMetrics.FRAME_ROUNDING),
        },
    )), owns=True)
    return _PLOT_PANEL_ICON_THEME


def toolbar_fitted_icon_theme():
    """Compact image-button theme for dense 22 px toolbar cells.

    The icon fills most of the 22 px cell while keeping a minimal safety
    margin so generated PNG strokes do not clip against the button frame.
    """
    global _TOOLBAR_FITTED_ICON_THEME
    if _theme_alive(_TOOLBAR_FITTED_ICON_THEME):
        return _TOOLBAR_FITTED_ICON_THEME
    _TOOLBAR_FITTED_ICON_THEME = _owned_theme(imgui_tool_button_theme(frame_padding=(1, 1)))
    return _TOOLBAR_FITTED_ICON_THEME

def path_button_theme():
    global _PATH_BUTTON_THEME
    if _theme_alive(_PATH_BUTTON_THEME):
        return _PATH_BUTTON_THEME
    _PATH_BUTTON_THEME = _owned_theme(imgui_path_bar_theme())
    return _PATH_BUTTON_THEME


def file_toolbar_surface_theme():
    return imgui_tool_bar_theme()


def file_status_bar_theme():
    return imgui_status_bar_theme()


def file_status_text_theme(muted=False):
    return imgui_status_text_theme(muted=bool(muted))


class ResourceTextures:
    _textures = {}

    @classmethod
    def _registry(cls):
        global _RESOURCE_TEXTURE_REGISTRY
        if _RESOURCE_TEXTURE_REGISTRY is None or getattr(_RESOURCE_TEXTURE_REGISTRY, "_deleted", False):
            _RESOURCE_TEXTURE_REGISTRY = QTextureRegistry(visible=False)
        return _RESOURCE_TEXTURE_REGISTRY

    @classmethod
    def get(cls, name: str, pixel_size: int = DEFAULT_UI_TEXTURE_SIZE):
        requested_size = max(1, int(pixel_size or 0)) if pixel_size else 0
        base_key = str(name).casefold()
        key = (base_key if requested_size == DEFAULT_UI_TEXTURE_SIZE
               else "{}@{}".format(base_key, requested_size or "source"))
        if key in cls._textures:
            cached = cls._textures[key]
            if cached is None:
                return None
            if cached.exists():
                return cached.nativeId()
            cls._textures.pop(key, None)

        path = icon_path(name)
        if not path.is_file():
            cls._textures[key] = None
            return None
        if requested_size:
            optimized = RESOURCE_DIR / "ui" / "{}px".format(requested_size) / path.name
            if optimized.is_file():
                path = optimized
        texture = cls._registry().loadFile(path, tag="winux_texture_{}".format(len(cls._textures)))
        cls._textures[key] = texture
        return texture.nativeId() if texture is not None else None

    @classmethod
    def reset(cls):
        global _RESOURCE_TEXTURE_REGISTRY
        cls._textures.clear()
        registry, _RESOURCE_TEXTURE_REGISTRY = _RESOURCE_TEXTURE_REGISTRY, None
        if registry is not None:
            try:
                registry.delete()
            except Exception:
                pass


def reset_toolbar_runtime_resources():
    """Reset module caches after ``dpg.destroy_context()``."""
    global _MENU_THEME, _PATH_BUTTON_FONT, _PATH_BUTTON_THEME, _PATH_FONT_DB
    global _TOOLBAR_ICON_THEME, _TOOLBAR_FITTED_ICON_THEME, _TOOLBAR_TABLE_THEME
    global _SEARCH_POPUP_THEME, _SEARCH_INPUT_THEME, _SEARCH_CLOSE_THEME
    global _SEARCH_SHELL_THEME, _SEARCH_EDITOR_THEME

    ResourceTextures.reset()
    reset_tooltip_runtime_resources()
    for theme in (
        _TOOLBAR_ICON_THEME, _TOOLBAR_FITTED_ICON_THEME, _PATH_BUTTON_THEME,
        _MENU_THEME, _TOOLBAR_TABLE_THEME, _SEARCH_POPUP_THEME,
        _SEARCH_INPUT_THEME, _SEARCH_CLOSE_THEME, _SEARCH_SHELL_THEME,
        _SEARCH_EDITOR_THEME,
    ):
        if isinstance(theme, QTheme):
            try:
                theme.delete()
            except Exception:
                pass
    _TOOLBAR_ICON_THEME = None
    _TOOLBAR_FITTED_ICON_THEME = None
    _PATH_BUTTON_THEME = None
    _MENU_THEME = None
    _TOOLBAR_TABLE_THEME = None
    _SEARCH_POPUP_THEME = None
    _SEARCH_INPUT_THEME = None
    _SEARCH_CLOSE_THEME = None
    _SEARCH_SHELL_THEME = None
    _SEARCH_EDITOR_THEME = None
    _PATH_BUTTON_FONT = None
    if _PATH_FONT_DB is not None:
        try:
            _PATH_FONT_DB.delete()
        except Exception:
            pass
    _PATH_FONT_DB = None


def resource_menu_theme():
    """Shared QMenuBar/QMenu theme for legacy and main command menus."""
    global _MENU_THEME
    if _theme_alive(_MENU_THEME):
        return _MENU_THEME
    _MENU_THEME = _owned_theme(imgui_menu_bar_theme())
    return _MENU_THEME


def command_button_theme(checked=False, disabled=False):
    return imgui_command_button_theme(
        checked=bool(checked), disabled=bool(disabled))

class ResourceMenuBar:
    """Text-only top-level menus backed by the shared retained QMenu.

    Earlier builds used one hand-written popup window per root menu.  Reusing
    QMenu gives the application command bar the same row height, icon gutter,
    keyboard navigation and popup shielding as context menus and dock menus.
    """

    def __init__(self, menus):
        self.popups = []
        self.buttons = []
        self._commands = {}
        self._layout = QHBoxLayout(spacing=0)
        self.container = self._layout.tag
        for menu_index, (title, entries) in enumerate(menus):
            button = QPushButton(
                title, parent=self._layout, height=26, role="flat")
            self.buttons.append(button)
            popup = self._build_popup(menu_index, entries)
            self.popups.append(popup)
            button.clicked.connect(
                lambda popup=popup, button=button: self._show(popup, button))
        QRetainedItem(self.container).setTheme(resource_menu_theme())

    def _build_popup(self, menu_index, entries):
        actions = []
        commands = {}
        command_index = 0
        for entry in entries:
            if entry is None:
                actions.append({"separator": True, "label": "---",
                                "action": "sep_{}_{}".format(menu_index, command_index)})
                command_index += 1
                continue
            label, icon_name, command = entry
            action_id = "menu_{}_{}".format(menu_index, command_index)
            command_index += 1
            texture = ResourceTextures.get(icon_name)
            actions.append({
                "id": action_id,
                "label": label,
                "action": action_id,
                "icon": texture,
            })
            commands[action_id] = command
        popup = QMenu(actions, min_width=190, max_width=360)
        popup.triggered.connect(self._triggered)
        register_pointer_protected_item(popup.tag)
        self._commands.update(commands)
        return popup

    @staticmethod
    def _show(popup, button):
        try:
            tag = getattr(button, "tag", button)
            geometry = QRetainedItem(tag).globalGeometry()
            popup.popup((geometry.x(), geometry.y() + geometry.height()))
        except Exception:
            popup.popup()

    def _triggered(self, action, _context=None):
        command = self._commands.get(str(action))
        if callable(command):
            command()



def add_resource_button(parent, icon_name, callback, tooltip, *, user_data=None,
                        width=TOOLBAR_BUTTON_WIDTH,
                        height=TOOLBAR_BUTTON_HEIGHT):
    """Create a QToolButton-sized action with a centered resource icon.

    Dear PyGui's image-button ``width``/``height`` describe the image content,
    not the complete clickable frame.  The old hard-coded 18x18 content plus
    1 px padding produced a ~20 px button inside a 32 px toolbar cell, making
    every action look undersized and vertically adrift.  Keep a 22 px glyph
    and let the shared 4x3 frame padding form a stable 30x28 hit target.
    """
    width = max(20, int(width))
    height = max(20, int(height))
    texture = ResourceTextures.get(
        icon_name, pixel_size=TOOLBAR_TEXTURE_SIZE)
    if texture:
        icon_extent = min(
            TOOLBAR_ICON_SIZE,
            max(12, width - 8),
            max(12, height - 6),
        )
        button = QToolButton(
            "", parent=parent, icon=texture,
            icon_size=(icon_extent, icon_extent), auto_raise=True,
        )
        # Keep WinUx's resource-specific tint while DearUIQt owns the control
        # lifecycle, enabled state and click signal.
        try:
            QRetainedItem(button.tag).configure(
                tint_color=(70, 70, 70, 255)
                if icon_name == "Search" else (255, 255, 255, 255))
        except Exception:
            pass
    else:
        button = QToolButton(
            tooltip, parent=parent,
            width=width, height=height, auto_raise=True,
        )
    button.clicked.connect(
        lambda: callback(button.tag, None, user_data)
        if callable(callback) else None)
    button.setTheme(toolbar_icon_theme())
    add_styled_tooltip(button.tag, tooltip)
    return button


class FileToolbar:
    """Navigation toolbar shared by Local and Server file views."""

    COLLAPSED_HEIGHT = 36
    SEARCH_ROW_HEIGHT = 32
    # The outer QToolBar surface has 2 px vertical padding on each side and
    # the shared alignment spacer consumes another 2 px.  Keep the toolbar
    # table at the same 30 px it receives while collapsed instead of using
    # Dear ImGui ``height=-1`` fill semantics.  A fill-height table expands
    # to consume the newly-added search row whenever the toolbar grows from
    # 36 -> 68 px, which can collapse/clip the navigation controls.
    TOOLBAR_GRID_HEIGHT = COLLAPSED_HEIGHT - 4 - TOOLBAR_VERTICAL_OFFSET

    def __init__(self, parent, panel, callbacks, initial_path_label: str):
        self.panel = panel
        self.callbacks = callbacks
        self.search_visible = False

        self._container_frame = QFrame(
            parent=parent, width=-1, height=self.COLLAPSED_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.container = self._container_frame.tag
        self._container_frame.setTheme(file_toolbar_surface_theme())

        # Dear ImGui/Dear PyGui lays image buttons a touch high in a compact
        # table row compared with the visual centre of a Qt QToolBar.  Keep
        # the toolbar height unchanged and apply a tiny top-only alignment
        # shim before the table.  This lowers the navigation/path/search
        # controls together, so their baselines remain identical instead of
        # compensating each icon independently.
        if TOOLBAR_VERTICAL_OFFSET > 0:
            QSpacer(0, TOOLBAR_VERTICAL_OFFSET, parent=self._container_frame)

        self._toolbar_grid = QGridLayout(
            7, column_widths=(32, 32, 32, 32, 32, None, 32),
            parent=self._container_frame, height=self.TOOLBAR_GRID_HEIGHT)
        self.table = self._toolbar_grid.tag
        QRetainedItem(self.table).setTheme(toolbar_table_theme())

        navigation_items = (
            ("Left_Arrow", "back", "Back"),
            ("Right_Arrow", "forward", "Forward"),
            ("Open_Folder", "parent", "Parent folder"),
            ("Home", "home", "Home"),
            ("Refresh", "refresh", "Refresh"),
        )
        for column, (icon_name, action, tooltip) in enumerate(navigation_items):
            add_resource_button(
                self._toolbar_grid.cell(0, column).tag, icon_name,
                self._on_navigate, tooltip, user_data=action,
                width=TOOLBAR_BUTTON_WIDTH, height=TOOLBAR_BUTTON_HEIGHT,
            )

        self.path_button = QPushButton(
            initial_path_label, parent=self._toolbar_grid.cell(0, 5),
            width=-1, height=TOOLBAR_BUTTON_HEIGHT,
        )
        self.path_button.clicked.connect(lambda: callbacks["choose_path"](panel))
        self.path_button.setTheme(path_button_theme())
        path_font = path_button_font()
        if path_font is not None:
            self.path_button.setFont(path_font)
        add_styled_tooltip(self.path_button.tag, "Choose path")

        self.search_button = add_resource_button(
            self._toolbar_grid.cell(0, 6).tag, "Search", self._toggle_search,
            "Search / filter", width=TOOLBAR_BUTTON_WIDTH, height=TOOLBAR_BUTTON_HEIGHT,
        )

        # Keep search anchored to the top of the file pane, directly beneath
        # the navigation toolbar.  Unlike the floating popup, this can never
        # drift over the file list or cover rows when the pane is resized.
        self._search_popup_frame = QFrame(
            parent=self._container_frame, show=False, width=-1,
            height=self.SEARCH_ROW_HEIGHT, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self.search_popup = self._search_popup_frame.tag
        self._search_popup_frame.setTheme(search_popup_theme())
        # One framed search field, matching a Qt QLineEdit with embedded
        # leading search icon and trailing clear action. The old horizontal
        # group exposed three separate ImGui widgets and looked disconnected.
        self._search_shell_frame = QFrame(
            parent=self._search_popup_frame, width=-1, height=26,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.search_shell = self._search_shell_frame.tag
        self._search_shell_frame.setTheme(search_shell_theme())
        self._search_grid = QGridLayout(
            3, column_widths=(22, None, 24), parent=self._search_shell_frame, height=0)
        self.search_table = self._search_grid.tag
        search_texture = ResourceTextures.get("Search", pixel_size=32)
        leading = self._search_grid.cell(0, 0)
        if search_texture:
            QImageView(
                search_texture, parent=leading, width=16, height=16,
                tint=(90, 90, 90, 255))
        else:
            QSpacer(16, 16, parent=leading)
        self.search_input = QLineEdit(
            "", parent=self._search_grid.cell(0, 1), width=-1,
            placeholder="Search this folder", on_enter=False, auto_select_all=False,
        )
        self.search_input.textEdited.connect(self._on_search_text)
        self.search_input.setTheme(search_editor_theme())
        self.search_close = QPushButton(
            "x", parent=self._search_grid.cell(0, 2),
            width=20, height=20, role="flat")
        self.search_close.clicked.connect(self._hide_search)
        self.search_close.setTheme(search_close_theme())
        add_styled_tooltip(
            self.search_input.tag, "Filter the visible items in this folder")

    @property
    def height(self):
        return self.COLLAPSED_HEIGHT + (
            self.SEARCH_ROW_HEIGHT if self.search_visible else 0)

    # QToolBar-like retained properties.  These are behavior/style semantics
    # only; Dear PyGui remains the renderer.
    def setIconSize(self, size):
        if isinstance(size, (tuple, list)):
            size = min(int(size[0]), int(size[1]))
        self._icon_size = max(12, int(size))

    def iconSize(self):
        return int(getattr(self, "_icon_size", 20))

    def setMovable(self, movable):
        self._movable = bool(movable)

    def isMovable(self):
        return bool(getattr(self, "_movable", False))

    def setFloatable(self, floatable):
        self._floatable = bool(floatable)

    def isFloatable(self):
        return bool(getattr(self, "_floatable", False))

    def _focus_search_input(self):
        if not self.search_visible:
            return
        try:
            if not self.search_input._deleted:
                self.search_input.setFocus()
        except Exception:
            pass

    def _schedule_search_focus(self):
        # Focusing in the same frame that a hidden window becomes visible can
        # be ignored by Dear ImGui.  Focus again on the next rendered frame;
        # once active, ImGui supplies its normal blinking text caret.
        self._focus_search_input()
        try:
            runtime = QGuiRuntime()
            callback = lambda *_args, **_kwargs: self._focus_search_input()
            runtime.invokeAfterFrames(callback, 1)
            runtime.invokeAfterFrames(callback, 2)
        except Exception:
            pass

    def _show_search(self):
        self.search_visible = True
        try:
            self._search_popup_frame.show()
            self._container_frame.resize(-1, self.height)
            self.panel.toolbar_height_changed()
        except Exception:
            pass
        self._schedule_search_focus()

    def _close_search(self, clear=True):
        """Hide the search strip from application code.

        This helper is deliberately *not* registered as a Dear PyGui callback,
        so it may safely accept application-only options such as ``clear``.
        Dear PyGui's callback runner indexes the callback tuple based on the
        function signature and only supplies sender/app_data/user_data.
        """
        self.search_visible = False
        try:
            self._search_popup_frame.hide()
            self._container_frame.resize(-1, self.height)
            self.panel.toolbar_height_changed()
        except Exception:
            pass
        if clear:
            self.clear_search(apply=True)

    def _hide_search(self, sender=None, app_data=None, user_data=None):
        """Dear PyGui callback for the search-strip close button."""
        del sender, app_data, user_data
        self._close_search(clear=True)

    def _toggle_search(self, sender=None, app_data=None, user_data=None):
        del sender, app_data, user_data
        if self.search_visible:
            self._close_search(clear=True)
        else:
            self._show_search()

    def _on_navigate(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        callback = self.callbacks.get("navigate")
        if callback is not None and action:
            callback(self.panel, action)

    def _on_search(self, sender=None, app_data=None, user_data=None):
        value = app_data
        if value is None and not self.search_input._deleted:
            value = self.search_input.text()
        self.panel.apply_filter(str(value or ""))

    def _on_search_text(self, value):
        self.panel.apply_filter(str(value or ""))

    def clear_search(self, apply=False):
        if not self.search_input._deleted:
            self.search_input.clear()
        if apply:
            self.panel.apply_filter("")

    def set_path_text(self, text: str):
        if not self.path_button._deleted:
            self.path_button.setText(str(text))
