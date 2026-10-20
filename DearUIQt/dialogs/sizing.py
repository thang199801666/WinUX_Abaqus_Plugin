"""Pure Qt-style size hints for lightweight message and input dialogs.

Sizing intentionally does not inspect the native renderer: native item geometry
is not reliable during the first hidden QDialog construction transaction.
"""
from __future__ import annotations

from textwrap import wrap


# DearUIQt's dialog body font is 14 px.  Explicit/wrapped rows in a DPG text
# item advance by roughly 15 px; the old 19 px estimate accumulated a large
# empty band above the pinned button box on multi-line warnings/confirmations.
_COMPACT_BASE_HEIGHT = 148
_COMPACT_TEXT_LINE_HEIGHT = 15
_COMPACT_INPUT_HEIGHT = 36
_COMPACT_MAX_HEIGHT = 360


def _text_rows(text: str, columns: int) -> int:
    """Approximate wrapped text height, preserving explicit empty lines."""
    return sum(
        max(1, len(wrap(line.expandtabs(4), columns, break_long_words=True,
                        break_on_hyphens=False)))
        for line in (str(text or "").split("\n") or [""])
    )


def compact_message_size(message, *, heading="", kind="message", width=480):
    """Return a bounded (width, height) hint for a QMessageBox-like dialog.

    The hint includes one heading, body text, a permanently pinned footer and,
    for an input dialog, the editor. Excess text uses the body scrollbar; do
    not reduce the amount of text shown in the model or discard action rows.

    The estimate deliberately follows the *rendered text row* height instead
    of generic form-row spacing.  This keeps confirmations with file previews
    tight while preserving a small safety margin above the button box.
    """
    width = max(360, int(width))
    # The icon/spacing and window margins consume ~110 px of message width.
    # Segoe UI at the dialog body size averages about 6 px per character; using
    # 7 px here falsely wrapped ordinary warning sentences and over-sized them.
    columns = max(24, (width - 118) // 6)
    body_lines = _text_rows(message, columns)
    heading_lines = _text_rows(heading, columns)
    extra_lines = max(0, body_lines - 1) + max(0, heading_lines - 1)
    editor_height = _COMPACT_INPUT_HEIGHT if kind == "input" else 0
    height = (_COMPACT_BASE_HEIGHT
              + _COMPACT_TEXT_LINE_HEIGHT * extra_lines
              + editor_height)
    return width, min(_COMPACT_MAX_HEIGHT, height)


__all__ = ["compact_message_size"]
