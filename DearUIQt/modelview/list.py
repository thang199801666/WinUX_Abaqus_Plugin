"""QListView-like retained list-view implementation."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from ..core.object import Signal, Qt, QPoint, QRect
from ..core.item_model import QModelIndex
from ..core.input import QGlobalInputBinding
from ..gui.system import QCursor
from ..gui.palette import QtFusionMetrics
from .models import QtListItem
from .themes import qt_item_row_theme, qt_list_view_theme, qt_check_list_row_theme
from .base import _QtAbstractItemView

class QtListView(_QtAbstractItemView):
    """QListView-like single-column item view with stable keys."""

    @staticmethod
    def _display_label(text):
        # ImGui Selectable has no independent horizontal text padding. Keep
        # its hit/highlight rectangle full-width and inset only its caption.
        # This is presentation-only: DisplayRole/currentText/copy stay exact.
        return "  " + str(text)

    def __init__(self, parent=None, items=(), *, width=-1, height=-1,
                  visible_rows=None, multiple=False, after=None, backend=None,
                  on_activate=None, context_menu_requests=False):
        backend, parent_options = self._construction(parent, backend)
        auto_height = visible_rows is not None and (height is None or height == -1)
        if auto_height:
            height = int(visible_rows) * QtFusionMetrics.ROW_HEIGHT + 2
        tag = backend.add_child_window(
            width=width, height=height, border=True,
            no_scrollbar=False, no_scroll_with_mouse=False, **parent_options
        )
        super().__init__(tag, parent=parent, after=after, backend=backend, multiple=multiple)
        self.items: dict[Any, Any] = {}
        self.checkboxes: dict[Any, Any] = {}
        self._values: list[QtListItem] = []
        # Last renderer state per row: avoid native set_value/theme crossings
        # when selection updates leave most rows visually unchanged.
        self._row_visual_state: dict[Any, tuple[bool, bool, bool, bool]] = {}
        self._row_visual_full_sync = True
        self._row_visual_selected = set()
        self._row_visual_current = None
        self._row_visual_focus = False
        self._row_visual_retry = set()
        self.currentTextChanged = Signal(self)
        self.itemCheckChanged = Signal(self)
        self.contextMenuRequested = Signal(self)
        self._context_handler_registry = None
        self._context_input_binding = None
        try:
            backend.bind_item_theme(self.tag, qt_list_view_theme(backend))
        except Exception:
            pass
        if callable(on_activate):
            self.activated.connect(on_activate)
        self.setItems(items)
        from ..backends.shared_scrollers import register_scroll_surface
        register_scroll_surface(backend, tag)
        if auto_height and self.checkboxes:
            self.setFixedHeight(int(visible_rows) * self.rowHeight() + 2)
        if context_menu_requests:
            self._context_input_binding = (
                QGlobalInputBinding(backend=backend, parent=self)
                .onMouseClick(Qt.RightButton, self._context_mouse_down)
                .activate()
            )

    def _model_index_for_key(self, key):
        model = self.model()
        if model is None:
            return super()._model_index_for_key(key)
        try:
            return model.index(int(key), 0)
        except (TypeError, ValueError):
            return super()._model_index_for_key(key)

    @staticmethod
    def _item_from_model_index(row, index):
        checked = index.data(Qt.CheckStateRole)
        text = index.data(Qt.DisplayRole)
        return QtListItem(
            row, "" if text is None else str(text), index.data(Qt.UserRole),
            bool(index.flags() & Qt.ItemIsEnabled),
            None if checked is None else int(checked) == Qt.Checked)

    def _update_model_data(self, top_left, bottom_right):
        model = self.model()
        if (model is None or not top_left.isValid() or not bottom_right.isValid()
                or top_left.model() is not model or bottom_right.model() is not model
                or top_left.parent().isValid() or bottom_right.parent().isValid()
                or top_left.row() > bottom_right.row()
                or top_left.column() > bottom_right.column()):
            return False
        if top_left.column() > 0:
            return True  # QListView renders only the first model column.
        updates = []
        for row in range(top_left.row(), bottom_right.row() + 1):
            index = model.index(row, 0)
            old = self._value_for_key(row)
            if not index.isValid() or old is None or row not in self.items:
                return False
            new = self._item_from_model_index(row, index)
            if (old.checked is None) != (new.checked is None):
                return False  # Checkbox presence changes native row structure.
            if new.checked is not None and row not in self.checkboxes:
                return False
            updates.append((old, new))
        try:
            for old, new in updates:
                options = {}
                if new.text != old.text:
                    options['label'] = self._display_label(new.text)
                if new.enabled != old.enabled:
                    options['enabled'] = new.enabled
                if options:
                    self.backend.configure_item(self.items[new.key], **options)
                if new.key in self.checkboxes:
                    if new.enabled != old.enabled:
                        self.backend.configure_item(self.checkboxes[new.key], enabled=new.enabled)
                    if new.checked != old.checked:
                        self.backend.set_value(self.checkboxes[new.key], new.checked)
                self._values[self._state._key_index[new.key]] = new
                if new.enabled != old.enabled:
                    self._row_visual_retry.add(new.key)
        except Exception:
            return False  # Reconcile partial writes from the authoritative model.
        self._sync_selection_visuals()
        return True

    def _model_changed(self, *_args):
        if self._deleted:
            return self
        if (type(self).setItems is QtListView.setItems
                and len(_args) >= 2 and isinstance(_args[0], QModelIndex)
                and isinstance(_args[1], QModelIndex)
                and self._update_model_data(_args[0], _args[1])):
            return self
        model = self.model()
        if model is None:
            self.setItems(())
            return self
        values = []
        for row in range(int(model.rowCount())):
            index = model.index(row, 0)
            if not index.isValid():
                continue
            values.append(self._item_from_model_index(row, index))
        self.setItems(values)
        return self

    def indexAtRow(self, row):
        model = self.model()
        return model.index(int(row), 0) if model is not None else None

    @staticmethod
    def _normalize_items(items: Iterable[Any]):
        normalized = []
        for index, item in enumerate(items or ()):
            if isinstance(item, QtListItem):
                normalized.append(item)
            elif isinstance(item, tuple) and len(item) >= 2:
                normalized.append(QtListItem(item[0], str(item[1]), item[2] if len(item) > 2 else None))
            else:
                normalized.append(QtListItem(item, str(item), item))
        return normalized

    def _add_native_item(self, item):
        """Construct one list item, including its optional check indicator."""
        parent = self.tag
        position = []
        if item.checked is not None:
            parent = self.backend.add_child_window(
                parent=self.tag, width=-1, height=QtFusionMetrics.ROW_HEIGHT,
                border=False, no_scrollbar=True, no_scroll_with_mouse=True)
            self.backend.bind_item_theme(parent, qt_check_list_row_theme(self.backend))
            self.checkboxes[item.key] = self.backend.add_checkbox(
                parent=parent, label="", default_value=bool(item.checked),
                enabled=bool(item.enabled), pos=(4, 2), user_data=item.key,
                callback=self._check_clicked)
            # Reserve a full indicator-sized lane plus a gap. A checkbox at
            # x=4 can reach x=24 (font height + frame padding); starting the
            # selectable there lets its selection/focus fill cover that border.
            position = (QtFusionMetrics.ROW_HEIGHT + 8, 0)
        self.items[item.key] = self.backend.add_selectable(
            parent=parent, label=self._display_label(item.text), width=0,
            height=QtFusionMetrics.ROW_HEIGHT, pos=position,
            default_value=item.key in self.selected,
            enabled=bool(item.enabled), user_data=item.key,
            callback=self._clicked,
        )

    def setItems(self, items):
        incoming = self._normalize_items(items)
        # Repeated model notifications frequently contain identical visible
        # rows (or only updated UserRole payloads).  Avoid deleting/recreating
        # all native selectable controls and losing their hover/scroll state.
        # Compare only renderer-owned fields; opaque UserRole values may not
        # implement boolean equality (e.g. NumPy arrays).
        if (len(incoming) == len(self._values) == len(self.items) and
                all(new.key == old.key and new.text == old.text and
                    new.enabled == old.enabled and new.checked == old.checked
                    for new, old in zip(incoming, self._values))):
            self._values = incoming
            return self
        self._row_visual_full_sync = True
        # Text, enabled and checkbox-value refreshes can all be applied in
        # place when row keys and checkbox *presence* have not changed.
        # Checked -> unchecked does not change the native row structure. In
        # particular, live checklists must not recreate thousands of controls
        # just because one check mark changed. Adding/removing a checkbox
        # still uses the structural renderer below.
        if (len(incoming) == len(self._values) == len(self.items) and
                all(new.key == old.key and
                    (new.checked is None) == (old.checked is None) and
                    (new.checked is None or new.key in self.checkboxes)
                    for new, old in zip(incoming, self._values))):
            try:
                for new, old in zip(incoming, self._values):
                    changed = {}
                    if new.text != old.text:
                        changed["label"] = self._display_label(new.text)
                    if new.enabled != old.enabled:
                        changed["enabled"] = bool(new.enabled)
                    if changed:
                        self.backend.configure_item(self.items[new.key], **changed)
                        if new.key in self.checkboxes and "enabled" in changed:
                            self.backend.configure_item(
                                self.checkboxes[new.key], enabled=bool(new.enabled))
                    if new.checked is not None and new.checked != old.checked:
                        self.backend.set_value(
                            self.checkboxes[new.key], bool(new.checked))
            except Exception:
                # A backend may have lost a row during a deferred deletion.
                # The full reconstruction below is the safe recovery route.
                pass
            else:
                self._values = incoming
                self._sync_selection_visuals()
                return self
        # Append-only refreshes do not invalidate existing row widgets,
        # scroll position, selection or focus. Reordering/check-state changes
        # still use the structural rebuild below. Only use this fast path if
        # the old prefix is visually identical (including checkbox state).
        previous_count = len(self._values)
        new_suffix = incoming[previous_count:]
        if (previous_count > 0 and len(incoming) > previous_count
                and previous_count == len(self.items)
                and all(new.key == old.key and new.text == old.text and
                        new.enabled == old.enabled and new.checked == old.checked
                        for new, old in zip(incoming[:previous_count], self._values))
                and len({item.key for item in new_suffix}) == len(new_suffix)
                and all(item.key not in self.items for item in new_suffix)):
            try:
                for item in new_suffix:
                    self._add_native_item(item)
            except Exception:
                # A half-created checkbox row is cleaned up by the full
                # reconstruction below, alongside its parent container.
                pass
            else:
                self._values = incoming
                self._state.replace(item.key for item in incoming)
                self._sync_selection_visuals()
                return self
        # Tail-only removal is common when streamed results are truncated or
        # a bounded history list loses its final entries.  Keep the surviving
        # native controls (and their focus/scroll state) instead of recreating
        # the entire prefix. A checkbox row is a child container, so delete
        # the direct child of the list rather than its selectable alone.
        if (0 < len(incoming) < previous_count
                and previous_count == len(self.items)
                and len({item.key for item in self._values}) == previous_count
                and all(new.key == old.key and new.text == old.text and
                        new.enabled == old.enabled and new.checked == old.checked
                        for new, old in zip(incoming, self._values))):
            try:
                children = list(self.backend.get_item_children(self.tag, 1) or [])
                # Verify the native structure before mutating anything.  This
                # avoids deleting unrelated children in nonstandard backends.
                valid = len(children) == previous_count and all(
                    old.key in self.checkboxes or children[index] == self.items[old.key]
                    for index, old in enumerate(self._values))
                if not valid:
                    raise RuntimeError("list native row structure changed")
                for child in reversed(children[len(incoming):]):
                    self.backend.delete_item(child)
            except Exception:
                # Partial native deletion is recovered by the full rebuild.
                pass
            else:
                previous_current = self.current
                removed = self._values[len(incoming):]
                for item in removed:
                    self.items.pop(item.key, None)
                    self.checkboxes.pop(item.key, None)
                    self._row_visual_state.pop(item.key, None)
                self._values = incoming
                self._state.replace(item.key for item in incoming)
                # A QListView model reset must not select a new first row.
                if previous_current not in self.items:
                    self._state.current = None
                    self._state.anchor = None
                self._sync_selection_visuals()
                if previous_current != self.current:
                    self.currentChanged.emit(self.current)
                    self.currentTextChanged.emit(self.currentText())
                return self
        previous_current = self.current
        old_scroll_y = self.verticalScrollValue()
        self._values = incoming
        keys = [item.key for item in self._values]
        self._state.replace(keys)
        # QListView does not implicitly select the first item after a model
        # reset. Keep an invalid current index until the user/caller chooses
        # one; this also prevents async suggestion lists from overwriting the
        # text the user is currently typing.
        if previous_current is None or previous_current not in keys:
            self._state.current = None
            self._state.anchor = None
        for child in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(child)
            except Exception:
                pass
        self.items.clear()
        self.checkboxes.clear()
        self._row_visual_state.clear()
        for item in self._values:
            self._add_native_item(item)
        self._sync_selection_visuals()
        self.setVerticalScrollValue(old_scroll_y)
        if previous_current != self.current:
            self.currentChanged.emit(self.current)
            self.currentTextChanged.emit(self.currentText())
        return self

    set_items = setItems

    def rowHeight(self):
        return QtFusionMetrics.ROW_HEIGHT

    def nativeItem(self, key):
        """Return the retained renderer id for ``key`` during migration."""
        return self.items.get(key)

    def setItemSizeHint(self, key, width=None, height=None):
        """Apply one row size hint without exposing ``configure_item`` to callers."""
        item = self.items.get(key)
        if item is None:
            return False
        values = {}
        if width is not None:
            values["width"] = int(width)
        if height is not None:
            values["height"] = int(height)
        if not values:
            return True
        try:
            self.backend.configure_item(item, **values)
            return True
        except Exception:
            return False

    def _clicked(self, sender, value, key):
        if self._deleted or self.items.get(key) != sender:
            return  # A queued callback may refer to a replaced native row.
        item = self._value_for_key(key)
        if item is None or not item.enabled:
            return
        old_current = self.current
        self._row_clicked(sender, value, key)
        if old_current != self.current:
            self.currentTextChanged.emit(self.currentText())

    def _check_clicked(self, sender, checked, key):
        if self._deleted or self.checkboxes.get(key) != sender:
            return  # Ignore callbacks queued by a row that has been rebuilt.
        item = self._value_for_key(key)
        if item is None or item.checked is None or not item.enabled:
            return
        checked = bool(checked)
        if checked == item.checked:
            return
        self._values[self._state._key_index[key]] = replace(item, checked=checked)
        self.itemCheckChanged.emit(key, checked)

    def itemGeometry(self, key, *, include_check_indicator=True):
        """Return global geometry for one retained row, or an empty QRect."""
        selectable = self.items.get(key)
        if selectable is None:
            return QRect()
        try:
            left, top = map(float, self.backend.get_item_rect_min(selectable))
            width, height = map(float, self.backend.get_item_rect_size(selectable))
            if include_check_indicator and key in self.checkboxes:
                check_left = float(self.backend.get_item_rect_min(self.checkboxes[key])[0])
                right = left + width
                left = min(left, check_left)
                width = max(0.0, right - left)
            return QRect(int(round(left)), int(round(top)),
                         max(0, int(round(width))), max(0, int(round(height))))
        except Exception:
            return QRect()

    def keyAt(self, point, *, require_hover=False):
        """Return the stable row key at a global point, mirroring QListView hit-test semantics."""
        point = point if isinstance(point, QPoint) else QPoint(*point)
        for key, selectable in tuple(self.items.items()):
            rect = self.itemGeometry(key)
            if rect.isEmpty() or not rect.contains(point):
                continue
            if require_hover:
                try:
                    hovered = self.backend.is_item_hovered(selectable) or (
                        key in self.checkboxes and self.backend.is_item_hovered(self.checkboxes[key]))
                except Exception:
                    hovered = False
                if not hovered:
                    continue
            return key
        return None

    def indexAt(self, point):
        key = self.keyAt(point)
        return self._model_index_for_key(key) if key is not None else None

    def _context_mouse_down(self, *_args):
        if self._deleted:
            return
        try:
            point = QCursor.pos(backend=self.backend)
        except Exception:
            return
        key = self.keyAt(point, require_hover=True)
        if key is not None:
            self.contextMenuRequested.emit(key, point.toTuple())

    def delete(self):
        binding = self._context_input_binding
        self._context_input_binding = None
        if binding is not None:
            try:
                binding.delete()
            except Exception:
                pass
        self._context_handler_registry = None
        super().delete()

    def setUniformItemSizes(self, enabled=True):
        # Rows already use one shared QtFusionMetrics.ROW_HEIGHT.  Retain the
        # familiar QListView property so callers can express intent without
        # depending on backend details.
        self._uniform_item_sizes = bool(enabled)
        return self

    def currentText(self):
        item = self._value_for_key(self.current)
        return item.text if item is not None else ""

    def currentData(self):
        return self.itemData(self.current)

    def itemData(self, key):
        item = self._value_for_key(key)
        return item.data if item is not None else None

    def itemForKey(self, key):
        """Return the retained row payload in O(1), or None for an absent key.

        Reuse the selection state's first-occurrence index rather than retaining
        another per-row dictionary. Same-key payload refreshes remain visible.
        """
        return self._value_for_key(key)

    def _value_for_key(self, key):
        # QListWidget overrides itemForKey to return a QListWidgetItem, not
        # the QtListItem payload consumed by this base renderer.
        index = self._state._key_index.get(key)
        if index is None or index >= len(self._values):
            return None
        item = self._values[index]
        return item if item.key == key else None

    def setCurrentText(self, text):
        text = str(text)
        item = next((item for item in self._values if item.text == text), None)
        if item is None:
            return False
        changed = self.setCurrentKey(item.key, select=True)
        if changed:
            self.currentTextChanged.emit(item.text)
        return changed

    def _sync_selection_visuals(self):
        selected_keys = set(self.selected)
        current_key = self.current
        active_focus = self._has_focus
        if self._row_visual_full_sync:
            dirty = set(self.items)
        else:
            dirty = selected_keys ^ self._row_visual_selected
            if current_key != self._row_visual_current:
                dirty.update((current_key, self._row_visual_current))
            if active_focus != self._row_visual_focus:
                # Active/inactive themes also change unselected hover colors.
                dirty.update(self.items)
        dirty.update(self._row_visual_retry)
        self._row_visual_retry.clear()
        visual_state = self._row_visual_state
        for key in dirty:
            item = self.items.get(key)
            if item is None:
                continue
            value = self._value_for_key(key)
            chosen = key in selected_keys
            current = key == current_key
            state = (chosen, value is not None and not value.enabled,
                     current, active_focus)
            if visual_state.get(key) == state:
                continue
            selected, disabled, current, active = state
            try:
                self.backend.set_value(item, selected)
                self.backend.bind_item_theme(
                    item, qt_item_row_theme(
                        self.backend,
                        selected=selected,
                        disabled=disabled,
                        current=current,
                        active=active,
                    ))
            except Exception:
                # Do not cache an incomplete update: try again on the next
                # selection/focus reconciliation if the backend was transient.
                visual_state.pop(key, None)
                self._row_visual_retry.add(key)
            else:
                visual_state[key] = state
        self._row_visual_selected = selected_keys
        self._row_visual_current = current_key
        self._row_visual_focus = active_focus
        self._row_visual_full_sync = False

    def _focus_current(self):
        item = self.items.get(self.current)
        if item is not None:
            try:
                self.backend.focus_item(item)
            except Exception:
                pass


QListView = QtListView
ImGuiListView = QtListView

__all__ = ["QtListView", "ImGuiListView", "QListView"]
