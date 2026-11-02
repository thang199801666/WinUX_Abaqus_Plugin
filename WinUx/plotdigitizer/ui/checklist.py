"""Plot Digitizer-only rounded check indicators and semantic workflow rows."""
from DearUIQt import QtListView
from DearUIQt.core import QItemInputBinding, Qt
from DearUIQt.gui import QtFusionPalette
from DearUIQt.widgets import QCanvas, QRetainedItem
from DearUIQt.themes import ThemeTarget, ThemeColor, ThemeStyle, make_theme, theme_component


CHECKBOX_ROUNDING = 2
TEXT_HIGHLIGHT_ROUNDING = 4
# Qt/Fusion keeps the indicator close to the font height (roughly 13-14 px).
# Dear ImGui derives the checkbox square from font height + FramePadding, so a
# zero frame pad is the important part; the positions below simply centre that
# native indicator in our 24 px list row.
CHECKBOX_LEFT = 7
CHECKBOX_TOP = 5
CAPTION_START_X = 29
ROW_FILL_TOP = 2
ROW_FILL_BOTTOM = 2


def rounded_checkbox_theme(backend, *, focused=False, compact=True):
    """Return a compact Qt/Fusion-like theme for native DPG checkboxes.

    Keep Dear ImGui's real checkbox hit target/checkmark instead of painting a
    fake indicator.  A zero FramePadding makes the visible square track the
    font height like Qt's 13-14 px indicator; blue is reserved for focus, while
    the check itself uses the normal text role as Qt Fusion does.
    """
    p = QtFusionPalette
    return make_theme(*(theme_component(ThemeTarget.CHECK_BOX,
        colors={ThemeColor.FRAME_BACKGROUND: p.BASE if enabled else p.BUTTON_DISABLED,
                ThemeColor.FRAME_BACKGROUND_HOVERED: p.HIGHLIGHT_HOVER if enabled else p.BUTTON_DISABLED,
                ThemeColor.FRAME_BACKGROUND_ACTIVE: p.SELECTION_INACTIVE if enabled else p.BUTTON_DISABLED,
                ThemeColor.CHECK_MARK: p.TEXT if enabled else p.TEXT_DISABLED,
                ThemeColor.TEXT: p.TEXT if enabled else p.TEXT_DISABLED,
                ThemeColor.BORDER: (p.FOCUS if focused else p.BORDER) if enabled else p.BORDER_LIGHT,
                ThemeColor.NAV_HIGHLIGHT: p.FOCUS},
        styles={ThemeStyle.FRAME_ROUNDING: CHECKBOX_ROUNDING, ThemeStyle.FRAME_BORDER_SIZE: 1,
                ThemeStyle.FRAME_PADDING: (0, 0),
                ThemeStyle.ITEM_INNER_SPACING: (6, 2)},
        enabled_state=enabled) for enabled in (True, False)), backend=backend,
        tag='winux.plotdigitizer.checkbox.qt.{}.{}'.format(int(focused), int(compact)), cache=True)


class DigitizerCheckList(QtListView):
    """Keep native row/checkbox input, painting rounded fills behind controls.

    Native Selectable ignores FrameRounding. A canvas before the controls draws
    the fill; text, keyboard selection and checkbox clicks remain native.
    """

    # Soft semantic fills used by Workflow.  Keep them intentionally pale so
    # black body text retains high contrast and the colors read as status, not
    # as warning/success buttons.
    UNFINISHED = (253, 244, 245, 255)
    UNFINISHED_HOVER = (250, 235, 238, 255)
    COMPLETE = (241, 248, 242, 255)
    COMPLETE_HOVER = (230, 243, 232, 255)
    ROUNDING = TEXT_HIGHLIGHT_ROUNDING

    def __init__(self, *args, completion_colors=False, **kwargs):
        self._completion_colors = completion_colors
        self._row_surfaces = {}
        super().__init__(*args, **kwargs)
        self._paint_binding = QItemInputBinding(self, parent=self).onVisible(self._paint_rows).activate()

    def _caption_clicked(self, key):
        """Treat the rounded caption surface as the checkbox row itself.

        The caption canvas is the only custom layer that can sit above the
        native Selectable. Bind input directly to that canvas instead of using
        a global mouse hook. This keeps text clicks reliable without allowing
        clicks on unrelated controls (for example View Data's coordinate combo)
        to be misclassified as Workflow clicks on native/multi-viewport Windows.
        """
        if self._deleted:
            return False
        item = self.itemForKey(key)
        if item is None or item.checked is None or not item.enabled:
            return False
        self.setCurrentKey(key, select=True)
        return self._toggle_row_checkbox(key)

    def _toggle_row_checkbox(self, key):
        """Toggle one checkbox row from a caption/row click."""
        checkbox = self.checkboxes.get(key)
        item = self.itemForKey(key)
        if checkbox is None or item is None or item.checked is None or not item.enabled:
            return False
        checked = not bool(item.checked)
        try:
            self.backend.set_value(checkbox, checked)
        except Exception:
            pass
        self._check_clicked(checkbox, checked, key)
        return True

    def _clicked(self, sender, value, key):
        old_checked = None
        item = self.itemForKey(key)
        if item is not None and item.checked is not None and item.enabled:
            old_checked = bool(item.checked)
        super()._clicked(sender, value, key)
        if old_checked is not None and bool(self.itemForKey(key).checked) == old_checked:
            self._toggle_row_checkbox(key)

    def _add_native_item(self, item):
        super()._add_native_item(item)
        if item.checked is None:
            return
        checkbox = self.checkboxes.get(item.key)
        if checkbox is not None:
            try:
                self.backend.configure_item(checkbox, pos=(CHECKBOX_LEFT, CHECKBOX_TOP))
            except Exception:
                pass
        native = self.items.get(item.key)
        if native is not None:
            try:
                self.backend.configure_item(native, pos=(CAPTION_START_X, 0))
            except Exception:
                pass
        old = self._row_surfaces.pop(item.key, None)
        if old is not None:
            old['parent'].delete()
        row = self.backend.get_item_info(self.items[item.key])['parent']
        parent = QRetainedItem(row, parent=self, backend=self.backend)
        # Keep the draw-list physically outside the checkbox lane.  A transparent
        # draw-list still participates in DearPyGui hit testing on some Windows
        # builds, so a full-row canvas can swallow checkbox clicks even when its
        # rectangle starts beside the indicator lane. Positioning the painted
        # caption after that lane keeps the native checkbox genuinely unobstructed
        # rather than merely transparent.
        # Keep one full-row draw surface, but paint only the caption lane.
        # The canvas owns a local item-click binding below, so it can render the
        # rounded fill without requiring any application-wide pointer hit-test.
        canvas = QCanvas(1, self.rowHeight(), parent=parent, backend=self.backend, pos=(0, 0))
        QRetainedItem(canvas.tag, backend=self.backend).reparent(row, before=self.checkboxes[item.key])
        caption_binding = (
            QItemInputBinding(canvas, parent=parent, backend=self.backend)
            .onClick(Qt.LeftButton, lambda *_args, key=item.key: self._caption_clicked(key))
            .activate()
        )
        paint = canvas.painter().drawRect((CAPTION_START_X, ROW_FILL_TOP),
            (CAPTION_START_X + 1, self.rowHeight() - ROW_FILL_BOTTOM),
            color=(0, 0, 0, 0), fill=(0, 0, 0, 0), rounding=self.ROUNDING)
        self._row_surfaces[item.key] = {
            'parent': parent, 'canvas': canvas, 'paint': paint, 'state': None,
            'caption_binding': caption_binding,
            'canvas_item': QRetainedItem(canvas.tag, backend=self.backend).setImmediateUpdates(True),
            'paint_item': QRetainedItem(paint, backend=self.backend).setImmediateUpdates(True)}
        self.backend.bind_item_theme(self.checkboxes[item.key], rounded_checkbox_theme(self.backend))

    def _transparent_row_theme(self, disabled):
        return make_theme(theme_component(ThemeTarget.SELECTABLE,
            colors={ThemeColor.HEADER: (0, 0, 0, 0), ThemeColor.HEADER_HOVERED: (0, 0, 0, 0),
                    ThemeColor.HEADER_ACTIVE: (0, 0, 0, 0), ThemeColor.NAV_HIGHLIGHT: (0, 0, 0, 0),
                    ThemeColor.TEXT: QtFusionPalette.TEXT_DISABLED if disabled else QtFusionPalette.TEXT,
                    ThemeColor.TEXT_DISABLED: QtFusionPalette.TEXT_DISABLED},
            styles={ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_PADDING: (5, 2),
                    ThemeStyle.SELECTABLE_TEXT_ALIGN: (0, .5)}, enabled_state=not disabled),
            backend=self.backend, tag='winux.plotdigitizer.checklist.text.{}'.format(int(disabled)), cache=True)

    def _sync_selection_visuals(self):
        super()._sync_selection_visuals()
        for key in list(self._row_surfaces):
            if key not in self.items:
                self._row_surfaces.pop(key)['parent'].delete()
        for key, native in self.items.items():
            if key in self._row_surfaces:
                item = self.itemForKey(key)
                self.backend.bind_item_theme(native, self._transparent_row_theme(not item.enabled))
                checkbox = self.checkboxes.get(key)
                if checkbox is not None:
                    self.backend.bind_item_theme(checkbox, rounded_checkbox_theme(
                        self.backend, focused=bool(item.enabled and self._has_focus and key == self.current)))
        self._paint_rows()

    def _paint_rows(self, *_args):
        if self._deleted:
            return
        p = QtFusionPalette
        for key, surface in self._row_surfaces.items():
            item = self.itemForKey(key)
            if item is None or not surface['canvas'].exists():
                continue
            width = surface['parent'].globalGeometry().width()
            if width <= 34:
                continue
            chosen = key in self.selected
            hovered = self.backend.is_item_hovered(self.items[key])
            if self._completion_colors:
                fill = self.COMPLETE if item.checked else self.UNFINISHED
                if chosen or hovered:
                    fill = self.COMPLETE_HOVER if item.checked else self.UNFINISHED_HOVER
            else:
                fill = (p.SELECTION_ACTIVE if self._has_focus else p.SELECTION_INACTIVE) if chosen else (
                    p.HIGHLIGHT_HOVER if hovered else (0, 0, 0, 0))
            border = p.FOCUS if chosen or (key == self.current and self._has_focus) else (0, 0, 0, 0)
            canvas_width = max(1, width)
            state = (canvas_width, fill, border)
            if surface['state'] != state:
                surface['canvas_item'].configure(width=canvas_width, height=self.rowHeight())
                surface['paint_item'].configure(
                    pmin=(CAPTION_START_X, ROW_FILL_TOP),
                    pmax=(max(CAPTION_START_X + 1, canvas_width - 2),
                          self.rowHeight() - ROW_FILL_BOTTOM),
                    fill=fill, color=border)
                surface['state'] = state
