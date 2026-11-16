"""Photoshop-style closable tabs for WinUx remote login sessions."""
from __future__ import annotations

from DearUIQt.gui import QtFusionPalette
from DearUIQt.layouts import QHBoxLayout
from DearUIQt.themes import (
    ThemeColor, ThemeStyle, ThemeTarget, make_theme, theme_component,
)
from DearUIQt.widgets import QFrame, QPushButton, QToolButton


def _bar_theme():
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={
            ThemeColor.CHILD_BACKGROUND: QtFusionPalette.WINDOW,
            ThemeColor.BORDER: QtFusionPalette.BORDER_LIGHT,
            ThemeColor.TEXT: QtFusionPalette.TEXT,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (3, 2),
            ThemeStyle.ITEM_SPACING: (2, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0,
        },
    ))


def _button_theme(*, active=False, close=False, new=False):
    p = QtFusionPalette
    if new:
        base = (0, 0, 0, 0)
        hover = p.BUTTON_HOVER
        pressed = p.BUTTON_ACTIVE
        border = (0, 0, 0, 0)
        rounding = 3
    elif close:
        # Photoshop/Windows-style close affordance: neutral at rest, danger red
        # only when hovered/pressed so accidental-close risk is visually clear.
        base = p.BASE if active else p.WINDOW
        hover = p.DANGER
        pressed = p.DANGER_ACTIVE
        border = p.BORDER_LIGHT if active else (0, 0, 0, 0)
        rounding = 3
    elif active:
        # Keep the active document stable while still acknowledging pointer
        # interaction with a very small hover lift.
        base = p.BASE
        hover = p.HIGHLIGHT_SOFT
        pressed = p.HIGHLIGHT_HOVER
        border = p.BORDER_LIGHT
        rounding = 3
    else:
        # WINDOW_ALT was too close to WINDOW and made hover almost invisible.
        # Use the common control hover palette so inactive tabs visibly lift
        # under the mouse without becoming as strong as the active tab.
        base = p.WINDOW
        hover = p.BUTTON_HOVER
        pressed = p.BUTTON_ACTIVE
        border = p.BORDER_LIGHT
        rounding = 3
    pad_x = 3 if close else 8
    return make_theme(
        theme_component(
            ThemeTarget.PUSH_BUTTON,
            colors={
                ThemeColor.BUTTON: base,
                ThemeColor.BUTTON_HOVERED: hover,
                ThemeColor.BUTTON_ACTIVE: pressed,
                ThemeColor.TEXT: p.TEXT,
                ThemeColor.BORDER: border,
            },
            styles={
                ThemeStyle.FRAME_PADDING: (pad_x, 2),
                ThemeStyle.FRAME_BORDER_SIZE: 1 if (active or (not new and not close)) else 0,
                ThemeStyle.FRAME_ROUNDING: rounding,
            },
        ),
        theme_component(
            ThemeTarget.IMAGE_BUTTON,
            colors={
                ThemeColor.BUTTON: base,
                ThemeColor.BUTTON_HOVERED: hover,
                ThemeColor.BUTTON_ACTIVE: pressed,
                ThemeColor.BORDER: border,
            },
            styles={
                ThemeStyle.FRAME_PADDING: (pad_x, 2),
                ThemeStyle.FRAME_BORDER_SIZE: 1 if (active or (not new and not close)) else 0,
                ThemeStyle.FRAME_ROUNDING: rounding,
            },
        ),
    )


class SessionTabStrip:
    """Small retained tab bar; content ownership remains in the main workspace."""

    HEIGHT = 27
    TAB_WIDTH = 146
    CLOSE_WIDTH = 20
    CONTROL_HEIGHT = 22

    def __init__(self, parent, *, on_activate, on_close, on_new):
        self.on_activate = on_activate
        self.on_close = on_close
        self.on_new = on_new
        self._signature = None
        self._active_id = None
        self._rows = {}
        self._frame = QFrame(
            parent=parent, pos=(0, 0), width=-1, height=self.HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False)
        self._frame.setTheme(_bar_theme())
        self.tag = self._frame.tag
        self._layout = QHBoxLayout(parent=self._frame, spacing=1)
        self._layout.setContentsMargins(3, 2, 3, 2)
        self._new_button = QToolButton(
            "+", parent=self._layout, width=24, height=self.CONTROL_HEIGHT, auto_raise=False)
        self._new_button.setTheme(_button_theme(new=True))
        self._new_button.setToolTip("New login session")
        self._new_button.clicked.connect(self._new_clicked)

    def _new_clicked(self):
        if callable(self.on_new):
            self.on_new()

    @staticmethod
    def _tab_label(data):
        account = str(data.get("account_label") or "")
        if not account:
            username = str(data.get("username") or "")
            host = str(data.get("host") or "")
            account = "{}@{}".format(username, host) if username and host else (host or username)
        if not account:
            account = str(data.get("short_id") or data.get("session_id") or "Session")[:18]
        state = str(data.get("state") or "")
        if state == "connecting":
            return "…  {}".format(account)
        if state == "reconnecting":
            return "↻  {}".format(account)
        return account

    def isVisible(self):
        return self._frame.isVisible()

    def setGeometry(self, x, y, width, height=None):
        height = self.HEIGHT if height is None else max(1, int(height))
        width = max(1, int(width))
        self._frame.setGeometry(int(x), int(y), width, height)
        # Photoshop compresses document tabs before overflowing. Keep the close
        # glyph permanently reachable while allowing labels to clip naturally.
        count = max(1, len(self._rows))
        available = max(1, width - 30 - max(0, count - 1))
        pair_width = max(88, min(self.TAB_WIDTH + self.CLOSE_WIDTH, available // count))
        label_width = max(64, pair_width - self.CLOSE_WIDTH)
        for row in self._rows.values():
            try:
                row["tab"].setFixedWidth(label_width)
                row["close"].setFixedWidth(self.CLOSE_WIDTH)
            except Exception:
                pass

    def _clear_rows(self):
        for row in tuple(self._rows.values()):
            try:
                row["layout"].delete()
            except Exception:
                pass
        self._rows.clear()

    def set_sessions(self, snapshot):
        data = snapshot if isinstance(snapshot, dict) else {}
        sessions = list(data.get("sessions") or ())
        active_id = str(data.get("active_session_id") or "")
        signature = tuple(str(item.get("session_id") or "") for item in sessions)
        visible_before = self._frame.isVisible()
        visible_after = bool(sessions)

        structure_changed = signature != self._signature
        if structure_changed:
            self._clear_rows()
            # The + button already exists as a child of the layout. Newly added
            # tab rows are appended after it by default; move + back to the end
            # after rebuilding so it behaves like Photoshop's new-document tab.
            for item in sessions:
                sid = str(item.get("session_id") or "")
                row = QHBoxLayout(parent=self._layout, spacing=0)
                tab = QPushButton(
                    self._tab_label(item), parent=row, width=self.TAB_WIDTH,
                    height=self.CONTROL_HEIGHT, checkable=True)
                tab.setToolTip(
                    "{}:{}\nSession {}".format(
                        item.get("host") or "?", item.get("port") or 22,
                        sid[:8] or "?"))
                tab.clicked.connect(
                    lambda _sid=sid: self.on_activate(_sid)
                    if callable(self.on_activate) else None)
                close = QToolButton(
                    "×", parent=row, width=self.CLOSE_WIDTH, height=self.CONTROL_HEIGHT,
                    auto_raise=False)
                close.setToolTip("Close session")
                tab.setTheme(_button_theme(active=False))
                close.setTheme(_button_theme(active=False, close=True))
                close.clicked.connect(
                    lambda _sid=sid: self.on_close(_sid)
                    if callable(self.on_close) else None)
                self._rows[sid] = {"layout": row, "tab": tab, "close": close}
            try:
                # QBoxLayout moves the existing widget without recreating it.
                self._layout.addWidget(self._new_button)
            except Exception:
                pass
            self._signature = signature

        self._active_id = active_id
        by_id = {str(item.get("session_id") or ""): item for item in sessions}
        for sid, row in self._rows.items():
            try:
                active = sid == active_id
                row["tab"].setText(self._tab_label(by_id.get(sid, {})))
                row["tab"].setChecked(active)
                row["tab"].setTheme(_button_theme(active=active))
                row["close"].setTheme(_button_theme(active=active, close=True))
            except Exception:
                pass
        self._frame.setVisible(visible_after)
        return structure_changed or visible_before != visible_after

    def apply_theme(self):
        self._frame.setTheme(_bar_theme())
        self._new_button.setTheme(_button_theme(new=True))
        for sid, row in self._rows.items():
            active = sid == self._active_id
            row["tab"].setTheme(_button_theme(active=active))
            row["close"].setTheme(_button_theme(active=active, close=True))


__all__ = ["SessionTabStrip"]
