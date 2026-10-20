"""Reusable modeless inline text editor surface.

The component is intentionally generic: it hosts one primary QLineEdit and an
optional suffix QLineEdit inside a borderless QPopupPanel.  Feature code can
use it for Explorer-style rename, tree-node editing, compact spreadsheet
labels, or any transient one-line editor without owning renderer windows,
themes, focus or pointer-protection lifecycle.
"""
from __future__ import annotations

from ..core import QPoint, Signal
from ..gui import QFontMetrics
from ..input_gate import register_pointer_protected_item, unregister_pointer_protected_item
from ..themes import inline_editor_theme_spec
from .editors import QLineEdit
from .popup_panel import QPopupPanel


class QInlineEditPanel(QPopupPanel):
    """One-line popup editor with optional non-selected suffix field."""

    def __init__(self, text="", suffix="", *, position=(0, 0), max_width=320,
                 height=22, font=None, text_color=None, selection_color=None,
                 border=None, source_item=None, callback=None, backend=None,
                 after=None, parent=None, tag=None, input_tag=None,
                 suffix_tag=None, measure=None, font_binder=None):
        self._measure_callback = measure
        self._font_binder = font_binder
        self._font = font
        self._max_width = max(24, int(max_width))
        self._height = max(16, int(height))
        self._source_item = getattr(source_item, "tag", source_item)
        self._source_hidden = False
        self._external_callback = callback
        self.textEdited = Signal()

        backend = backend or getattr(parent, "backend", None)
        metrics = QFontMetrics(font, backend=backend)
        self._metrics = metrics
        base_width, suffix_width, total = self._measure_parts(text, suffix)
        super().__init__(
            width=total, height=self._height, min_width=24, max_width=self._max_width,
            min_height=self._height, max_height=self._height, backend=backend,
            after=after, parent=parent, tag=tag, bring_to_front_on_focus=True)
        self.textEdited.owner = self
        self._theme = inline_editor_theme_spec(
            text_color=text_color, selection_color=selection_color,
            border=border).createObject(parent=self, backend=self.backend)
        self.setTheme(self._theme)
        self.baseEditor = QLineEdit(
            str(text or ""), parent=self, tag=input_tag,
            width=base_width, pos=(2, 0), auto_select_all=True,
            callback=self._edited)
        self.suffixEditor = None
        if suffix:
            self.suffixEditor = QLineEdit(
                str(suffix), parent=self, tag=suffix_tag,
                width=suffix_width, pos=(2 + base_width, 0), auto_select_all=False,
                callback=self._edited)
        for editor in (self.baseEditor, self.suffixEditor):
            if editor is not None:
                editor.setTheme(self._theme)
                if font is not None:
                    if callable(self._font_binder):
                        try:
                            self._font_binder(editor.tag, font)
                        except Exception:
                            editor.setFont(font)
                    else:
                        editor.setFont(font)
        register_pointer_protected_item(self.tag)
        self._hide_source()
        self.showAt(position, clamp=False, focus=False)
        self.baseEditor.setFocus()

    def _measure(self, text):
        if callable(self._measure_callback):
            try:
                value = self._measure_callback(str(text or ""), self._font)
                return float(value[0] if isinstance(value, (tuple, list)) else value)
            except Exception:
                pass
        return float(self._metrics.horizontalAdvance(str(text or "")))

    def _measure_parts(self, base, suffix):
        base_width = max(12, int(round(self._measure(base or " ") + 4.0)))
        suffix_width = max(8, int(round(self._measure(suffix) + 4.0))) if suffix else 0
        total = max(24, min(self._max_width, base_width + suffix_width + 4))
        if base_width + suffix_width + 4 > total:
            available = max(12, total - 4)
            if suffix:
                suffix_width = min(suffix_width, max(8, available // 2))
            base_width = max(12, available - suffix_width)
        return base_width, suffix_width, total

    def _edited(self, sender=None, value=None, user_data=None):
        self.resizeToContents()
        combined = self.text()
        self.textEdited.emit(combined)
        callback = self._external_callback
        if callable(callback):
            try:
                callback(sender, value, user_data)
            except TypeError:
                try:
                    callback(combined)
                except TypeError:
                    callback()

    def text(self):
        base = self.baseEditor.text() if self.baseEditor is not None else ""
        suffix = self.suffixEditor.text() if self.suffixEditor is not None else ""
        return str(base) + str(suffix)

    def resizeToContents(self):
        base = self.baseEditor.text() if self.baseEditor is not None else ""
        suffix = self.suffixEditor.text() if self.suffixEditor is not None else ""
        base_width, suffix_width, total = self._measure_parts(base, suffix)
        self.baseEditor.resize(base_width, self._height)
        self.baseEditor.move(2, 0)
        if self.suffixEditor is not None:
            self.suffixEditor.resize(suffix_width, self._height)
            self.suffixEditor.move(2 + base_width, 0)
        self.resize(total, self._height)
        return total

    def refocus(self):
        if self._deleted or self.baseEditor is None or not self.baseEditor.exists():
            return False
        self.baseEditor.setFocus()
        return True

    def containsMouse(self):
        try:
            return bool(self.underMouse())
        except Exception:
            return False

    def _hide_source(self):
        tag = self._source_item
        if not tag:
            return
        try:
            if self.backend.does_item_exist(tag):
                self.backend.configure_item(tag, show=False)
                self._source_hidden = True
        except Exception:
            self._source_hidden = False

    def restoreSource(self):
        if not self._source_hidden or not self._source_item:
            self._source_hidden = False
            return
        try:
            if self.backend.does_item_exist(self._source_item):
                self.backend.configure_item(self._source_item, show=True)
        except Exception:
            pass
        self._source_hidden = False

    def delete(self):
        if self._deleted:
            return
        unregister_pointer_protected_item(self.tag)
        self.restoreSource()
        super().delete()


__all__ = ["QInlineEditPanel"]
