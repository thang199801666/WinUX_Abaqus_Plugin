"""One typography setup for WinUx floating dialogs and detachable tools."""
from __future__ import annotations

import os
from pathlib import Path

from DearUIQt.themes import DialogMetrics
from DearUIQt.gui import QFontDatabase
from DearUIQt.runtime import QGuiRuntime
from ..resources import resource_path


def configure_ui_context(view):
    """Install the same Segoe UI fonts and UI-thread callback policy everywhere."""
    runtime = QGuiRuntime()
    runtime.configureApplication(manual_callback_management=True)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    body = fonts / "segoeui.ttf"
    if not body.is_file():
        return
    database = QFontDatabase()
    view._font_database = database
    body_font = database.addApplicationFont(body, DialogMetrics.BODY_FONT_SIZE)
    if body_font is None:
        return
    view.body_qfont = body_font
    view.body_font = body_font.nativeId()
    heading = fonts / "seguisb.ttf"
    if heading.is_file():
        qfont = database.addApplicationFont(heading, DialogMetrics.HEADING_FONT_SIZE)
        if qfont is not None:
            view.heading_qfont = qfont
            view.heading_font = qfont.nativeId()
    terminal = fonts / "consola.ttf"
    if terminal.is_file():
        qfont = database.addApplicationFont(terminal, DialogMetrics.BODY_FONT_SIZE)
        if qfont is not None:
            view.terminal_qfont = qfont
            view.terminal_font = qfont.nativeId()
    runtime.setApplicationFont(body_font)
    view.ui_font_family = "Segoe UI"
    view.ui_font_size = DialogMetrics.BODY_FONT_SIZE


def viewport_icon_options():
    """Use the WinUx application icon for every native tool/dialog viewport."""
    icon = resource_path("WinUx.ico")
    return {"small_icon": str(icon), "large_icon": str(icon)} if icon.is_file() else {}
