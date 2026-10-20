"""Multiline text editor widgets.

DearUIQt's current Dear PyGui backend is plain-text oriented.  QTextEdit keeps a
Qt-compatible surface while deliberately rendering text as plain text; rich
text APIs retain their payload but do not attempt HTML layout in the backend.
"""
from __future__ import annotations

from .editors import QPlainTextEdit


class QTextEdit(QPlainTextEdit):
    """QTextEdit-compatible multiline editor over the native InputText widget."""

    def __init__(self, text="", *, accept_rich_text=False, **kwargs):
        super().__init__(text, **kwargs)
        self._accept_rich_text = bool(accept_rich_text)
        self._html = None

    def setText(self, text):
        self._html = None
        return super().setText(text)

    def setPlainText(self, text):
        self._html = None
        return super().setPlainText(text)

    def setHtml(self, html):
        # Keep the source so callers can round-trip it.  The Dear PyGui renderer
        # intentionally displays it as plain text until a rich-text backend is
        # introduced.
        self._html = str(html or "")
        return super().setPlainText(self._html)

    def toHtml(self):
        return self._html if self._html is not None else self.toPlainText()

    def setAcceptRichText(self, enabled):
        self._accept_rich_text = bool(enabled)

    def acceptRichText(self):
        return self._accept_rich_text

    def append(self, text):
        return self.appendPlainText(text)

    def insertHtml(self, html):
        return self.insertPlainText(str(html or ""))


__all__ = ["QTextEdit"]
