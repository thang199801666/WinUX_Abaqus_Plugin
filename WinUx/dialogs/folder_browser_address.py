"""A single Windows-style address field that switches breadcrumbs/editor."""
from pathlib import Path

from .folder_browser_style import (
    METRICS, browser_surface_theme, browser_layout_theme,
    browser_field_shell_theme, browser_icon_slot_theme, browser_embedded_editor_theme,
    browser_breadcrumb_button_theme, browser_breadcrumb_blank_theme,
    create_breadcrumb_chevron, address_location_texture,
    folder_item_texture, navigation_texture,
)
from DearUIQt.gui import QFontMetrics
from DearUIQt.tooltip import add_styled_tooltip
from DearUIQt.widgets import QPushButton, QFrame, QImageView, QMenu, QToolButton
from DearUIQt.core import QItemInputBinding
from DearUIQt.layouts import QHBoxLayout, QGridLayout


def sync_editor_draft(control):
    """Reconcile a line edit's retained cache with an uncommitted native draft.

    DearUIQt caches the last programmatic ``setText`` value, but native edits
    typed without Return never raise the item callback that updates that
    cache.  A later ``setText`` with the cached value is then deduped and the
    uncommitted draft survives (Escape-restore and filter reset regressions).
    """
    try:
        control._user_value(control.text())
    except Exception:
        pass


def set_editor_text(control, value):
    """QLineEdit::setText that also discards an uncommitted native draft."""
    sync_editor_draft(control)
    control.setText(value)


class FolderAddressBar:
    """QFileDialog-like address bar built only from DearUIQt public widgets."""

    def __init__(self, dialog, parent, *, breadcrumbs=False):
        self.dialog = dialog
        self._plain_location = not breadcrumbs
        self.editing = False
        self._last_layout = None
        self._last_valid_width = 0.0
        self._metrics = QFontMetrics()
        self._segment_theme = browser_breadcrumb_button_theme()
        self._blank_theme = browser_breadcrumb_blank_theme()
        self._normal_theme = browser_field_shell_theme(focused=False)
        self._focus_theme = browser_field_shell_theme(focused=True)
        self._frame = QFrame(
            parent=parent, width=-1, height=METRICS.location_height,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.tag = self._frame.tag
        self._frame.setTheme(self._normal_theme)
        self._grid = QGridLayout(
            3, column_widths=(20, None, METRICS.control_height - 2), parent=self._frame, height=0)
        self._grid.setTheme(browser_layout_theme(cell_padding=(1, 0)))

        self._icon_frame = QFrame(
            parent=self._grid.cell(0, 0), width=22, height=METRICS.location_height - 2,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self._icon_frame.setTheme(browser_icon_slot_theme())
        self._icon_view = QImageView(
            address_location_texture(dialog._current_path, size=16),
            parent=self._icon_frame, width=16, height=16,
            pos=(1, max(0, (METRICS.location_height - 18) // 2)))
        self.icon = self._icon_view.tag

        self._body_frame = QFrame(
            parent=self._grid.cell(0, 1), width=-1, height=METRICS.location_height - 2,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.body = self._body_frame.tag
        self._body_frame.setTheme(browser_surface_theme(
            cell_padding=(1, 0), spacing=(0, 0)))
        self._breadcrumb_layout = QHBoxLayout(
            parent=self._body_frame, spacing=0)
        self.breadcrumbs = self._breadcrumb_layout.tag
        self._editor_control = dialog.line_edit_widget(
            dialog._current_path, parent=self._body_frame, width=-1,
            pos=(0, 0), on_enter=True, auto_select_all=True,
            callback=lambda *_args: dialog._navigate_typed())
        self._editor_control.setTheme(browser_embedded_editor_theme(self._metrics.height()))
        if self._plain_location:
            self._breadcrumb_layout.hide()
        else:
            self._editor_control.hide()
        self.editor = self._editor_control.tag
        self._arrow_control = QToolButton(
            '', parent=self._grid.cell(0, 2), icon=navigation_texture('Edit address'),
            icon_size=(METRICS.icon_size, METRICS.icon_size),
            width=METRICS.control_height - 2, height=METRICS.control_height - 2)
        self._arrow_control.setTheme(dialog._navigation_theme)
        self._arrow_control.clicked.connect(self._show_locations if self._plain_location else self.begin_edit)
        self.edit_button = self._arrow_control.tag
        self._focus_binding = (QItemInputBinding(self._editor_control, parent=dialog)
                               .onFocus(self._refresh_focus).onActivated(self._refresh_focus)
                               .onDeactivated(self._refresh_focus).activate())
        self._locations = QMenu(parent=dialog, parent_window=dialog.tag,
                                after=dialog.view.after, min_width=240, max_width=1600)
        self._locations.triggered.connect(self._location_selected)
        self.refresh(force=True)

    def _refresh_focus(self, *_args):
        focused = self._editor_control.hasFocus() or self._editor_control.isActive()
        self._frame.setTheme(self._focus_theme if focused else self._normal_theme)

    def _show_locations(self):
        # Lexical history/parents only: never enumerate or probe a disk/share
        # merely to open the Qt-style location dropdown.
        path = Path(self.dialog._current_path)
        candidates = [str(path), *(str(p) for p in path.parents),
                      *reversed(self.dialog._back_paths),
                      *self.dialog._place_items]
        paths = list(dict.fromkeys(candidates))
        # Anchor the list to the address field, not to the renderer's default
        # popup origin (which can place it outside/below the file dialog).
        rect = self._frame.globalGeometry()
        width = max(240, int(rect.width()))
        menu = self._locations
        menu._min_width = width
        menu._max_width = width
        # QMenu supports native texture IDs in action specs.  Use the same
        # Shell folder icon as the file list; drive roots get the chooser's
        # drive texture.  Reuse the two shared textures for every opening
        # instead of retrieving an icon per history entry/network path.
        folder_icon = folder_item_texture(16)
        actions = [
            {"label": value, "action": value,
             "icon": (address_location_texture(value, size=16)
                      if Path(value).anchor == value else folder_icon)}
            for value in paths
        ]
        menu.setActions(actions)
        # QMenu.popup converts global coordinates to its parent-window space.
        # In particular, do not pass the address field's local widget position.
        menu.popup((rect.left(), rect.bottom()))

    def _location_selected(self, path, _context=None):
        self.dialog.view.after(1, self.dialog._navigate, str(path))

    def begin_edit(self):
        self.editing = True
        self._breadcrumb_layout.hide()
        self._editor_control.show()
        sync_editor_draft(self._editor_control)
        self._editor_control.setText(self.dialog._current_path)
        self._frame.setTheme(self._focus_theme)
        self._editor_control.setFocus()

    def end_edit(self):
        self.editing = False
        self._editor_control.setVisible(self._plain_location)
        self._breadcrumb_layout.setVisible(not self._plain_location)
        sync_editor_draft(self._editor_control)
        self._editor_control.setText(self.dialog._current_path)
        self.refresh(force=True)
        self._frame.setTheme(self._normal_theme)

    def _width(self, text):
        return float(self._metrics.horizontalAdvance(str(text or "")))

    def _available_width(self):
        """Return address-body width without assuming the item has rendered."""
        available = 0.0
        try:
            available = float(self._body_frame.globalGeometry().width() or 0.0)
        except Exception:
            available = 0.0
        if available >= 40:
            self._last_valid_width = available
            return available
        if self._last_valid_width >= 40:
            return self._last_valid_width

        preferred = getattr(self.dialog, "preferred_size", None)
        dialog_width = 0.0
        if isinstance(preferred, (tuple, list)) and len(preferred) >= 1:
            try:
                dialog_width = float(preferred[0] or 0.0)
            except (TypeError, ValueError, IndexError, OverflowError):
                dialog_width = 0.0
        if dialog_width <= 0:
            try:
                dialog_width = float(self.dialog.width() or 0.0)
            except Exception:
                dialog_width = 0.0
        return max(180.0, dialog_width - 425.0) if dialog_width > 0 else 320.0

    def _fit(self, text, available):
        if self._width(text) <= available:
            return text
        while text and self._width(text + "...") > available:
            text = text[:-1]
        return text + "..." if text else "..."

    def refresh(self, force=False):
        if not self._frame.exists():
            return
        if self._plain_location:
            if not (self.editing or self._editor_control.hasFocus() or self._editor_control.isActive()):
                set_editor_text(self._editor_control, self.dialog._current_path)
            return
        available = self._available_width()
        stamp = (self.dialog._current_path, int(available))
        if not force and stamp == self._last_layout:
            return
        self._last_layout = stamp
        self._breadcrumb_layout.clear(delete=True)
        path = Path(self.dialog._current_path)
        chain = list(reversed(path.parents)) + [path]
        visible = [chain[-1]]
        used = min(self._width(path.name or path.anchor) + 14, available * 0.6)
        for ancestor in reversed(chain[:-1]):
            width = self._width(ancestor.name or ancestor.anchor) + 28
            if used + width + 26 > available:
                break
            visible.insert(0, ancestor)
            used += width
        if len(visible) < len(chain):
            control = QPushButton(
                "...", parent=self._breadcrumb_layout, width=24,
                height=METRICS.location_height - 3)
            control.clicked.connect(self.begin_edit)
            control.setTheme(self._segment_theme)
            add_styled_tooltip(control.tag, self.dialog._current_path)
        budget = max(24, available - (26 if len(visible) < len(chain) else 0))
        for index, ancestor in enumerate(visible):
            if index or len(visible) < len(chain):
                create_breadcrumb_chevron(self._breadcrumb_layout)
                budget -= 11
            full_label = ancestor.name or ancestor.anchor
            remaining = len(visible) - index - 1
            width = max(24, min(self._width(full_label) + 14,
                                budget - remaining * 40))
            label = self._fit(full_label, max(8, width - 12))
            control = QPushButton(
                label, parent=self._breadcrumb_layout, width=int(width),
                height=METRICS.location_height - 3)
            control.clicked.connect(lambda p=str(ancestor): self.dialog._navigate(p))
            control.setTheme(self._segment_theme)
            add_styled_tooltip(control.tag, str(ancestor))
            budget -= width
        if budget > 4:
            control = QPushButton(
                "", parent=self._breadcrumb_layout, width=int(budget),
                height=METRICS.location_height - 3)
            control.clicked.connect(self.begin_edit)
            control.setTheme(self._blank_theme)
