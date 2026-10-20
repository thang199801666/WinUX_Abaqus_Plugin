"""QTreeWidget/QTreeWidgetItem convenience item view.

The widget owns a small hierarchical item model and renders full-width retained
rows through the active DearUIQt backend.  Applications use Qt roles and item
methods; Dear PyGui-specific selectable/draw-list plumbing stays here.
"""
from __future__ import annotations

from itertools import count

from ..core.object import Qt, Signal
from ..gui.palette import QtFusionMetrics
from ..widgets.widget import QWidget


_TREE_KEYS = count(1)


class QTreeWidgetItem:
    Type = 0
    UserType = 1000

    def __init__(self, parent=None, strings=(), type=Type):
        # Qt accepts QTreeWidgetItem(parent, ["text", ...]) as well as a
        # top-level item constructed independently.  A string is one column,
        # not an iterable of characters.
        if isinstance(parent, (str, bytes, list, tuple)) and not isinstance(parent, (QTreeWidgetItem, QTreeWidget)):
            if not strings:
                strings, parent = parent, None
        if isinstance(strings, (str, bytes)):
            strings = [strings]
        self._key = next(_TREE_KEYS)
        self._texts = [str(value) for value in (strings or [""])]
        if not self._texts:
            self._texts = [""]
        self._type = int(type)
        self._data = {}
        self._icons = {}
        self._tooltips = {}
        self._children = []
        self._parent_item = None
        self._tree = None
        self._expanded = False
        self._hidden = False
        self._enabled = True
        self._selected = False
        self._row_theme = None
        self._container_theme = None
        if isinstance(parent, QTreeWidgetItem):
            parent.addChild(self)
        elif isinstance(parent, QTreeWidget):
            parent.addTopLevelItem(self)
        elif parent is not None:
            raise TypeError("parent must be QTreeWidget, QTreeWidgetItem, or None")

    @property
    def key(self):
        return self._key

    def type(self):
        return self._type

    def treeWidget(self):
        return self._tree

    def parent(self):
        return self._parent_item

    def child(self, index):
        index = int(index)
        return self._children[index] if 0 <= index < len(self._children) else None

    def childCount(self):
        return len(self._children)

    def indexOfChild(self, child):
        try:
            return self._children.index(child)
        except ValueError:
            return -1

    def _adopt(self, child, index=None):
        if not isinstance(child, QTreeWidgetItem):
            raise TypeError("tree child must be QTreeWidgetItem")
        if child is self or self._is_descendant_of(child):
            raise ValueError("cannot create a cyclic tree")
        old_tree = child._tree
        if child._parent_item is not None:
            child._parent_item._children.remove(child)
        elif old_tree is not None:
            old_tree._top_level.remove(child)
        child._parent_item = self
        child._set_tree(self._tree)
        if index is None:
            self._children.append(child)
        else:
            self._children.insert(max(0, min(int(index), len(self._children))), child)
        if old_tree is not None and old_tree is not self._tree:
            old_tree._rebuild()
        self._notify_structure()
        return child

    def _is_descendant_of(self, item):
        current = self._parent_item
        while current is not None:
            if current is item:
                return True
            current = current._parent_item
        return False

    def addChild(self, child):
        return self._adopt(child)

    def addChildren(self, children):
        return [self._adopt(child) for child in list(children or ())]

    def insertChild(self, index, child):
        return self._adopt(child, index)

    def takeChild(self, index):
        index = int(index)
        if not 0 <= index < len(self._children):
            return None
        child = self._children.pop(index)
        child._parent_item = None
        child._set_tree(None)
        self._notify_structure()
        return child

    def takeChildren(self):
        children = list(self._children)
        self._children.clear()
        for child in children:
            child._parent_item = None
            child._set_tree(None)
        self._notify_structure()
        return children

    def _set_tree(self, tree):
        self._tree = tree
        for child in self._children:
            child._set_tree(tree)

    def _notify_structure(self):
        if self._tree is not None:
            self._tree._rebuild()

    def _changed(self, column=0, role=Qt.DisplayRole):
        if self._tree is not None:
            self._tree._item_changed(self, int(column), int(role))

    def text(self, column=0):
        column = int(column)
        return self._texts[column] if 0 <= column < len(self._texts) else ""

    def setText(self, column, text):
        column = int(column)
        while len(self._texts) <= column:
            self._texts.append("")
        text = str(text)
        if self._texts[column] == text:
            return
        self._texts[column] = text
        self._changed(column, Qt.DisplayRole)

    def data(self, column, role):
        column, role = int(column), int(role)
        if role == Qt.DisplayRole:
            return self.text(column)
        if role == Qt.DecorationRole:
            return self.icon(column)
        if role == Qt.ToolTipRole:
            return self.toolTip(column)
        if role == Qt.CheckStateRole:
            return self._data.get((column, role), Qt.Unchecked)
        return self._data.get((column, role))

    def setData(self, column, role, value):
        column, role = int(column), int(role)
        if role == Qt.DisplayRole:
            self.setText(column, value)
            return
        if role == Qt.DecorationRole:
            self.setIcon(column, value)
            return
        if role == Qt.ToolTipRole:
            self.setToolTip(column, value)
            return
        key = (column, role)
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._changed(column, role)

    def icon(self, column=0):
        return self._icons.get(int(column))

    def setIcon(self, column, icon):
        column = int(column)
        if self._icons.get(column) == icon:
            return
        self._icons[column] = icon
        self._changed(column, Qt.DecorationRole)

    def toolTip(self, column=0):
        return self._tooltips.get(int(column), "")

    def setToolTip(self, column, text):
        column = int(column)
        text = str(text or "")
        if self._tooltips.get(column, "") == text:
            return
        self._tooltips[column] = text
        self._changed(column, Qt.ToolTipRole)

    def checkState(self, column=0):
        return int(self.data(column, Qt.CheckStateRole) or Qt.Unchecked)

    def setCheckState(self, column, state):
        self.setData(column, Qt.CheckStateRole, int(state))

    def isExpanded(self):
        return bool(self._expanded)

    def setExpanded(self, expanded):
        expanded = bool(expanded)
        if self._expanded == expanded:
            return
        self._expanded = expanded
        if self._tree is not None:
            self._tree._item_expansion_changed(self)

    def isHidden(self):
        return bool(self._hidden)

    def setHidden(self, hidden):
        hidden = bool(hidden)
        if self._hidden == hidden:
            return
        self._hidden = hidden
        self._notify_structure()

    def isDisabled(self):
        return not self._enabled

    def setDisabled(self, disabled):
        self.setEnabled(not disabled)

    def isEnabled(self):
        return bool(self._enabled)

    def setEnabled(self, enabled):
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._changed(0, Qt.UserRole - 1)

    def isSelected(self):
        return bool(self._selected)

    def setSelected(self, selected):
        if self._tree is not None:
            if selected:
                self._tree.setCurrentItem(self)
            elif self._tree.currentItem() is self:
                self._tree.setCurrentItem(None)
        else:
            self._selected = bool(selected)

    # DearUIQt extension: renderer themes remain opaque backend values.  This
    # lets applications preserve a native visual without importing a backend.
    def rowTheme(self):
        return self._row_theme

    def setRowTheme(self, theme):
        self._row_theme = theme
        self._changed(0, Qt.UserRole - 2)

    def containerTheme(self):
        return self._container_theme

    def setContainerTheme(self, theme):
        self._container_theme = theme
        self._changed(0, Qt.UserRole - 3)


class QTreeWidget(QWidget):
    """Hierarchical convenience view with full-row retained item rendering."""

    def __init__(self, parent=None, *, width=-1, height=-1, row_height=None,
                 indentation=18, icon_size=(16, 16), root_spacing=0,
                 after=None, backend=None):
        backend, options = self._construction(parent, backend)
        tag = backend.add_child_window(
            width=int(width), height=int(height), border=False,
            no_scrollbar=False, no_scroll_with_mouse=False, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.currentItemChanged = Signal(self)
        self.itemClicked = Signal(self)
        self.itemDoubleClicked = Signal(self)
        self.itemActivated = Signal(self)
        self.itemExpanded = Signal(self)
        self.itemCollapsed = Signal(self)
        self.itemChanged = Signal(self)
        self.itemSelectionChanged = Signal(self)
        self.layoutChanged = Signal(self)
        self._top_level = []
        self._current = None
        self._rendered = {}
        self._item_by_native = {}
        self._handler_registries = []
        self._header_hidden = True
        self._indentation = max(0, int(indentation))
        self._row_height = int(row_height or QtFusionMetrics.ROW_HEIGHT)
        self._icon_size = (int(icon_size[0]), int(icon_size[1]))
        self._root_spacing = max(0, int(root_spacing))
        self._expand_on_item_click = False
        self._text_overlay = None
        self._root_sections_visible = True

    def setRootSectionsVisible(self, visible):
        """Show section headers, or present their children as a flat Places list."""
        self._root_sections_visible = bool(visible)
        self._rebuild()

    def setItemTextOverlay(self, *, size=13, color=(32, 32, 32, 255)):
        """Paint pixel-aligned icon/text rows above the native hit surface.

        Used by QFileDialog-style navigation panes whose compact labels must
        not depend on the current font's space-glyph width. The Selectable
        remains the full-row selection and pointer target.
        """
        self._text_overlay = {"size": float(size), "color": tuple(color)}
        self._rebuild()

    def setHeaderHidden(self, hidden=True):
        self._header_hidden = bool(hidden)

    def isHeaderHidden(self):
        return self._header_hidden

    def setIndentation(self, indentation):
        indentation = max(0, int(indentation))
        if indentation != self._indentation:
            self._indentation = indentation
            self._rebuild()

    def indentation(self):
        return self._indentation

    def setIconSize(self, size):
        width, height = size
        size = (max(1, int(width)), max(1, int(height)))
        if size != self._icon_size:
            self._icon_size = size
            self._rebuild()

    def iconSize(self):
        return self._icon_size

    def setRootSpacing(self, spacing):
        spacing = max(0, int(spacing))
        if spacing != self._root_spacing:
            self._root_spacing = spacing
            self._rebuild()

    def rootSpacing(self):
        return self._root_spacing

    def setExpandOnItemClick(self, enabled):
        self._expand_on_item_click = bool(enabled)

    def addTopLevelItem(self, item):
        return self.insertTopLevelItem(len(self._top_level), item)

    def addTopLevelItems(self, items):
        return [self.addTopLevelItem(item) for item in list(items or ())]

    def insertTopLevelItem(self, index, item):
        if not isinstance(item, QTreeWidgetItem):
            raise TypeError("top-level item must be QTreeWidgetItem")
        old_tree = item._tree
        if item._parent_item is not None:
            item._parent_item._children.remove(item)
            item._parent_item = None
        elif old_tree is not None and item in old_tree._top_level:
            old_tree._top_level.remove(item)
        item._set_tree(self)
        index = max(0, min(int(index), len(self._top_level)))
        self._top_level.insert(index, item)
        if old_tree is not None and old_tree is not self:
            old_tree._rebuild()
        self._rebuild()
        return item

    def takeTopLevelItem(self, index):
        index = int(index)
        if not 0 <= index < len(self._top_level):
            return None
        item = self._top_level.pop(index)
        item._set_tree(None)
        if self._current is item or self._is_descendant(self._current, item):
            self.setCurrentItem(None)
        self._rebuild()
        return item

    def topLevelItem(self, index):
        index = int(index)
        return self._top_level[index] if 0 <= index < len(self._top_level) else None

    def topLevelItemCount(self):
        return len(self._top_level)

    def indexOfTopLevelItem(self, item):
        try:
            return self._top_level.index(item)
        except ValueError:
            return -1

    def invisibleRootItem(self):
        # Qt returns a synthetic root.  Returning a lightweight facade would
        # complicate ownership; callers can use topLevelItem* for mutation.
        return None

    def clear(self):
        for item in self._top_level:
            item._set_tree(None)
        self._top_level.clear()
        self._current = None
        self._rebuild()

    def currentItem(self):
        return self._current

    def setCurrentItem(self, item, column=0):
        del column
        if item is not None and (not isinstance(item, QTreeWidgetItem) or item._tree is not self):
            return False
        if item is not None and not item.isEnabled():
            return False
        previous = self._current
        if previous is item:
            return True
        if previous is not None:
            previous._selected = False
        self._current = item
        if item is not None:
            item._selected = True
        self._sync_selection()
        self.currentItemChanged.emit(item, previous)
        self.itemSelectionChanged.emit()
        return True

    def selectedItems(self):
        return [self._current] if self._current is not None else []

    def expandItem(self, item):
        if isinstance(item, QTreeWidgetItem) and item._tree is self:
            item.setExpanded(True)
            return True
        return False

    def collapseItem(self, item):
        if isinstance(item, QTreeWidgetItem) and item._tree is self:
            item.setExpanded(False)
            return True
        return False

    def expandAll(self):
        for item, _depth in self._walk(all_items=True):
            if item.childCount():
                item._expanded = True
        self._rebuild()

    def collapseAll(self):
        for item, _depth in self._walk(all_items=True):
            if item.childCount():
                item._expanded = False
        self._rebuild()

    def nativeItem(self, item):
        visual = self._rendered.get(item)
        return visual.get("selectable") if visual else None

    def nativeRow(self, item):
        visual = self._rendered.get(item)
        return visual.get("row") if visual else None

    def itemAt(self, point):
        try:
            x, y = map(float, point)
        except Exception:
            return None
        for item, visual in tuple(self._rendered.items()):
            row = visual.get("row")
            try:
                left, top = self.backend.get_item_rect_min(row)
                width, height = self.backend.get_item_rect_size(row)
            except Exception:
                continue
            if left <= x < left + width and top <= y < top + height:
                return item
        return None

    def _is_descendant(self, item, parent):
        current = item
        while current is not None:
            if current is parent:
                return True
            current = current.parent()
        return False

    def _walk(self, *, all_items=False):
        result = []
        def visit(item, depth):
            if item.isHidden():
                return
            result.append((item, depth))
            if all_items or item.isExpanded():
                for child in item._children:
                    visit(child, depth + 1)
        for root in self._top_level:
            if all_items or self._root_sections_visible:
                visit(root, 0)
            elif not root.isHidden() and root.isExpanded():
                for child in root._children:
                    visit(child, 0)
        return result

    def _visible_label(self, item, depth):
        # Spaces reserve pixels for indentation, branch indicator and icon
        # while preserving the native Selectable text/highlight behavior.
        indent_spaces = max(0, int(round((depth * self._indentation) / 4.0)))
        branch_spaces = 4 if item.childCount() else 2
        icon_spaces = 5 if item.icon(0) is not None else 0
        return (" " * (indent_spaces + branch_spaces + icon_spaces)) + item.text(0)

    def _clear_native(self):
        for registry in self._handler_registries:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handler_registries.clear()
        try:
            self.backend.delete_item(self.tag, children_only=True)
        except TypeError:
            for child in list(self.backend.get_item_children(self.tag, 1) or []):
                try:
                    self.backend.delete_item(child)
                except Exception:
                    pass
        except Exception:
            pass
        self._rendered.clear()
        self._item_by_native.clear()

    def _rebuild(self):
        if getattr(self, "_deleted", False):
            return
        self._clear_native()
        first_root = True
        for root in self._top_level:
            if root.isHidden():
                continue
            if not first_root and self._root_spacing:
                try:
                    self.backend.add_child_window(
                        parent=self.tag, width=-1, height=self._root_spacing,
                        border=False, no_scrollbar=True, no_scroll_with_mouse=True)
                except Exception:
                    pass
            first_root = False
            if self._root_sections_visible:
                self._render_item(root, 0)
            if root.isExpanded():
                def render_children(parent, depth):
                    for child in parent._children:
                        if child.isHidden():
                            continue
                        self._render_item(child, depth)
                        if child.isExpanded():
                            render_children(child, depth + 1)
                render_children(root, 1 if self._root_sections_visible else 0)
        self._sync_selection()
        self.layoutChanged.emit()

    def _render_item(self, item, depth):
        b = self.backend
        row = b.add_child_window(
            parent=self.tag, width=-1, height=self._row_height,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        if item.containerTheme() is not None:
            try:
                b.bind_item_theme(row, item.containerTheme())
            except Exception:
                pass
        native_user_data = item.data(0, Qt.UserRole)
        if native_user_data is None:
            native_user_data = item.key
        selectable = b.add_selectable(
            # Selectable follows ImGui semantics: zero fills the available
            # row, whereas -1 is a literal negative width (unlike ChildWindow).
            # A negative rectangle clips both text and interaction entirely.
            parent=row, label="" if self._text_overlay else self._visible_label(item, depth), width=0,
            height=self._row_height, default_value=(item is self._current),
            enabled=item.isEnabled(), callback=self._native_clicked,
            user_data=native_user_data)
        if item.rowTheme() is not None:
            try:
                b.bind_item_theme(selectable, item.rowTheme())
            except Exception:
                pass
        tooltip = item.toolTip(0)
        if tooltip:
            try:
                from ..tooltip import add_styled_tooltip
                add_styled_tooltip(row, tooltip, backend=b)
            except Exception:
                pass
        visual = {"row": row, "selectable": selectable, "depth": depth,
                  "overlay": None, "icon": None, "text": None}
        self._rendered[item] = visual
        self._item_by_native[selectable] = item

        # Draw only decoration/branch geometry.  Text remains owned by the
        # Selectable so selected/disabled colors follow the active backend theme.
        try:
            draw_width = max(1, int(b.get_item_rect_size(self.tag)[0] or 256))
        except Exception:
            draw_width = 256
        try:
            # DPG 2.x Drawlist ignores its own pos when rendering. An explicit
            # positioned Group resets the cursor before the visual layer;
            # otherwise it flows below the Selectable and is entirely clipped.
            anchor = b.add_group(parent=row, pos=(0, 0))
            overlay = b.add_drawlist(draw_width, self._row_height, parent=anchor)
            visual["overlay"] = overlay
            x = depth * self._indentation + (1 if self._text_overlay else 5)
            mid = self._row_height // 2
            if item.childCount():
                if item.isExpanded():
                    b.draw_triangle((x, mid - 3), (x + 8, mid - 3), (x + 4, mid + 2),
                                    fill=(120, 120, 120, 255), parent=overlay)
                else:
                    b.draw_triangle((x + 1, mid - 5), (x + 1, mid + 4), (x + 6, mid),
                                    fill=(120, 120, 120, 255), parent=overlay)
                x += 21 if self._text_overlay else 13
            elif self._text_overlay:
                x += 4
            icon = item.icon(0)
            if icon is not None:
                iw, ih = self._icon_size
                y = max(0, (self._row_height - ih) // 2)
                image = b.draw_image(icon, (x, y), (x + iw, y + ih), parent=overlay)
                visual["icon"] = image
            if self._text_overlay:
                # Match the original selector: root label x=24, root icon
                # x=22/text x=43; child icon x=indent+5/text x=indent+28.
                if icon is not None:
                    text_x = x + self._icon_size[0] + (5 if item.childCount() else 7)
                else:
                    text_x = x + (2 if item.childCount() else 0)
                try:
                    text_height = float(b.get_text_size(item.text(0) or "Ag")[1])
                except Exception:
                    text_height = self._text_overlay["size"]
                text_y = max(0, int(round((self._row_height - text_height) * 0.5)))
                visual["text"] = b.draw_text(
                    (text_x, text_y), item.text(0), parent=overlay,
                    size=self._text_overlay["size"], color=self._text_overlay["color"])
            registry = b.add_item_handler_registry()
            b.add_item_clicked_handler(
                parent=registry, button=b.mvMouseButton_Left,
                callback=self._overlay_clicked, user_data=native_user_data)
            b.bind_item_handler_registry(overlay, registry)
            self._handler_registries.append(registry)
            self._item_by_native[overlay] = item
        except Exception:
            pass

    def _item_for_sender(self, sender):
        item = self._item_by_native.get(sender)
        if item is not None:
            return item
        # Item handler callbacks use the handler as sender. Resolve by the
        # user_data value only as a fallback; current rendered rows are tiny.
        return None

    def _item_for_user_data(self, user_data):
        for item in self._rendered:
            value = item.data(0, Qt.UserRole)
            if (value if value is not None else item.key) == user_data:
                return item
        return None

    def _native_clicked(self, sender, app_data=None, user_data=None):
        item = self._item_by_native.get(sender) or self._item_for_user_data(user_data)
        self._activate_pointer_item(item, sender, app_data)

    def _overlay_clicked(self, sender, app_data=None, user_data=None):
        item = self._item_for_user_data(user_data)
        self._activate_pointer_item(item, sender, app_data)

    def _activate_pointer_item(self, item, sender=None, app_data=None):
        del sender, app_data
        if item is None or not item.isEnabled():
            return
        self.setCurrentItem(item)
        self.itemClicked.emit(item, 0)
        double = False
        try:
            double = bool(self.backend.is_mouse_button_double_clicked(self.backend.mvMouseButton_Left))
        except Exception:
            pass
        if double:
            self.itemDoubleClicked.emit(item, 0)
            self.itemActivated.emit(item, 0)
        if item.childCount() and self._expand_on_item_click and not double:
            item.setExpanded(not item.isExpanded())

    def _sync_selection(self):
        for item, visual in tuple(self._rendered.items()):
            selected = item is self._current
            item._selected = selected
            try:
                self.backend.set_value(visual["selectable"], selected)
            except Exception:
                pass

    def _item_expansion_changed(self, item):
        self._rebuild()
        (self.itemExpanded if item.isExpanded() else self.itemCollapsed).emit(item)

    def _item_changed(self, item, column, role):
        visual = self._rendered.get(item)
        if visual is not None and column == 0:
            try:
                if role == Qt.DisplayRole:
                    if visual.get("text") is not None:
                        self.backend.configure_item(visual["text"], text=item.text(0))
                    else:
                        self.backend.configure_item(
                            visual["selectable"], label=self._visible_label(item, visual["depth"]))
                elif role == Qt.DecorationRole:
                    if visual.get("icon") is not None and item.icon(0) is not None:
                        self.backend.configure_item(visual["icon"], texture_tag=item.icon(0))
                    else:
                        # Adding/removing decoration changes the text inset and
                        # native draw primitive set, so rebuild the visible tree.
                        self._rebuild()
                elif role == Qt.ToolTipRole:
                    self._rebuild()
                elif role in (Qt.UserRole - 1, Qt.UserRole - 2, Qt.UserRole - 3):
                    self._rebuild()
            except Exception:
                pass
        self.itemChanged.emit(item, column)

    def delete(self):
        self._clear_native()
        for item in self._top_level:
            item._set_tree(None)
        self._top_level.clear()
        super().delete()


__all__ = ["QTreeWidget", "QTreeWidgetItem"]
