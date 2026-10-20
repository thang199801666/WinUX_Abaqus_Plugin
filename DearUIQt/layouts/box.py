"""Qt-style box containers preserving Dear ImGui's native layout behavior."""
from ..widgets.widget import QWidget
from ..core.object import Qt, QSize, QMargins, QSizePolicy
from ..widgets.buttons import QLabel
from ..gui.style import METRICS, bind_theme, form_row_theme, aligned_cell_theme


class QLayoutItem:
    """A non-owning reference returned by layout inspection/removal APIs."""
    def __init__(self, value):
        self._value = value

    def widget(self):
        return None if getattr(self._value, "_is_layout", False) else self._value

    def layout(self):
        return self._value if getattr(self._value, "_is_layout", False) else None

    def isEmpty(self):
        return self._value._deleted

    def sizeHint(self):
        callback = getattr(self._value, "sizeHint", None)
        return callback() if callable(callback) else QSize(-1, -1)

    def minimumSize(self):
        callback = getattr(self._value, "minimumSizeHint", None)
        return callback() if callable(callback) else QSize(0, 0)

    def expandingDirections(self):
        callback = getattr(self._value, "sizePolicy", None)
        policy = callback() if callable(callback) else None
        return 0 if policy is None else policy.expandingDirections()


def _layout_hint(child, minimum=False):
    """Return a child's participating hint using Qt hidden/size-policy rules."""
    hidden = getattr(child, "isHidden", lambda: False)()
    policy = getattr(child, "sizePolicy", lambda: None)()
    retain_hidden = bool(policy is not None and policy.retainSizeWhenHidden())
    if hidden and not retain_hidden:
        return None
    callback = child.minimumSizeHint if minimum else child.sizeHint
    hint = callback()
    if not isinstance(hint, QSize) or not hint.isValid():
        return QSize(0, 0)
    if policy is not None:
        try:
            width, height = hint.width(), hint.height()
            if policy.horizontalPolicy() == QSizePolicy.Ignored:
                width = 0
            if policy.verticalPolicy() == QSizePolicy.Ignored:
                height = 0
            hint = QSize(width, height)
        except Exception:
            pass
    return hint


def _invalidate_owner(layout):
    """Invalidate nested layout caches and request one root geometry pass."""
    owner = layout.parent
    while getattr(owner, "_is_layout", False):
        owner._layout_dirty = True
        owner._cached_size_hint = None
        owner._cached_minimum_size = None
        owner = owner.parent
    update = getattr(owner, "updateGeometry", None)
    if callable(update):
        update()



def _validate_placement(layout, widget):
    layout._require_ui()
    if layout._deleted:
        raise RuntimeError("cannot add items to a deleted layout")
    if not isinstance(widget, QWidget) or widget._deleted:
        raise ValueError("layout requires a live QWidget or layout")
    widget._require_ui()
    if widget.backend is not layout.backend:
        raise ValueError("layout and widget must use the same backend")
    ancestor = layout
    while ancestor is not None:
        if ancestor is widget:
            raise ValueError("layout placement cannot contain an ownership cycle")
        ancestor = ancestor.parent


def _detach(layout, widget):
    native_parent = layout.backend.get_item_parent(layout.tag)
    if not native_parent:
        raise RuntimeError("layout removal requires an enclosing native container")
    layout.backend.move_item(widget._layout_tag(), parent=native_parent)
    widget.setParent(layout.parent)
    return QLayoutItem(widget)


class QBoxLayout(QWidget):
    _is_layout = True
    def __init__(self, *, horizontal=False, spacing=7, parent=None, after=None, backend=None,
                 indent=0, show=True, tag=None):
        backend, options = self._construction(parent, backend)
        if tag is not None:
            options["tag"] = tag
        native = backend.add_group(
            horizontal=bool(horizontal), horizontal_spacing=spacing,
            indent=max(0, int(indent)), show=bool(show), **options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        if not show:
            self._explicit_visible = False
            self._effective_visible = False
            self._properties["show"] = False
        self._horizontal = bool(horizontal)
        self._spacing = max(0, int(spacing))
        self._layout_dirty = True
        self._layout_enabled = True
        self._contents_margins = QMargins(0, 0, 0, 0)
        self._cached_size_hint = None
        self._cached_minimum_size = None

    def invalidate(self):
        self._layout_dirty = True
        self._cached_size_hint = None
        self._cached_minimum_size = None
        _invalidate_owner(self)
        return True

    def activate(self):
        if not self._layout_enabled or not self._layout_dirty:
            return False
        for child in self._items():
            child.ensurePolished()
            if getattr(child, "_is_layout", False):
                child.activate()
        self._layout_dirty = False
        return True

    def setEnabled(self, enabled):
        enabled = bool(enabled)
        if enabled != self._layout_enabled:
            self._layout_enabled = enabled
            if enabled:
                self.invalidate()

    def isEnabled(self):
        return self._layout_enabled

    def spacing(self):
        return self._spacing

    def setSpacing(self, spacing):
        spacing = max(0, int(spacing))
        if spacing != self._spacing:
            self._spacing = spacing
            try:
                self._configure("horizontal_spacing", spacing)
            except Exception:
                pass
            self.invalidate()

    def contentsMargins(self):
        return QMargins(*tuple(self._contents_margins))

    def setContentsMargins(self, left, top=None, right=None, bottom=None):
        if isinstance(left, QMargins) and top is None and right is None and bottom is None:
            margins = QMargins(*tuple(left))
        else:
            if None in (top, right, bottom):
                raise TypeError("setContentsMargins requires QMargins or four integers")
            margins = QMargins(left, top, right, bottom)
        if margins != self._contents_margins:
            self._contents_margins = margins
            self.invalidate()

    def expandingDirections(self):
        directions = 0
        for child in self._items():
            policy = child.sizePolicy()
            directions |= policy.expandingDirections()
            if self._horizontal and policy.horizontalStretch() > 0:
                directions |= Qt.Horizontal
            if not self._horizontal and policy.verticalStretch() > 0:
                directions |= Qt.Vertical
        return directions

    def addSpacing(self, size):
        from ..widgets.primitives import QSpacer
        size = max(0, int(size))
        spacer = QSpacer(size if self._horizontal else 0,
                         0 if self._horizontal else size,
                         parent=self, backend=self.backend)
        self.invalidate()
        return spacer

    def addStretch(self, stretch=0):
        from ..widgets.primitives import QSpacer
        spacer = QSpacer(0, 0, parent=self, backend=self.backend, expanding=True)
        policy = spacer.sizePolicy()
        if self._horizontal:
            policy.setHorizontalStretch(max(1, int(stretch or 1)))
        else:
            policy.setVerticalStretch(max(1, int(stretch or 1)))
        spacer.setSizePolicy(policy)
        self.invalidate()
        return spacer

    def setStretch(self, index, stretch):
        """Set Qt-style stretch metadata on one box-layout item.

        Dear ImGui owns final placement, but retaining stretch on QSizePolicy
        gives nested layouts/backends one canonical sizing contract without a
        parallel host-application-specific field.
        """
        item = self.itemAt(int(index))
        if item is None:
            return False
        widget = item.layout() or item.widget()
        if widget is None:
            return False
        policy = widget.sizePolicy()
        if self._horizontal:
            policy.setHorizontalStretch(stretch)
        else:
            policy.setVerticalStretch(stretch)
        widget.setSizePolicy(policy)
        self.invalidate()
        return True

    def stretch(self, index):
        item = self.itemAt(int(index))
        if item is None:
            return 0
        widget = item.layout() or item.widget()
        if widget is None:
            return 0
        policy = widget.sizePolicy()
        return policy.horizontalStretch() if self._horizontal else policy.verticalStretch()

    def setStretchFactor(self, widget, stretch):
        index = self.indexOf(widget)
        return False if index < 0 else self.setStretch(index, stretch)

    @staticmethod
    def _valid_hint(value):
        return value if isinstance(value, QSize) and value.isValid() else QSize(0, 0)

    def _aggregate_hint(self, minimum=False):
        hints = []
        for child in self._items():
            hint = _layout_hint(child, minimum)
            if hint is not None:
                hints.append(self._valid_hint(hint))
        margins = self._contents_margins
        horizontal_margin = margins.left() + margins.right()
        vertical_margin = margins.top() + margins.bottom()
        if not hints:
            return QSize(horizontal_margin, vertical_margin)
        gap = self._spacing * max(0, len(hints) - 1)
        if self._horizontal:
            return QSize(sum(item.width() for item in hints) + gap + horizontal_margin,
                         max(item.height() for item in hints) + vertical_margin)
        return QSize(max(item.width() for item in hints) + horizontal_margin,
                     sum(item.height() for item in hints) + gap + vertical_margin)

    def sizeHint(self):
        if self._cached_size_hint is None:
            self._cached_size_hint = self._aggregate_hint(False)
        return self._cached_size_hint

    def minimumSize(self):
        if self._cached_minimum_size is None:
            self._cached_minimum_size = self._aggregate_hint(True)
        return self._cached_minimum_size

    minimumSizeHint = minimumSize

    def count(self):
        return len(self._items())

    def _items(self):
        self._require_ui()
        return [child for child in self._children if isinstance(child, QWidget)]

    def itemAt(self, index):
        items = self._items()
        return QLayoutItem(items[index]) if 0 <= index < len(items) else None

    def indexOf(self, widget):
        items = self._items()
        return items.index(widget) if widget in items else -1

    def _insert(self, index, widget):
        _validate_placement(self, widget)
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("layout index must be an integer")
        others = [child for child in self._items() if child is not widget]
        index = len(others) if index < 0 else min(index, len(others))
        options = {"parent": self.tag}
        if index < len(others):
            options["before"] = others[index]._layout_tag()
        self.backend.move_item(widget._layout_tag(), **options)
        widget.setParent(self)
        others.insert(index, widget)
        helpers = [child for child in self._children if not isinstance(child, QWidget)]
        self._children[:] = helpers + others
        self.invalidate()
        return widget

    def addWidget(self, widget):
        return self._insert(-1, widget)

    def insertWidget(self, index, widget):
        return self._insert(index, widget)

    def addLayout(self, layout):
        return self.insertLayout(-1, layout)

    def insertLayout(self, index, layout):
        if not getattr(layout, "_is_layout", False):
            raise ValueError("addLayout requires a layout")
        return self._insert(index, layout)

    def takeAt(self, index):
        items = self._items()
        if not 0 <= index < len(items):
            return None
        item = _detach(self, items[index])
        self.invalidate()
        return item

    def removeWidget(self, widget):
        return self.takeAt(self.indexOf(widget))

    def clear(self, *, delete=True):
        """Remove all layout items, optionally deleting their owned widgets.

        ``delete=True`` is the practical retained-UI equivalent of repeatedly
        taking Qt layout items and calling ``deleteLater`` on their widgets.
        It also keeps renderer child deletion out of application code.
        """
        items = list(self._items())
        if delete:
            for child in reversed(items):
                child.delete()
            self.invalidate()
            return len(items)
        for index in range(len(items) - 1, -1, -1):
            self.takeAt(index)
        return len(items)


class QHBoxLayout(QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(horizontal=True, **kwargs)


class QVBoxLayout(QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(horizontal=False, **kwargs)


def _intrinsic_height_grid(parent, backend, native_parent):
    """Return whether a grid's nearest vertical host sizes itself to contents.

    QtDialog frequently passes a raw Dear PyGui parent ID (via a QObject proxy),
    not its QWidget owner.  Looking only at QWidget.parent misses these native
    ancestry links, notably QGroupBox sections and dialog form containers.

    Do not cross a fixed-height child window: a nested viewport intentionally
    owns its remaining height even inside an outer auto-height card.
    """
    owner = parent
    seen = set()
    for _ in range(32):
        if owner is None or id(owner) in seen:
            break
        seen.add(id(owner))
        if getattr(owner, "_vertical_sizing_host", False) or hasattr(owner, "_frame_shape"):
            return bool(getattr(owner, "_auto_resize_y", False))
        owner = getattr(owner, "parent", None)

    configuration = getattr(backend, "get_item_configuration", None)
    get_parent = getattr(backend, "get_item_parent", None)
    if not callable(configuration) or not callable(get_parent) or native_parent is None:
        return False
    tag = native_parent
    seen_tags = set()
    for _ in range(32):
        try:
            if not tag or tag in seen_tags:
                break
            seen_tags.add(tag)
            config = configuration(tag)
            if not isinstance(config, dict):
                break
            if "auto_resize_y" in config:
                return bool(config["auto_resize_y"])
            tag = get_parent(tag)
        except (KeyError, TypeError, ValueError, RuntimeError):
            break
        except Exception:
            # Not all test/native backends expose configuration inspection.
            break
    return False


class QGridLayout(QWidget):
    """Retained table cells; row/column spans are intentionally unsupported."""
    _is_layout = True

    def __init__(self, columns=2, *, column_widths=None, parent=None, after=None, backend=None,
                 width=-1, height=-1, vertical_dividers=False, horizontal_dividers=False):
        if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
            raise ValueError("grid columns must be a positive integer")
        widths = (None,) * columns if column_widths is None else tuple(column_widths)
        if len(widths) != columns or any(width is not None and (
                not isinstance(width, (int, float)) or isinstance(width, bool) or
                width <= 0 or width != width or width == float('inf')) for width in widths):
            raise ValueError("column widths must match the grid and be positive or None")
        # A fill-height ImGui table and an auto-height child can amplify each
        # other's measured height indefinitely.  Honor the nearest native or
        # QObject-backed vertical host, including raw-tag parents in QDialogs.
        backend, options = self._construction(parent, backend)
        native_height = int(height)
        if native_height == -1 and _intrinsic_height_grid(
                parent, backend, options.get("parent")):
            native_height = 0
        tag = backend.add_table(header_row=False, width=int(width), height=native_height,
            policy=backend.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=bool(horizontal_dividers), borders_outerH=False,
            borders_innerV=bool(vertical_dividers), borders_outerV=False, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.columns = columns
        self._rows, self._cells = [], {}
        self._layout_dirty = True
        self._layout_enabled = True
        self._contents_margins = QMargins(0, 0, 0, 0)
        self._horizontal_spacing = 0
        self._vertical_spacing = 0
        self._cached_size_hint = None
        self._cached_minimum_size = None
        try:
            for width in widths:
                if width is None:
                    backend.add_table_column(parent=tag, width_stretch=True)
                else:
                    backend.add_table_column(parent=tag, width_fixed=True, init_width_or_weight=width)
        except Exception:
            self.delete()
            raise

    def invalidate(self):
        self._layout_dirty = True
        self._cached_size_hint = None
        self._cached_minimum_size = None
        _invalidate_owner(self)
        return True

    def activate(self):
        if not self._layout_enabled or not self._layout_dirty:
            return False
        for _row, _column, child in self._entries():
            child.ensurePolished()
            if getattr(child, "_is_layout", False):
                child.activate()
        self._layout_dirty = False
        return True

    def setEnabled(self, enabled):
        enabled = bool(enabled)
        if enabled != self._layout_enabled:
            self._layout_enabled = enabled
            if enabled:
                self.invalidate()

    def isEnabled(self):
        return self._layout_enabled

    def contentsMargins(self):
        return QMargins(*tuple(self._contents_margins))

    def setContentsMargins(self, left, top=None, right=None, bottom=None):
        if isinstance(left, QMargins) and top is None and right is None and bottom is None:
            margins = QMargins(*tuple(left))
        else:
            if None in (top, right, bottom):
                raise TypeError("setContentsMargins requires QMargins or four integers")
            margins = QMargins(left, top, right, bottom)
        if margins != self._contents_margins:
            self._contents_margins = margins
            self.invalidate()

    def horizontalSpacing(self):
        return self._horizontal_spacing

    def verticalSpacing(self):
        return self._vertical_spacing

    def setHorizontalSpacing(self, spacing):
        spacing = max(0, int(spacing))
        if spacing != self._horizontal_spacing:
            self._horizontal_spacing = spacing
            self.invalidate()

    def setVerticalSpacing(self, spacing):
        spacing = max(0, int(spacing))
        if spacing != self._vertical_spacing:
            self._vertical_spacing = spacing
            self.invalidate()

    def expandingDirections(self):
        directions = 0
        for _row, _column, child in self._entries():
            directions |= child.sizePolicy().expandingDirections()
        return directions

    def _aggregate_hint(self, minimum=False):
        widths = [0] * self.columns
        heights = [0] * max(1, self.rowCount())
        for row, column, child in self._entries():
            hint = _layout_hint(child, minimum)
            if hint is None or not isinstance(hint, QSize) or not hint.isValid():
                continue
            widths[column] = max(widths[column], hint.width())
            if row >= len(heights):
                heights.extend([0] * (row + 1 - len(heights)))
            heights[row] = max(heights[row], hint.height())
        margins = self._contents_margins
        width_gap = self._horizontal_spacing * max(0, len(widths) - 1)
        populated_rows = max(0, len(heights) - 1)
        height_gap = self._vertical_spacing * populated_rows
        return QSize(
            sum(widths) + width_gap + margins.left() + margins.right(),
            sum(heights) + height_gap + margins.top() + margins.bottom(),
        )

    def sizeHint(self):
        if self._cached_size_hint is None:
            self._cached_size_hint = self._aggregate_hint(False)
        return self._cached_size_hint

    def minimumSize(self):
        if self._cached_minimum_size is None:
            self._cached_minimum_size = self._aggregate_hint(True)
        return self._cached_minimum_size

    minimumSizeHint = minimumSize

    def cell(self, row, column):
        """Return an owned box container suitable as a child widget parent."""
        self._require_ui()
        if self._deleted:
            raise RuntimeError("cannot access a deleted grid")
        if (not isinstance(row, int) or isinstance(row, bool) or row < 0 or
                not isinstance(column, int) or isinstance(column, bool) or
                not 0 <= column < self.columns):
            raise ValueError("invalid grid position")
        while len(self._rows) <= row:
            index = len(self._rows)
            native_row = self.backend.add_table_row(parent=self.tag)
            cells = []
            try:
                for _ in range(self.columns):
                    cell = QVBoxLayout(spacing=0, parent=native_row, after=self._after, backend=self.backend)
                    cell.setParent(self)
                    cells.append(cell)
            except Exception:
                for cell in cells:
                    cell.delete()
                self.backend.delete_item(native_row)
                raise
            self._rows.append(native_row)
            self._cells.update(((index, col), cell) for col, cell in enumerate(cells))
        return self._cells[row, column]

    def addWidget(self, widget, row, column):
        _validate_placement(self, widget)
        cell = self.cell(row, column)
        if widget.parent is not cell:
            self.backend.move_item(widget._layout_tag(), parent=cell.tag)
            widget.setParent(cell)
        self.invalidate()
        return widget

    def addLayout(self, layout, row, column):
        if not getattr(layout, "_is_layout", False):
            raise ValueError("addLayout requires a layout")
        return self.addWidget(layout, row, column)

    def rowCount(self):
        self._require_ui()
        return len(self._rows)

    def columnCount(self):
        return self.columns

    def _entries(self):
        self._require_ui()
        return [(row, col, child) for (row, col), cell in sorted(self._cells.items())
                for child in cell._children if isinstance(child, QWidget)]

    def count(self):
        return len(self._entries())

    def itemAt(self, index):
        entries = self._entries()
        return QLayoutItem(entries[index][2]) if 0 <= index < len(entries) else None

    def itemAtPosition(self, row, column):
        self._require_ui()
        cell = self._cells.get((row, column))
        return cell.itemAt(0) if cell is not None else None

    def indexOf(self, widget):
        return next((index for index, (_, _, child) in enumerate(self._entries())
                     if child is widget), -1)

    def getItemPosition(self, index):
        entries = self._entries()
        if not 0 <= index < len(entries):
            return None
        row, column, _widget = entries[index]
        return row, column, 1, 1

    def takeAt(self, index):
        entries = self._entries()
        if not 0 <= index < len(entries):
            return None
        item = _detach(self, entries[index][2])
        self.invalidate()
        return item

    def removeWidget(self, widget):
        return self.takeAt(self.indexOf(widget))

    def clear(self, *, delete=True):
        entries = list(self._entries())
        if delete:
            for _row, _column, child in reversed(entries):
                child.delete()
            self.invalidate()
            return len(entries)
        for index in range(len(entries) - 1, -1, -1):
            self.takeAt(index)
        return len(entries)

    def delete(self):
        try:
            super().delete()
        finally:
            # A rejected worker-thread deletion must not mutate the UI caches.
            if self._deleted:
                self._rows.clear()
                self._cells.clear()


class QFormLayout(QGridLayout):
    """Two-column label/field form with owned rows and Qt-like role lookup."""
    LabelRole = 0
    FieldRole = 1

    def __init__(self, *, label_width=140, parent=None, after=None, backend=None):
        super().__init__(2, column_widths=(label_width, None), parent=parent,
                         after=after, backend=backend)
        bind_theme(self.backend, self.tag, form_row_theme)

    def addRow(self, label, field):
        _validate_placement(self, field)
        if label is field:
            raise ValueError("form label and field must be different widgets")
        if not isinstance(label, str):
            _validate_placement(self, label)
        row = self.rowCount()
        created_label = isinstance(label, str)
        label_cell = self.cell(row, self.LabelRole)
        if created_label or isinstance(label, QLabel):
            bind_theme(self.backend, label_cell.tag, aligned_cell_theme)
            self.backend.add_spacer(parent=label_cell.tag, height=METRICS.form_label_top_pad)
        if created_label:
            label = QLabel(label, parent=label_cell)
        else:
            self.addWidget(label, row, self.LabelRole)
        try:
            self.addWidget(field, row, self.FieldRole)
        except Exception:
            if created_label:
                label.delete()
            raise
        return row

    def labelForField(self, field):
        for row, column, child in self._entries():
            if column == self.FieldRole and child is field:
                item = self.itemAtPosition(row, self.LabelRole)
                return item.widget() if item is not None else None
        return None


__all__ = ["QLayoutItem", "QBoxLayout", "QHBoxLayout", "QVBoxLayout", "QGridLayout", "QFormLayout"]
