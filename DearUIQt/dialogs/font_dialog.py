"""Reusable Qt-style font selector built from DearUIQt retained widgets."""
from __future__ import annotations

from dataclasses import dataclass

from ..backends import get_backend
from ..core import Qt
from ..gui import QFontDatabase, QFontMetrics
from ..layouts import QHBoxLayout, QVBoxLayout
from ..modelview import QListWidget
from ..widgets import QLabel, QLineEdit, QPushButton, QSpacer, QComboBox
from .qt_dialog import QtDialog


@dataclass(frozen=True)
class QFontSelection:
    family: str
    style: str
    size: int
    script: str = "Western"


class QFontDialog(QtDialog):
    """Windows-like font selector with live preview.

    The application supplies family/style discovery and face resolution so the
    reusable DearUIQt layer never depends on an application-specific font store.
    All geometry is derived from the active body font metrics.
    """

    REUSABLE_HOST = True
    DEFAULT_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72)

    def __init__(self, view, *, families, styles_provider, face_resolver,
                 family="", style="Regular", size=12, scripts=("Western",),
                 sample="AaBbYyZz 012345", minimum_size=6, maximum_size=144,
                 on_selected=None, parent=None):
        self._families = tuple(dict.fromkeys(str(v) for v in families if str(v).strip()))
        self._styles_provider = styles_provider
        self._face_resolver = face_resolver
        self._minimum_size = max(1, int(minimum_size))
        self._maximum_size = max(self._minimum_size, int(maximum_size))
        self._scripts = tuple(str(v) for v in scripts if str(v).strip()) or ("Western",)
        self._sample_text = str(sample or "Sample")
        self._on_selected = on_selected
        self._updating = False
        self._preview_database = None
        self._preview_fonts = {}
        self._row_fonts = {}

        metrics = QFontMetrics(getattr(view, "body_qfont", None))
        line = max(1, int(metrics.lineSpacing()))
        pad = max(8, int(round(line * .72)))
        family_text_width = max((metrics.horizontalAdvance(name) for name in self._families),
                                default=metrics.horizontalAdvance("Segoe UI"))
        # Match the proportions of the native Windows Font dialog while still
        # deriving every dimension from the current application font metrics.
        family_width = max(metrics.horizontalAdvance("Arial Unicode MS") + pad * 4,
                           min(300, family_text_width + pad * 2))
        style_width = max(metrics.horizontalAdvance("Narrow Bold Italic") + pad * 3,
                          int(round(family_width * .62)))
        size_width = max(metrics.horizontalAdvance("144") + pad * 3,
                         int(round(family_width * .34)))
        column_gap = max(8, int(round(line * .62)))
        outer_pad = max(12, int(round(line * .86)))
        dialog_width = family_width + style_width + size_width + column_gap * 2 + outer_pad * 2
        dialog_height = max(int(round(line * 42.0)), 620)
        super().__init__(view, "Font", dialog_width, dialog_height, parent=parent,
                         compact=False, resizable=True)
        self.setMinimumSize(max(460, dialog_width), max(560, line * 32))

        # QFontDialog deliberately avoids QGridLayout/QFormLayout/QDialogButtonBox.
        # Those abstractions are implemented with Dear PyGui tables, and nested
        # top-level dialog creation can otherwise re-enter mvTable construction on
        # some Win32 input-dispatch paths.  Box layouts use native groups only.
        self._columns = self.own_widget(QHBoxLayout(
            parent=self._qt_parent(self.content), after=view.after, backend=get_backend(),
            spacing=column_gap))

        self._family_column = self._font_column(
            self._columns, family_width, "Font:",
            family or (self._families[0] if self._families else ""), readonly=False)
        self._style_column = self.own_widget(QVBoxLayout(
            parent=self._columns, after=view.after, backend=get_backend(),
            spacing=max(3, line // 4)))
        self._columns.addLayout(self._style_column)
        self.own_widget(QLabel(
            "Font style:", parent=self._style_column, after=view.after, backend=get_backend()))
        initial_family = family or (self._families[0] if self._families else "")
        initial_styles = self._normalized_style_options(initial_family)
        initial_style = next(
            (name for name in initial_styles if name.casefold() == str(style or "Regular").casefold()),
            initial_styles[0] if initial_styles else "Regular")
        self.style_combo = self.own_widget(QComboBox(
            initial_styles, current=initial_style, parent=self._style_column,
            after=view.after, backend=get_backend(), editable=False, width=style_width))
        self.style_combo.setMaxVisibleItems(10)
        self.style_combo.setPopupParent(self.tag)
        self._remember_focusable(self.style_combo.tag)
        self._style_spacer = self.own_widget(QSpacer(
            width=style_width, height=max(line * 10, 160), parent=self._style_column,
            after=view.after, backend=get_backend()))
        self._style_column.addWidget(self._style_spacer)

        self._size_column = self._font_column(
            self._columns, size_width, "Size:", str(int(size)), readonly=False)

        self._family_editor = self._family_column[1]
        self._size_editor = self._size_column[1]

        self.family_list = self.own_widget(QListWidget(
            parent=self._family_column[0], after=view.after, backend=get_backend(),
            width=family_width, visible_rows=13))
        self.size_list = self.own_widget(QListWidget(
            parent=self._size_column[0], after=view.after, backend=get_backend(),
            width=size_width, visible_rows=13))
        family_items = self.family_list.addItems(self._families)
        # Do not preload every installed face here. Dear PyGui rebuilds its font
        # atlas for application fonts, and loading hundreds of Windows faces in
        # one constructor can terminate the native process. Row face preview is
        # applied lazily only to the current family.
        sizes = sorted(set(self.DEFAULT_SIZES + (int(size),)))
        self.size_list.addItems(str(v) for v in sizes if self._minimum_size <= v <= self._maximum_size)

        self._family_editor.textEdited.connect(self._filter_families, receiver=self)
        self._family_editor.returnPressed.connect(self._commit_typed_family, receiver=self)
        self._size_editor.textEdited.connect(self._size_text_edited, receiver=self)
        self._size_editor.returnPressed.connect(self._commit_typed_size, receiver=self)
        self.family_list.itemClicked.connect(self._family_clicked, receiver=self)
        self.style_combo.currentTextChanged.connect(self._style_changed, receiver=self)
        self.size_list.itemClicked.connect(self._size_clicked, receiver=self)
        self.family_list.currentItemChanged.connect(
            lambda item, _old: self._family_clicked(item) if item is not None else None, receiver=self)
        self.size_list.currentItemChanged.connect(
            lambda item, _old: self._size_clicked(item) if item is not None else None, receiver=self)
        self.family_list.itemDoubleClicked.connect(lambda _item: self._accept(), receiver=self)
        self.size_list.itemDoubleClicked.connect(lambda _item: self._accept(), receiver=self)

        # Match Windows' lower silhouette: blank region under Font, with
        # Sample and Script aligned beneath the style/size columns.
        lower_right_width = style_width + size_width + column_gap
        self._lower = self.own_widget(QHBoxLayout(
            parent=self._qt_parent(self.content), after=view.after, backend=get_backend(),
            spacing=column_gap))
        self._lower_blank = self.own_widget(QSpacer(
            width=family_width, height=max(line * 7, 96),
            parent=self._lower, after=view.after, backend=get_backend()))
        self._lower.addWidget(self._lower_blank)

        self._lower_right = self.own_widget(QVBoxLayout(
            parent=self._lower, after=view.after, backend=get_backend(), spacing=max(5, line // 3)))
        self._lower.addLayout(self._lower_right)

        with self.section("Sample", parent=self._lower_right) as preview_parent:
            preview_pad = max(8, int(round(line * .65)))
            self.own_widget(QSpacer(
                width=lower_right_width, height=preview_pad,
                parent=self._qt_parent(preview_parent), after=view.after, backend=get_backend()))
            self._preview_label = self.own_widget(QLabel(
                self._sample_text, parent=self._qt_parent(preview_parent),
                after=view.after, backend=get_backend()))
            self._preview_label.setAlignment(Qt.AlignCenter)
            self._preview_label.setMinimumWidth(max(1, lower_right_width - preview_pad * 2))
            self._preview_label.setMinimumHeight(max(line * 3, int(round(line * 3.6))))
            self.own_widget(QSpacer(
                width=lower_right_width, height=preview_pad,
                parent=self._qt_parent(preview_parent), after=view.after, backend=get_backend()))

        self._script_box = self.own_widget(QVBoxLayout(
            parent=self._lower_right, after=view.after, backend=get_backend(), spacing=max(3, line // 4)))
        self._lower_right.addLayout(self._script_box)
        self.own_widget(QLabel(
            "Script:", parent=self._script_box, after=view.after, backend=get_backend()))
        self.script_combo = self.combo(
            self._scripts, parent=self._script_box, default_value=self._scripts[0],
            width=max(metrics.horizontalAdvance("Western") + pad * 7, lower_right_width))

        # A table-free footer avoids the final mvTable construction path as well.
        self._footer_layout = self.own_widget(QHBoxLayout(
            parent=self._qt_parent(self.footer), after=view.after, backend=get_backend(),
            spacing=max(8, int(round(line * .55)))))
        # Use the layout's expanding stretch rather than a fixed spacer so the
        # action buttons remain anchored to the lower-right edge after resize.
        self._footer_stretch = self._footer_layout.addStretch(1)
        self._ok_button = self.own_widget(QPushButton(
            "OK", parent=self._footer_layout, after=view.after, backend=get_backend(),
            width=self.action_width("OK"), height=self.action_height(), role="primary", default=True))
        self._cancel_button = self.own_widget(QPushButton(
            "Cancel", parent=self._footer_layout, after=view.after, backend=get_backend(),
            width=self.action_width("Cancel"), height=self.action_height(), role="secondary"))
        self._footer_layout.addWidget(self._ok_button)
        self._footer_layout.addWidget(self._cancel_button)
        self._ok_button.clicked.connect(self._accept, receiver=self)
        self._cancel_button.clicked.connect(self.destroy, receiver=self)
        self._remember_focusable(self._ok_button.tag)
        self._remember_focusable(self._cancel_button.tag)

        self._select_initial(family, style, int(size))
        self._refresh_preview()

    def _font_column(self, row_layout, width, label, value, readonly=False):
        column = self.own_widget(QVBoxLayout(
            parent=row_layout, after=self.view.after, backend=get_backend(),
            spacing=max(3, QFontMetrics(getattr(self.view, "body_qfont", None)).lineSpacing() // 4)))
        row_layout.addLayout(column)
        self.own_widget(QLabel(
            label, parent=column, after=self.view.after, backend=get_backend()))
        editor = self.own_widget(QLineEdit(
            str(value), parent=column, after=self.view.after, backend=get_backend(),
            width=int(width), readonly=readonly))
        self._remember_focusable(editor.tag)
        return column, editor

    @staticmethod
    def _item_text(item):
        return item.text() if item is not None else ""

    def _set_editor(self, editor, value):
        self._updating = True
        try:
            editor.setText(str(value))
        finally:
            self._updating = False

    def _set_list_values(self, widget, values, selected=None):
        widget.clear()
        items = widget.addItems(values)
        if not items:
            return None
        selected_text = str(selected or "")
        target = next((item for item in items if item.text().casefold() == selected_text.casefold()), items[0])
        widget.setCurrentItem(target)
        return target

    def _ensure_font_database(self):
        if self._preview_database is None:
            self._preview_database = QFontDatabase(parent=self, backend=get_backend())
        return self._preview_database

    def _resolve_preview_font(self, family, style, size):
        try:
            resolved = self._face_resolver(family, style)
            path = resolved[-1] if isinstance(resolved, (tuple, list)) else resolved
        except Exception:
            path = None
        if not path:
            return None
        try:
            from pathlib import Path
            candidate = Path(str(path))
            # Dear PyGui/ImGui font-atlas loading is most reliable for a single
            # TTF/OTF face. Skip collections and unusually large/corrupt-looking
            # files rather than risking a native process termination.
            if candidate.suffix.lower() not in {".ttf", ".otf"}:
                return None
            if candidate.stat().st_size > 32 * 1024 * 1024:
                return None
        except Exception:
            return None
        key = (str(path), int(size))
        font = self._row_fonts.get(key) or self._preview_fonts.get(key)
        if font is not None:
            return font
        font = self._ensure_font_database().addApplicationFont(path, int(size))
        if font is not None:
            self._row_fonts[key] = font
        return font

    def _bind_current_family_row_font(self, item):
        """Best-effort face preview for the current row only.

        Never bulk-load the installed font catalog: native font-atlas rebuilds
        are intentionally bounded to one selected face at a time.
        """
        if item is None:
            return False
        native = self.family_list.items.get(item.key)
        if native is None:
            return False
        try:
            row_size = int(round(float(self._size_editor.text())))
        except Exception:
            row_size = 12
        row_size = max(11, min(16, row_size))
        font = self._resolve_preview_font(item.text(), "Regular", row_size)
        if font is None:
            return False
        binder = getattr(get_backend(), "bind_item_font", None)
        if not callable(binder):
            return False
        try:
            binder(native, font.nativeId())
            return True
        except Exception:
            return False

    def _normalized_style_options(self, family):
        styles = list(self._styles_provider(family) or ("Regular",))
        standard = ("Regular", "Bold", "Italic", "Bold Italic")
        ordered = []
        for name in standard:
            if name not in ordered:
                ordered.append(name)
        for name in styles:
            if name not in ordered:
                ordered.append(name)
        return ordered

    def _force_combo_preview(self, combo, text):
        """Synchronize QComboBox model and the retained ComboField preview."""
        text = str(text or "")
        combo.setCurrentText(text)
        field = getattr(combo, "_choice_field", None)
        if field is not None:
            try:
                field.setText(text)
            except Exception:
                pass
        legacy = getattr(combo, "_legacy", None)
        if legacy is not None:
            try:
                legacy.setCurrentText(text)
            except Exception:
                pass
        try:
            combo._properties["value"] = text
        except Exception:
            pass

    def _set_style_options(self, family, selected=None):
        styles = self._normalized_style_options(family)
        current = str(selected or self.style_combo.currentText() or "Regular")
        match = next((name for name in styles if name.casefold() == current.casefold()), styles[0])
        self._updating = True
        try:
            self.style_combo.clear()
            self.style_combo.addItems(styles)
            self._force_combo_preview(self.style_combo, match)
        finally:
            self._updating = False
        return match

    def _effective_family(self):
        """Return an installed family even while the editor contains a prefix.

        Windows' chooser lets the edit field lead the list selection.  Keeping
        the typed prefix intact makes keyboard search pleasant, while the
        current list row remains the authoritative family for preview/accept.
        """
        typed = self._family_editor.text().strip()
        exact = next((name for name in self._families
                      if name.casefold() == typed.casefold()), None)
        if exact is not None:
            return exact
        current = self.family_list.currentItem()
        if current is not None:
            return current.text()
        return typed or (self._families[0] if self._families else "")

    def _sync_family_candidate(self, item, requested_style=None, *, update_editor=False):
        if item is None:
            return
        family = self._item_text(item)
        if update_editor:
            self._set_editor(self._family_editor, family)
        self._bind_current_family_row_font(item)
        current = requested_style or self.style_combo.currentText() or "Regular"
        self._set_style_options(family, current)
        self._refresh_preview(family=family)

    def _select_initial(self, family, style, size):
        family = str(family or "")
        row = next((i for i in range(self.family_list.count())
                    if self.family_list.item(i).text().casefold() == family.casefold()), 0)
        if self.family_list.count():
            self.family_list.setCurrentRow(row)
            self._family_clicked(self.family_list.item(row), requested_style=style)
        target_size = str(max(self._minimum_size, min(self._maximum_size, int(size))))
        for i in range(self.size_list.count()):
            if self.size_list.item(i).text() == target_size:
                self.size_list.setCurrentRow(i)
                break
        self._set_editor(self._size_editor, target_size)

    def _filter_families(self, text):
        if self._updating:
            return
        # Windows' font chooser keeps the full family catalog visible while
        # typing and moves the current row to the nearest prefix.  Rebuilding a
        # filtered list made the control feel like a search box and also caused
        # typed text to jump when currentItemChanged fired.
        query = str(text or "").strip().casefold()
        if not query:
            return
        row = next((i for i, family in enumerate(self._families)
                    if family.casefold().startswith(query)), None)
        if row is None:
            row = next((i for i, family in enumerate(self._families)
                        if query in family.casefold()), None)
        if row is None:
            return
        self._updating = True
        try:
            self.family_list.setCurrentRow(row)
        finally:
            self._updating = False
        # Keep the user's typed prefix visible, but update dependent controls
        # from the highlighted family immediately.
        self._sync_family_candidate(self.family_list.item(row), update_editor=False)

    def _commit_typed_family(self):
        text = self._family_editor.text().strip()
        if not text:
            return
        row = next((i for i, family in enumerate(self._families)
                    if family.casefold() == text.casefold()), None)
        if row is None:
            row = next((i for i, family in enumerate(self._families)
                        if family.casefold().startswith(text.casefold())), None)
        if row is not None:
            self.family_list.setCurrentRow(row)
            self._family_clicked(self.family_list.item(row))

    def _family_clicked(self, item, requested_style=None):
        if item is None or self._updating:
            return
        self._sync_family_candidate(item, requested_style, update_editor=True)

    def _style_changed(self, _text):
        if self._updating:
            return
        self._refresh_preview()

    def _size_clicked(self, item):
        if item is None or self._updating:
            return
        self._set_editor(self._size_editor, self._item_text(item))
        self._refresh_preview()

    def _size_text_edited(self, text):
        if self._updating:
            return
        try:
            value = int(round(float(str(text).strip())))
        except (TypeError, ValueError):
            return
        if not self._minimum_size <= value <= self._maximum_size:
            return
        self._updating = True
        try:
            for i in range(self.size_list.count()):
                if self.size_list.item(i).text() == str(value):
                    self.size_list.setCurrentRow(i)
                    break
        finally:
            self._updating = False
        self._refresh_preview()

    def _commit_typed_size(self):
        try:
            value = int(round(float(self._size_editor.text())))
        except (TypeError, ValueError):
            value = self.currentSelection().size
        value = max(self._minimum_size, min(self._maximum_size, value))
        self._set_editor(self._size_editor, value)
        for i in range(self.size_list.count()):
            if self.size_list.item(i).text() == str(value):
                self.size_list.setCurrentRow(i)
                break
        self._refresh_preview()

    def currentSelection(self):
        family = self._effective_family()
        style = self.style_combo.currentText().strip() or "Regular"
        try:
            size = int(round(float(self._size_editor.text())))
        except (TypeError, ValueError):
            size = 12
        size = max(self._minimum_size, min(self._maximum_size, size))
        script_combo = getattr(self, "script_combo", None)
        if script_combo is None:
            script = self._scripts[0]
        else:
            script = str(self.control_value(script_combo) or self._scripts[0])
        return QFontSelection(family, style, size, script)

    def _refresh_preview(self, family=None):
        if not hasattr(self, "_preview_label"):
            return
        selection = self.currentSelection()
        preview_family = str(family or selection.family)
        font = self._resolve_preview_font(preview_family, selection.style, selection.size)
        if font is not None:
            self._preview_fonts[(getattr(font, 'path', ''), selection.size)] = font
        if font is not None:
            try:
                get_backend().bind_item_font(self._preview_label.tag, font.nativeId())
            except Exception:
                pass

    def _accept(self):
        self._commit_typed_size()
        family = self._effective_family()
        if family:
            self._set_editor(self._family_editor, family)
        selection = self.currentSelection()
        callback = self._on_selected
        self.destroy()
        if callable(callback):
            try:
                self.view.after(0, callback, selection)
            except Exception:
                callback(selection)


__all__ = ["QFontDialog", "QFontSelection"]
