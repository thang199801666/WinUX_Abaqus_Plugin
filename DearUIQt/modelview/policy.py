"""Shared QAbstractItemView-style interaction policy.

The policy layer owns edit-trigger state, cursor action constants and the
selection/current application rules. Concrete views keep topology/rendering in
``moveCursor()``/``scrollTo()`` and provide tiny synchronization hooks.
"""
from __future__ import annotations

from ..core.object import Signal, Qt
from ..core.input import QGlobalInputBinding
from ..gui.system import QCursor
from ..core.item_model import QModelIndex, QItemSelectionModel
from .style_option import QStyleOptionViewItem


class QItemViewPolicyMixin:
    NoEditTriggers = 0x00
    CurrentChanged = 0x01
    DoubleClicked = 0x02
    SelectedClicked = 0x04
    EditKeyPressed = 0x08
    AnyKeyPressed = 0x10
    AllEditTriggers = CurrentChanged | DoubleClicked | SelectedClicked | EditKeyPressed | AnyKeyPressed

    MoveUp = 0
    MoveDown = 1
    MoveLeft = 2
    MoveRight = 3
    MoveHome = 4
    MoveEnd = 5
    MovePageUp = 6
    MovePageDown = 7
    MoveNext = 8
    MovePrevious = 9

    EnsureVisible = 0
    PositionAtTop = 1
    PositionAtBottom = 2
    PositionAtCenter = 3

    def _init_item_view_policy(self, *, multiple=False):
        self._edit_triggers = self.DoubleClicked | self.EditKeyPressed
        self._page_step = 10
        self._model_cursor_anchor = QModelIndex()
        self._policy_multiple = bool(multiple)
        # M6g: focus/current/selection rendering state is retained by the
        # policy layer, not by individual renderers.  Concrete views only
        # translate this normalized state into native themes.
        focus_signal = getattr(self, "focusChanged", None)
        if focus_signal is None:
            focus_signal = Signal(self)
            self.focusChanged = focus_signal
        self._has_focus = bool(getattr(self, "_has_focus", False))
        self._focus_input_binding = getattr(self, "_focus_input_binding", None)
        self._install_item_view_focus_tracking()

    def _install_item_view_focus_tracking(self):
        if getattr(self, "_focus_input_binding", None) is not None:
            return
        try:
            self._focus_input_binding = (
                QGlobalInputBinding(backend=self.backend, parent=self)
                .onMouseClick(Qt.LeftButton, self._focus_mouse_down)
                .activate()
            )
        except Exception:
            self._focus_input_binding = None

    def _focus_mouse_down(self, *_args):
        try:
            point = QCursor.pos(backend=self.backend)
        except Exception:
            point = None
        self._set_view_focus(bool(point is not None and self._point_in_view(point)))

    def _point_in_view(self, point):
        try:
            return bool(self.containsGlobalPoint(point, clipped=True))
        except Exception:
            return False

    def _ensure_native_visible(self, native, hint=None, viewport=None):
        """Scroll a native row into view without using renderer focus.

        DearPyGui ``focus_item`` has a hidden scrolling side effect. Item
        views must not use it as a scroll primitive because programmatic
        current/selection updates can then reclaim the viewport. This helper
        performs the Qt ``scrollTo`` geometry calculation directly and only
        mutates the vertical scroll value when the row is outside the visible
        viewport (or an explicit position hint requests movement).
        """
        if native is None:
            return False
        b = self.backend
        viewport = self.tag if viewport is None else viewport
        if hint is None:
            hint = self.EnsureVisible
        try:
            view_left, view_top = map(float, b.get_item_rect_min(viewport))
            view_width, view_height = map(float, b.get_item_rect_size(viewport))
            row_left, row_top = map(float, b.get_item_rect_min(native))
            row_width, row_height = map(float, b.get_item_rect_size(native))
            current = float(b.get_y_scroll(viewport))
        except Exception:
            return False

        del view_left, view_width, row_left, row_width
        view_bottom = view_top + max(0.0, view_height)
        row_bottom = row_top + max(0.0, row_height)
        target = current

        if int(hint) == self.PositionAtTop:
            target = current + (row_top - view_top)
        elif int(hint) == self.PositionAtBottom:
            target = current + (row_bottom - view_bottom)
        elif int(hint) == self.PositionAtCenter:
            target = current + ((row_top + row_bottom) * 0.5 - (view_top + view_bottom) * 0.5)
        elif row_top < view_top:
            target = current - (view_top - row_top)
        elif row_bottom > view_bottom:
            target = current + (row_bottom - view_bottom)
        else:
            return False

        target = max(0.0, float(target))
        if abs(target - current) < 0.5:
            return False
        try:
            b.set_y_scroll(viewport, target)
            return True
        except Exception:
            return False

    def _set_view_focus(self, focused):
        focused = bool(focused)
        if bool(getattr(self, "_has_focus", False)) == focused:
            return False
        self._has_focus = focused
        sync = getattr(self, "_sync_selection_visuals", None)
        if callable(sync):
            sync()
        self.focusChanged.emit(focused)
        return True

    def hasFocus(self):
        return bool(getattr(self, "_has_focus", False))

    def setFocus(self):
        # Keep QApplication/native focus and retained active-selection state in
        # lockstep, but never use focus acquisition as an implicit scroll
        # request. DearPyGui row focus/ensure-visible can move the viewport;
        # that made a stale current row reclaim the scroll position whenever a
        # list regained focus after a click, refresh, modal close, or wheel
        # interaction. Keyboard navigation already calls scrollTo()/
        # _focus_current() explicitly where movement is intended.
        try:
            super().setFocus()
        except Exception:
            pass
        self._set_view_focus(True)
        return self

    def styleOptionForIndex(self, index=None, *, selected=None, disabled=None, current=None, hovered=False):
        if index is None:
            try:
                index = self.currentIndex()
            except Exception:
                index = QModelIndex()
        selection_model = getattr(self, "_selection_model", None)
        if selected is None:
            selected = False
            if selection_model is not None and isinstance(index, QModelIndex) and index.isValid():
                try:
                    selected = selection_model.isSelected(index)
                except Exception:
                    try:
                        selected = index in selection_model.selectedIndexes()
                    except Exception:
                        selected = False
        if current is None:
            current = False
            if selection_model is not None:
                try:
                    current = index == selection_model.currentIndex()
                except Exception:
                    pass
        if disabled is None:
            disabled = False
            if isinstance(index, QModelIndex) and index.isValid():
                try:
                    disabled = not bool(index.flags() & Qt.ItemIsEnabled)
                except Exception:
                    pass
        option = QStyleOptionViewItem(
            selected=bool(selected), current=bool(current), focused=self.hasFocus(),
            disabled=bool(disabled), hovered=bool(hovered), index=index, widget=self)
        delegate = getattr(self, "_item_delegate", None)
        init_option = getattr(delegate, "initStyleOption", None)
        if callable(init_option) and isinstance(index, QModelIndex) and index.isValid():
            try:
                init_option(option, index)
            except Exception:
                pass
        return option

    def _item_visual_state(self, *, selected=False, disabled=False, current=False, hovered=False):
        return self.styleOptionForIndex(
            None, selected=selected, disabled=disabled, current=current, hovered=hovered
        ).stateTuple()

    def _delete_item_view_policy(self):
        binding = getattr(self, "_focus_input_binding", None)
        self._focus_input_binding = None
        if binding is not None:
            try:
                binding.delete()
            except Exception:
                pass

    def editTriggers(self):
        return int(getattr(self, "_edit_triggers", self.DoubleClicked | self.EditKeyPressed))

    def setEditTriggers(self, triggers):
        self._edit_triggers = int(triggers) & int(self.AllEditTriggers)
        return self

    def pageStep(self):
        return max(1, int(getattr(self, "_page_step", 10)))

    def setPageStep(self, rows):
        self._page_step = max(1, int(rows))
        return self

    def _index_is_editable(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return False
        try:
            flags = index.flags()
        except Exception:
            return False
        return bool((flags & Qt.ItemIsEditable) and (flags & Qt.ItemIsEnabled))

    def _edit_from_trigger(self, trigger, index=None):
        if not (self.editTriggers() & int(trigger)):
            return None
        if index is None:
            index = self.currentIndex()
        if not self._index_is_editable(index):
            return None
        edit = getattr(self, "edit", None)
        return edit(index) if callable(edit) else None

    def _cursor_action_for_key(self, key, *, shift=False):
        if key == Qt.Key_Up: return self.MoveUp
        if key == Qt.Key_Down: return self.MoveDown
        if key == Qt.Key_Left: return self.MoveLeft
        if key == Qt.Key_Right: return self.MoveRight
        if key == Qt.Key_Home: return self.MoveHome
        if key == Qt.Key_End: return self.MoveEnd
        if key == Qt.Key_PageUp: return self.MovePageUp
        if key == Qt.Key_PageDown: return self.MovePageDown
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and shift): return self.MovePrevious
        if key == Qt.Key_Tab: return self.MoveNext
        return None

    def _policy_sync_from_selection(self):
        """Concrete view hook after QItemSelectionModel mutation."""

    def _policy_focus_current(self):
        try:
            self.setFocus()
        except Exception:
            pass

    def _policy_current_changed(self, current, previous):
        del current, previous

    def _apply_policy_cursor(self, target, *, ctrl=False, shift=False):
        if not isinstance(target, QModelIndex) or not target.isValid():
            return False
        selection_model = getattr(self, "_selection_model", None)
        if selection_model is None:
            self.setCurrentIndex(target)
            self.scrollTo(target, self.EnsureVisible)
            self._policy_focus_current()
            if self.editTriggers() & self.CurrentChanged:
                self._edit_from_trigger(self.CurrentChanged, target)
            return True

        previous = selection_model.currentIndex()
        multiple = bool(getattr(self, "multiple", getattr(self, "_policy_multiple", False)))
        anchor = getattr(self, "_model_cursor_anchor", QModelIndex())
        model = getattr(self, "_model", None)

        if shift and multiple and previous.isValid() and previous.parent() == target.parent() and model is not None:
            if not anchor.isValid() or anchor.parent() != target.parent():
                anchor = previous
                self._model_cursor_anchor = anchor
            parent = target.parent()
            r0, r1 = sorted((anchor.row(), target.row()))
            c0, c1 = sorted((anchor.column(), target.column()))
            indexes = []
            for row in range(r0, r1 + 1):
                for column in range(c0, c1 + 1):
                    try:
                        idx = model.index(row, column, parent)
                    except Exception:
                        idx = QModelIndex()
                    if idx.isValid():
                        indexes.append(idx)
            selection_model.select(indexes, QItemSelectionModel.Select if ctrl else QItemSelectionModel.ClearAndSelect)
            selection_model.setCurrentIndex(target, QItemSelectionModel.NoUpdate)
        elif ctrl and multiple:
            selection_model.setCurrentIndex(target, QItemSelectionModel.NoUpdate)
        else:
            self._model_cursor_anchor = target
            selection_model.select([target], QItemSelectionModel.ClearAndSelect)
            selection_model.setCurrentIndex(target, QItemSelectionModel.NoUpdate)

        self._policy_sync_from_selection()
        self.scrollTo(target, self.EnsureVisible)
        self._policy_focus_current()
        self._policy_current_changed(target, previous)
        return True

    def _move_policy_current(self, key, *, ctrl=False, shift=False):
        action = self._cursor_action_for_key(key, shift=shift)
        if action is None:
            return False
        modifiers = ((Qt.ControlModifier if ctrl else Qt.NoModifier) |
                     (Qt.ShiftModifier if shift else Qt.NoModifier))
        target = self.moveCursor(action, modifiers)
        return self._apply_policy_cursor(target, ctrl=ctrl, shift=shift)


__all__ = ["QItemViewPolicyMixin"]
