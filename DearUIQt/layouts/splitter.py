"""Retained Qt-style splitter widget built on Dear PyGui geometry."""
from __future__ import annotations

from ..core.object import Qt, Signal
from ..gui.style import bind_theme, splitter_hitbox_theme, splitter_theme
from ..widgets.widget import QWidget


class QSplitterHandle(QWidget):
    """Reusable splitter grab surface with a separate one-pixel paint line.

    Dear ImGui needs a comfortably sized native hit target while desktop UI
    splitters are normally painted as a very thin divider.  This class keeps
    those two concerns together: ``tag`` is the hitbox and ``lineTag()`` is the
    visual divider.  Host applications may still bind their own input policy
    without constructing raw backend buttons.
    """

    def __init__(self, orientation=Qt.Horizontal, *, parent=None, after=None,
                 backend=None, handle_width=7, line_width=1, visible=True):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("splitter handle orientation must be Qt.Horizontal or Qt.Vertical")
        backend, options = self._construction(parent, backend)
        self._orientation = orientation
        self._handle_width = max(1, int(handle_width))
        self._line_width = max(1, int(line_width))
        line_options = dict(options)
        hit_options = dict(options)
        line_options.update(label="", width=1, height=1, show=bool(visible))
        hit_options.update(label="", width=1, height=1, show=bool(visible))
        self._line_tag = backend.add_button(**line_options)
        tag = backend.add_button(**hit_options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._prime_visibility_state(bool(visible))
        bind_theme(self.backend, self._line_tag, splitter_theme, active=False)
        bind_theme(self.backend, self.tag, splitter_hitbox_theme)

    def orientation(self):
        return self._orientation

    def setOrientation(self, orientation):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("splitter handle orientation must be Qt.Horizontal or Qt.Vertical")
        self._orientation = orientation

    def handleWidth(self):
        return self._handle_width

    def setHandleWidth(self, width):
        self._handle_width = max(1, int(width))

    def lineWidth(self):
        return self._line_width

    def setLineWidth(self, width):
        self._line_width = max(1, int(width))

    def lineTag(self):
        return self._line_tag

    def hitBoxTag(self):
        return self.tag

    def setGeometry(self, x, y=None, width=None, height=None):
        if isinstance(x, (tuple, list)) and y is None:
            x, y, width, height = x
        x, y, width, height = int(x), int(y), int(width), int(height)
        native_width = width if width < 0 else max(1, width)
        native_height = height if height < 0 else max(1, height)
        self.backend.configure_item(
            self.tag, pos=(x, y), width=native_width, height=native_height)
        if self._orientation == Qt.Horizontal:
            line_x = x + max(0, (max(1, width) - self._line_width) // 2)
            self.backend.configure_item(
                self._line_tag, pos=(line_x, y), width=self._line_width,
                height=native_height)
        else:
            line_y = y + max(0, (max(1, height) - self._line_width) // 2)
            self.backend.configure_item(
                self._line_tag, pos=(x, line_y), width=native_width,
                height=self._line_width)

    def setVisible(self, visible):
        super().setVisible(visible)
        try:
            self.backend.configure_item(self._line_tag, show=bool(visible))
        except Exception:
            pass

    def delete(self):
        line = self._line_tag
        self._line_tag = None
        try:
            if line is not None and self.backend.does_item_exist(line):
                self.backend.delete_item(line)
        finally:
            super().delete()


class QSplitter(QWidget):
    """Generic multi-pane ``QSplitter`` wrapper.

    Children are ordinary :class:`QWidget` instances.  The splitter owns their
    native geometry, preserves relative sizes across host resizes, and exposes
    the familiar ``sizes()``, ``setSizes()`` and ``splitterMoved`` contract.
    No application-specific pane, dock or input semantics live here.
    """

    def __init__(self, orientation=Qt.Horizontal, *, parent=None, after=None,
                 backend=None, handle_width=5):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("splitter orientation must be Qt.Horizontal or Qt.Vertical")
        backend, options = self._construction(parent, backend)
        tag = backend.add_child_window(
            width=-1, height=-1, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.splitterMoved = Signal(self)
        self._orientation = orientation
        self._handle_width = max(1, int(handle_width))
        self._widgets = []
        self._handles = []
        self._handle_lines = []
        self._handle_widgets = []
        self._handler_registries = []
        self._weights = []
        self._last_sizes = []
        self._active_handle = None
        self._drag_origin = 0.0
        self._drag_sizes = None
        self._resize_registry = None
        self._install_resize_handler()

    def orientation(self):
        return self._orientation

    def setOrientation(self, orientation):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("splitter orientation must be Qt.Horizontal or Qt.Vertical")
        if orientation == self._orientation:
            return
        self._orientation = orientation
        for handle in self._handle_widgets:
            handle.setOrientation(orientation)
        self._layout_children()

    def handleWidth(self):
        return self._handle_width

    def setHandleWidth(self, width):
        width = max(1, int(width))
        if width != self._handle_width:
            self._handle_width = width
            self._layout_children()

    def createHandle(self):
        return QSplitterHandle(
            self._orientation, parent=self, backend=self.backend,
            handle_width=self._handle_width, line_width=1)

    def handle(self, index):
        """Return the QSplitterHandle before widget *index* (Qt uses 1..count-1)."""
        handle_index = int(index) - 1
        if 0 <= handle_index < len(self._handle_widgets):
            return self._handle_widgets[handle_index]
        return None

    def count(self):
        return len(self._widgets)

    def widget(self, index):
        return self._widgets[index] if 0 <= int(index) < len(self._widgets) else None

    def indexOf(self, widget):
        try:
            return self._widgets.index(widget)
        except ValueError:
            return -1

    def addWidget(self, widget):
        return self.insertWidget(len(self._widgets), widget)

    def insertWidget(self, index, widget):
        self._require_ui()
        if not isinstance(widget, QWidget):
            raise TypeError("splitter child must be QWidget")
        if widget._deleted:
            raise RuntimeError("cannot add a deleted splitter child")
        if widget.backend is not self.backend:
            raise ValueError("splitter and child must use the same backend")
        if widget is self:
            raise ValueError("a splitter cannot contain itself")
        old_index = self.indexOf(widget)
        if old_index >= 0:
            self._widgets.pop(old_index)
            weight = self._weights.pop(old_index)
            if old_index < index:
                index -= 1
        else:
            weight = 1.0
        index = max(0, min(int(index), len(self._widgets)))
        self.backend.move_item(widget._layout_tag(), parent=self.tag)
        widget.setParent(self)
        self._widgets.insert(index, widget)
        self._weights.insert(index, weight)
        self._rebuild_handles()
        self._layout_children()
        return widget

    def replaceWidget(self, index, widget):
        self._require_ui()
        old = self.widget(index)
        if old is None:
            raise IndexError("splitter index out of range")
        old_weight = self._weights[index]
        detached = self._detach_widget(index)
        self.insertWidget(index, widget)
        self._weights[index] = old_weight
        self._layout_children()
        return detached

    def _detach_widget(self, index):
        widget = self._widgets.pop(index)
        self._weights.pop(index)
        native_parent = None
        try:
            native_parent = self.backend.get_item_parent(self.tag)
        except Exception:
            pass
        if native_parent:
            self.backend.move_item(widget._layout_tag(), parent=native_parent)
        widget.setParent(self.parent)
        self._rebuild_handles()
        return widget

    def setStretchFactor(self, index, stretch):
        if not 0 <= int(index) < len(self._widgets):
            return False
        stretch = max(0.0, float(stretch))
        self._weights[int(index)] = stretch
        self._normalize_weights()
        self._layout_children()
        return True

    def sizes(self):
        if len(self._last_sizes) == len(self._widgets):
            return list(self._last_sizes)
        total = self._current_extent()
        return self._resolve_sizes(total)

    def setSizes(self, sizes):
        values = [max(0.0, float(value)) for value in sizes]
        if len(values) != len(self._widgets):
            raise ValueError("setSizes requires one size per splitter widget")
        if values and sum(values) <= 0:
            values = [1.0] * len(values)
        self._weights = values
        self._normalize_weights()
        self._layout_children()

    def saveState(self):
        return {
            "orientation": int(self._orientation),
            "handleWidth": int(self._handle_width),
            "sizes": self.sizes(),
        }

    def restoreState(self, state):
        if not isinstance(state, dict):
            return False
        try:
            orientation = int(state.get("orientation", self._orientation))
            handle_width = int(state.get("handleWidth", self._handle_width))
            sizes = state.get("sizes")
            self.setOrientation(orientation)
            self.setHandleWidth(handle_width)
            if sizes is not None and len(sizes) == len(self._widgets):
                self.setSizes(sizes)
            return True
        except (TypeError, ValueError):
            return False

    def moveSplitter(self, position, index):
        """Programmatically move handle *index* (1..count-1), like Qt."""
        self._require_ui()
        handle_index = int(index) - 1
        if not 0 <= handle_index < len(self._handles):
            return False
        sizes = self.sizes()
        prefix = sum(sizes[:handle_index]) + self._handle_width * handle_index
        pair_total = sizes[handle_index] + sizes[handle_index + 1]
        first = int(round(float(position) - prefix))
        first = max(1, min(pair_total - 1, first)) if pair_total >= 2 else max(0, pair_total)
        sizes[handle_index] = first
        sizes[handle_index + 1] = max(0, pair_total - first)
        self.setSizes(sizes)
        self.splitterMoved.emit(int(round(position)), int(index))
        return True

    # ---------------------------------------------------------------- native layout
    def _current_extent(self):
        try:
            width, height = self.backend.get_item_rect_size(self.tag)
            extent = width if self._orientation == Qt.Horizontal else height
            if float(extent) > 0:
                return int(round(float(extent)))
        except Exception:
            pass
        return self.width() if self._orientation == Qt.Horizontal else self.height()

    def _normalize_weights(self):
        if not self._weights:
            return
        total = sum(max(0.0, value) for value in self._weights)
        if total <= 0:
            self._weights = [1.0 / len(self._weights)] * len(self._weights)
        else:
            self._weights = [max(0.0, value) / total for value in self._weights]

    def _resolve_sizes(self, total_extent):
        count = len(self._widgets)
        if not count:
            return []
        available = max(count, int(total_extent) - self._handle_width * max(0, count - 1))
        self._normalize_weights()
        if not self._weights:
            self._weights = [1.0 / count] * count
        raw = [available * weight for weight in self._weights]
        sizes = [max(1, int(value)) for value in raw]
        difference = available - sum(sizes)
        # Distribute rounding remainder from the largest fractional parts.
        order = sorted(range(count), key=lambda i: raw[i] - int(raw[i]), reverse=difference > 0)
        step = 1 if difference > 0 else -1
        for offset in range(abs(difference)):
            index = order[offset % count]
            if step < 0 and sizes[index] <= 1:
                continue
            sizes[index] += step
        # Last-resort correction when several 1px minima prevented subtraction.
        delta = available - sum(sizes)
        if delta:
            sizes[-1] = max(1, sizes[-1] + delta)
        return sizes

    def _layout_children(self, *_args):
        if self._deleted:
            return
        total = self._current_extent()
        if total <= 0:
            return
        sizes = self._resolve_sizes(total)
        self._last_sizes = list(sizes)
        try:
            width, height = self.backend.get_item_rect_size(self.tag)
            width, height = int(width), int(height)
        except Exception:
            width, height = self.width(), self.height()
        cursor = 0
        for index, widget in enumerate(self._widgets):
            extent = sizes[index]
            if self._orientation == Qt.Horizontal:
                self.backend.configure_item(widget._layout_tag(), pos=(cursor, 0), width=extent, height=max(1, height))
            else:
                self.backend.configure_item(widget._layout_tag(), pos=(0, cursor), width=max(1, width), height=extent)
            cursor += extent
            if index < len(self._handles):
                handle = self._handles[index]
                line = self._handle_lines[index]
                if self._orientation == Qt.Horizontal:
                    self.backend.configure_item(handle, pos=(cursor, 0), width=self._handle_width, height=max(1, height))
                    line_x = cursor + max(0, (self._handle_width - 1) // 2)
                    self.backend.configure_item(line, pos=(line_x, 0), width=1, height=max(1, height))
                else:
                    self.backend.configure_item(handle, pos=(0, cursor), width=max(1, width), height=self._handle_width)
                    line_y = cursor + max(0, (self._handle_width - 1) // 2)
                    self.backend.configure_item(line, pos=(0, line_y), width=max(1, width), height=1)
                cursor += self._handle_width

    def _install_resize_handler(self):
        try:
            registry = self.backend.add_item_handler_registry()
            self.backend.add_item_resize_handler(parent=registry, callback=self._layout_children)
            self.backend.bind_item_handler_registry(self.tag, registry)
            self._resize_registry = registry
        except Exception:
            self._resize_registry = None

    def _rebuild_handles(self):
        for registry in self._handler_registries:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handler_registries = []
        for handle_widget in self._handle_widgets:
            try:
                handle_widget.delete()
            except Exception:
                pass
        self._handles = []
        self._handle_lines = []
        self._handle_widgets = []
        for index in range(max(0, len(self._widgets) - 1)):
            # Keep the interaction target comfortably wide while painting only
            # a one-pixel divider, matching Qt's visual/interaction split.
            handle_widget = self.createHandle()
            line = handle_widget.lineTag()
            handle = handle_widget.hitBoxTag()
            self._handle_widgets.append(handle_widget)
            self._handle_lines.append(line)
            self._handles.append(handle)
            try:
                registry = self.backend.add_item_handler_registry()
                self.backend.add_item_clicked_handler(
                    parent=registry,
                    button=getattr(self.backend, "mvMouseButton_Left", 0),
                    callback=lambda *args, _index=index: self._begin_drag(_index),
                )
                self.backend.add_item_active_handler(
                    parent=registry,
                    callback=lambda *args, _index=index: self._drag(_index),
                )
                self.backend.add_item_deactivated_handler(
                    parent=registry,
                    callback=lambda *args, _index=index: self._end_drag(_index),
                )
                self.backend.bind_item_handler_registry(handle, registry)
                self._handler_registries.append(registry)
            except Exception:
                pass

    def _pointer_coordinate(self):
        try:
            mouse = self.backend.get_mouse_pos(local=False)
            root = self.backend.get_item_rect_min(self.tag)
            axis = 0 if self._orientation == Qt.Horizontal else 1
            return float(mouse[axis]) - float(root[axis])
        except Exception:
            return None

    def _begin_drag(self, index):
        coordinate = self._pointer_coordinate()
        if coordinate is None:
            return
        self._active_handle = index
        self._drag_origin = coordinate
        self._drag_sizes = self.sizes()
        try:
            bind_theme(self.backend, self._handle_lines[index], splitter_theme, active=True)
        except Exception:
            pass

    def _drag(self, index):
        if self._active_handle != index or self._drag_sizes is None:
            return
        coordinate = self._pointer_coordinate()
        if coordinate is None:
            return
        sizes = list(self._drag_sizes)
        delta = int(round(coordinate - self._drag_origin))
        pair_total = sizes[index] + sizes[index + 1]
        first = max(1, min(pair_total - 1, sizes[index] + delta)) if pair_total >= 2 else pair_total
        sizes[index] = first
        sizes[index + 1] = max(0, pair_total - first)
        self.setSizes(sizes)
        position = sum(sizes[:index + 1]) + self._handle_width * index
        self.splitterMoved.emit(int(position), index + 1)

    def _end_drag(self, index):
        if self._active_handle != index:
            return
        self._active_handle = None
        self._drag_sizes = None
        try:
            bind_theme(self.backend, self._handle_lines[index], splitter_theme, active=False)
        except Exception:
            pass

    def resize(self, width, height):
        super().resize(width, height)
        self._layout_children()

    def delete(self):
        self._handles = []
        self._handle_lines = []
        self._handle_widgets = []
        self._handler_registries = []
        self._widgets = []
        super().delete()


__all__ = ["QSplitter"]
