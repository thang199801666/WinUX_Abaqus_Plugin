"""Dependency-free dock layout topology used by :mod:`DearUIQt.docking`.

The model mirrors the part of ``QMainWindow``'s dock layout that matters to a
retained-mode host: each dock area owns a recursive tree of split nodes and tab
nodes.  Rendering is deliberately kept out of this module so layout/state logic
can be validated without Dear PyGui or a native windowing backend.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Dict, Iterable, Optional


class DockLayoutTree:
    """Recursive split/tab topology for QMainWindow-like dock sites."""

    AREAS = ("left", "right", "top", "bottom")
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"

    def __init__(self):
        self.roots: Dict[str, Optional[dict]] = {area: None for area in self.AREAS}
        self._group_counter = 0

    @classmethod
    def normalize_area(cls, area):
        value = str(area or "right").strip().lower()
        return value if value in cls.AREAS else "right"

    @classmethod
    def normalize_orientation(cls, orientation):
        # DearUIQt.Qt follows Qt: Horizontal=1, Vertical=2.  Accept strings too
        # so this model remains dependency-free and straightforward to persist.
        if orientation in (2, "2"):
            return cls.VERTICAL
        value = str(orientation or "horizontal").strip().lower()
        if value in ("vertical", "v", "bottom", "top"):
            return cls.VERTICAL
        return cls.HORIZONTAL

    def _next_group_id(self):
        self._group_counter += 1
        return "dock-tabs-{}".format(self._group_counter)

    def _tabs(self, keys=(), active=None, group_id=None):
        keys = [str(key) for key in keys if str(key)]
        if active not in keys:
            active = keys[-1] if keys else None
        return {
            "type": "tabs",
            "id": str(group_id or self._next_group_id()),
            "keys": keys,
            "active": active,
        }

    @staticmethod
    def _split(orientation, first, second, weights=None):
        weights = list(weights or (1.0, 1.0))[:2]
        while len(weights) < 2:
            weights.append(1.0)
        weights = [max(0.0001, float(weight)) for weight in weights]
        total = sum(weights) or 1.0
        return {
            "type": "split",
            "orientation": DockLayoutTree.normalize_orientation(orientation),
            "weights": [weight / total for weight in weights],
            "children": [first, second],
        }

    def clear(self):
        for area in self.AREAS:
            self.roots[area] = None

    def _walk(self, node, parent=None, index=None):
        if node is None:
            return
        yield node, parent, index
        if node.get("type") == "split":
            for child_index, child in enumerate(node.get("children") or ()):
                yield from self._walk(child, node, child_index)

    def _find(self, key):
        key = str(key)
        for area in self.AREAS:
            root = self.roots.get(area)
            for node, parent, index in self._walk(root):
                if node.get("type") == "tabs" and key in node.get("keys", ()):
                    return area, node, parent, index
        return None

    def contains(self, key):
        return self._find(key) is not None

    def area_of(self, key):
        found = self._find(key)
        return found[0] if found is not None else None

    def group_of(self, key):
        found = self._find(key)
        return found[1] if found is not None else None

    def group_id_of(self, key):
        group = self.group_of(key)
        return None if group is None else group.get("id")

    def group_keys(self, key):
        group = self.group_of(key)
        return tuple(group.get("keys") or ()) if group is not None else ()

    def tabified(self, key):
        key = str(key)
        return tuple(candidate for candidate in self.group_keys(key) if candidate != key)

    def active_for(self, key):
        group = self.group_of(key)
        return None if group is None else group.get("active")

    def set_active(self, key):
        key = str(key)
        group = self.group_of(key)
        if group is None or key not in group.get("keys", ()):
            return False
        changed = group.get("active") != key
        group["active"] = key
        return changed

    def _replace_node(self, area, parent, index, replacement):
        if parent is None:
            self.roots[area] = replacement
        else:
            parent["children"][index] = replacement

    def _prune(self, area, node, parent=None, index=None):
        if node is None:
            return None
        if node.get("type") == "tabs":
            keys = list(node.get("keys") or ())
            if not keys:
                self._replace_node(area, parent, index, None)
                return None
            if node.get("active") not in keys:
                node["active"] = keys[-1]
            return node
        children = [child for child in node.get("children") or () if child is not None]
        node["children"] = children
        if not children:
            self._replace_node(area, parent, index, None)
            return None
        if len(children) == 1:
            self._replace_node(area, parent, index, children[0])
            return children[0]
        weights = list(node.get("weights") or ())[:len(children)]
        while len(weights) < len(children):
            weights.append(1.0)
        weights = [max(0.0001, float(weight)) for weight in weights]
        total = sum(weights) or 1.0
        node["weights"] = [weight / total for weight in weights]
        return node

    def remove(self, key):
        key = str(key)
        found = self._find(key)
        if found is None:
            return False
        area, group, parent, index = found
        keys = group.get("keys") or []
        keys.remove(key)
        if group.get("active") == key:
            group["active"] = keys[-1] if keys else None
        if not keys:
            self._replace_node(area, parent, index, None)
            # Collapse empty/single-child ancestors from the root down. A small
            # fixed-point pass keeps the code robust for arbitrarily deep trees.
            changed = True
            while changed:
                changed = False
                root = self.roots.get(area)
                for node, node_parent, node_index in list(self._walk(root)):
                    if node.get("type") != "split":
                        continue
                    before = len(node.get("children") or ())
                    replacement = self._prune(area, node, node_parent, node_index)
                    after = (len(replacement.get("children") or ())
                             if isinstance(replacement, dict)
                             and replacement.get("type") == "split" else -1)
                    if replacement is not node or before != after:
                        changed = True
                        break
        return True

    def rename(self, old_key, new_key):
        old_key, new_key = str(old_key), str(new_key)
        if not old_key or not new_key or old_key == new_key:
            return bool(old_key and self.contains(old_key))
        if self.contains(new_key):
            return False
        group = self.group_of(old_key)
        if group is None:
            return False
        keys = group.get("keys") or []
        keys[keys.index(old_key)] = new_key
        if group.get("active") == old_key:
            group["active"] = new_key
        return True

    def add_tab(self, key, area="right", *, activate=True, target=None):
        key = str(key)
        if not key:
            return False
        area = self.normalize_area(area)
        if self.contains(key):
            self.remove(key)
        root = self.roots.get(area)
        if root is None:
            self.roots[area] = self._tabs((key,), active=key)
            return True
        group = self.group_of(target) if target is not None else None
        if group is None or self.area_of(target) != area:
            # Preserve DearUIQt's historical addDockWidget behaviour: a new
            # dock in an occupied site joins the last tab group unless the
            # caller explicitly requests splitDockWidget().
            groups = [node for node, _parent, _index in self._walk(root)
                      if node.get("type") == "tabs"]
            group = groups[-1] if groups else None
        if group is None:
            self.roots[area] = self._tabs((key,), active=key)
            return True
        group.setdefault("keys", []).append(key)
        if activate:
            group["active"] = key
        return True

    def move_area_root(self, source_area, target_area):
        """Move one complete area topology when the destination is empty."""
        source_area = self.normalize_area(source_area)
        target_area = self.normalize_area(target_area)
        if source_area == target_area:
            return True
        root = self.roots.get(source_area)
        if root is None:
            return False
        if self.roots.get(target_area) is not None:
            return False
        self.roots[target_area] = root
        self.roots[source_area] = None
        return True

    def move_to_area(self, key, area, *, target=None, activate=True):
        key = str(key)
        existed = self.contains(key)
        if existed:
            self.remove(key)
        self.add_tab(key, self.normalize_area(area), activate=activate, target=target)
        return True

    def tabify(self, first, second):
        first, second = str(first), str(second)
        if not first or not second or first == second:
            return False
        found = self._find(first)
        if found is None:
            return False
        area, group, _parent, _index = found
        if second in group.get("keys", ()):
            group["active"] = second
            return True
        if self.contains(second):
            self.remove(second)
            # first's parent may have collapsed after removing second.
            found = self._find(first)
            if found is None:
                return False
            area, group, _parent, _index = found
        group.setdefault("keys", []).append(second)
        group["active"] = second
        return True

    def split(self, first, second, orientation):
        """Split *first* and place *second* after it in Qt orientation order.

        When *first* belongs to a tab group with more than one dock, Qt adds
        *second* as another tab instead of creating a neighboring split.  The
        return value is ``"tabified"`` or ``"split"`` when successful.
        """
        first, second = str(first), str(second)
        if not first or not second or first == second:
            return False
        found = self._find(first)
        if found is None:
            return False
        area, first_group, parent, index = found
        if len(first_group.get("keys") or ()) > 1:
            return "tabified" if self.tabify(first, second) else False
        if self.contains(second):
            self.remove(second)
            found = self._find(first)
            if found is None:
                return False
            area, first_group, parent, index = found
        second_group = self._tabs((second,), active=second)
        split = self._split(orientation, first_group, second_group)
        self._replace_node(area, parent, index, split)
        return "split"

    def dock_relative(self, target, moving, zone):
        """Move *moving* relative to *target* using a QMainWindow drop zone.

        ``center`` tabifies the moving dock with the complete target tab leaf.
        ``left``/``right`` create a horizontal split and ``top``/``bottom`` a
        vertical split.  Unlike :meth:`split`, an edge drop intentionally
        splits the *whole target tab group* even when it already contains
        several tabs; this mirrors interactive QMainWindow docking feedback.

        The method is dependency-free so drag/drop topology can be validated
        without Dear PyGui or a native windowing backend.
        """
        target, moving = str(target), str(moving)
        zone = str(zone or "center").strip().lower()
        if (not target or not moving or target == moving
                or zone not in ("left", "right", "top", "bottom", "center")):
            return False
        if self._find(target) is None:
            return False
        if zone == "center":
            return "tabified" if self.tabify(target, moving) else False

        # Remove the moving dock first.  When it came from the same tab leaf,
        # pruning may collapse ancestors, so always refind the target after the
        # mutation before replacing its leaf in the tree.
        if self.contains(moving):
            self.remove(moving)
        found = self._find(target)
        if found is None:
            return False
        area, target_group, parent, index = found
        moving_group = self._tabs((moving,), active=moving)
        orientation = (
            self.HORIZONTAL if zone in ("left", "right") else self.VERTICAL)
        before = zone in ("left", "top")
        if before:
            replacement = self._split(orientation, moving_group, target_group)
        else:
            replacement = self._split(orientation, target_group, moving_group)
        self._replace_node(area, parent, index, replacement)
        return "split"


    def _detach_group(self, key):
        """Detach and return the complete tab leaf containing *key*.

        This is the topology primitive needed by QMainWindow::GroupedDragging:
        unlike :meth:`remove`, every tab in the source leaf moves together and
        the original group id/active tab are preserved.
        """
        key = str(key)
        found = self._find(key)
        if found is None:
            return None
        area, group, parent, index = found
        self._replace_node(area, parent, index, None)

        # Collapse empty/single-child ancestors after removing the whole leaf.
        changed = True
        while changed:
            changed = False
            root = self.roots.get(area)
            for node, node_parent, node_index in list(self._walk(root)):
                if node.get("type") != "split":
                    continue
                before = len(node.get("children") or ())
                replacement = self._prune(area, node, node_parent, node_index)
                after = (len(replacement.get("children") or ())
                         if isinstance(replacement, dict)
                         and replacement.get("type") == "split" else -1)
                if replacement is not node or before != after:
                    changed = True
                    break
        return area, group

    def dock_group_relative(self, target, moving, zone):
        """Move the complete tab group containing *moving* relative to *target*.

        ``center`` merges both groups while preserving the source tab order and
        active tab. Edge zones move the source tab leaf as one unit, which is
        the dependency-free topology counterpart of QMainWindow::GroupedDragging.
        """
        target, moving = str(target), str(moving)
        zone = str(zone or "center").strip().lower()
        if (not target or not moving or target == moving
                or zone not in ("left", "right", "top", "bottom", "center")):
            return False
        source = self.group_of(moving)
        target_group = self.group_of(target)
        if source is None or target_group is None or source is target_group:
            return False
        source_keys = tuple(source.get("keys") or ())
        if not source_keys:
            return False
        source_active = source.get("active")

        detached = self._detach_group(moving)
        if detached is None:
            return False
        _source_area, moving_group = detached

        # Always re-find the target after pruning the source branch.
        found = self._find(target)
        if found is None:
            # Defensive rollback: keep the detached group reachable rather than
            # silently losing docks if a malformed topology was supplied.
            self.roots[self.normalize_area(_source_area)] = moving_group
            return False
        area, target_group, parent, index = found

        if zone == "center":
            target_keys = target_group.setdefault("keys", [])
            for candidate in source_keys:
                if candidate not in target_keys:
                    target_keys.append(candidate)
            target_group["active"] = (
                source_active if source_active in target_keys else target_keys[-1])
            return "tabified"

        orientation = (
            self.HORIZONTAL if zone in ("left", "right") else self.VERTICAL)
        before = zone in ("left", "top")
        replacement = (
            self._split(orientation, moving_group, target_group)
            if before else self._split(orientation, target_group, moving_group))
        self._replace_node(area, parent, index, replacement)
        return "split"

    def reorder_tab(self, key, index):
        key = str(key)
        group = self.group_of(key)
        if group is None:
            return False
        keys = group.get("keys") or []
        if key not in keys:
            return False
        old_index = keys.index(key)
        index = max(0, min(int(index), len(keys) - 1))
        if old_index == index:
            return False
        keys.pop(old_index)
        keys.insert(index, key)
        return True

    def flatten_keys(self, area=None):
        areas = (self.normalize_area(area),) if area is not None else self.AREAS
        result = []
        for candidate_area in areas:
            for node, _parent, _index in self._walk(self.roots.get(candidate_area)):
                if node.get("type") == "tabs":
                    result.extend(node.get("keys") or ())
        return tuple(result)

    def _visible(self, node, visible):
        if node is None:
            return False
        if node.get("type") == "tabs":
            return any(key in visible for key in node.get("keys") or ())
        return any(self._visible(child, visible) for child in node.get("children") or ())

    def layout_details(
            self, area, width, height, *, x=0, y=0, visible_keys=None,
            handle_width=0, handle_hit_width=None):
        """Return visible tab groups plus splitter-handle geometry.

        ``handle_width`` is the visual separator thickness that participates in
        geometry allocation.  ``handle_hit_width`` may be larger than the
        visible separator, mirroring Qt's QSplitter behavior where a 0/1 px
        handle still receives a wider mouse-grab target.  Passing the default
        handle width of zero preserves the pre-r69 layout contract exactly.
        """
        area = self.normalize_area(area)
        visible = (set(map(str, visible_keys)) if visible_keys is not None
                   else set(self.flatten_keys(area)))
        handle_width = max(0, int(handle_width or 0))
        if handle_hit_width is None:
            handle_hit_width = handle_width
        handle_hit_width = max(handle_width, int(handle_hit_width or 0))
        groups = []
        handles = []

        def visit(node, rx, ry, rw, rh, path=()):
            if node is None or not self._visible(node, visible):
                return
            if node.get("type") == "tabs":
                keys = [key for key in node.get("keys") or () if key in visible]
                if not keys:
                    return
                active = node.get("active") if node.get("active") in keys else keys[-1]
                groups.append({
                    "group_id": node.get("id"),
                    "keys": tuple(keys),
                    "active": active,
                    "rect": (int(rx), int(ry), max(1, int(rw)), max(1, int(rh))),
                })
                return

            original = list(node.get("children") or ())
            visible_children = [
                (index, child) for index, child in enumerate(original)
                if self._visible(child, visible)
            ]
            if not visible_children:
                return
            if len(visible_children) == 1:
                child_index, child = visible_children[0]
                visit(child, rx, ry, rw, rh, path + (child_index,))
                return

            weights = list(node.get("weights") or ())
            child_weights = []
            for child_index, _child in visible_children:
                try:
                    child_weights.append(max(0.0001, float(weights[child_index])))
                except Exception:
                    child_weights.append(1.0)
            total = sum(child_weights) or 1.0
            normalized = [weight / total for weight in child_weights]
            horizontal = node.get("orientation") == self.HORIZONTAL
            extent = max(1, int(rw if horizontal else rh))
            separator_total = handle_width * max(0, len(visible_children) - 1)
            content_extent = max(len(visible_children), extent - separator_total)
            sizes = []
            used = 0
            for visible_index, weight in enumerate(normalized):
                if visible_index == len(normalized) - 1:
                    size = max(1, content_extent - used)
                else:
                    size = max(1, int(round(content_extent * weight)))
                    remaining_children = len(normalized) - visible_index - 1
                    size = min(
                        size, max(1, content_extent - used - remaining_children))
                sizes.append(size)
                used += size

            cursor_x, cursor_y = int(rx), int(ry)
            for visible_index, ((child_index, child), size) in enumerate(
                    zip(visible_children, sizes)):
                if horizontal:
                    child_rect = (cursor_x, int(ry), size, max(1, int(rh)))
                    visit(
                        child, child_rect[0], child_rect[1], child_rect[2],
                        child_rect[3], path + (child_index,))
                    cursor_x += size
                else:
                    child_rect = (int(rx), cursor_y, max(1, int(rw)), size)
                    visit(
                        child, child_rect[0], child_rect[1], child_rect[2],
                        child_rect[3], path + (child_index,))
                    cursor_y += size

                if visible_index >= len(visible_children) - 1:
                    continue

                next_child_index = visible_children[visible_index + 1][0]
                if horizontal:
                    visual_rect = (
                        cursor_x, int(ry), handle_width, max(1, int(rh)))
                    center = cursor_x + handle_width * 0.5
                    hit_x = int(round(center - handle_hit_width * 0.5))
                    hit_rect = (
                        hit_x, int(ry), max(1, handle_hit_width),
                        max(1, int(rh)))
                    cursor_x += handle_width
                else:
                    visual_rect = (
                        int(rx), cursor_y, max(1, int(rw)), handle_width)
                    center = cursor_y + handle_width * 0.5
                    hit_y = int(round(center - handle_hit_width * 0.5))
                    hit_rect = (
                        int(rx), hit_y, max(1, int(rw)),
                        max(1, handle_hit_width))
                    cursor_y += handle_width

                handles.append({
                    "area": area,
                    "path": tuple(path),
                    "orientation": (
                        self.HORIZONTAL if horizontal else self.VERTICAL),
                    "before_index": child_index,
                    "after_index": next_child_index,
                    "before_extent": int(size),
                    "after_extent": int(sizes[visible_index + 1]),
                    "rect": tuple(map(int, visual_rect)),
                    "hit_rect": tuple(map(int, hit_rect)),
                    "split_rect": (
                        int(rx), int(ry), max(1, int(rw)), max(1, int(rh))),
                })

        visit(
            self.roots.get(area), int(x), int(y), max(1, int(width)),
            max(1, int(height)))
        return {"groups": tuple(groups), "handles": tuple(handles)}

    def layout(self, area, width, height, *, x=0, y=0, visible_keys=None):
        """Return visible tab groups with recursively allocated rectangles."""
        return self.layout_details(
            area, width, height, x=x, y=y, visible_keys=visible_keys
        )["groups"]

    def _split_node_at_path(self, area, path):
        node = self.roots.get(self.normalize_area(area))
        try:
            indexes = tuple(int(index) for index in path)
        except Exception:
            return None
        for index in indexes:
            if not isinstance(node, dict) or node.get("type") != "split":
                return None
            children = node.get("children") or ()
            if index < 0 or index >= len(children):
                return None
            node = children[index]
        if not isinstance(node, dict) or node.get("type") != "split":
            return None
        return node

    def resize_split_handle(
            self, area, path, before_index, after_index,
            before_size, after_size):
        """Resize one visible split pair by updating their relative weights.

        The topology remains unchanged; only the two selected child weights are
        redistributed. Hidden siblings (if a future non-binary state contains
        them) retain their share.
        """
        node = self._split_node_at_path(area, path)
        if node is None:
            return False
        children = list(node.get("children") or ())
        try:
            before_index = int(before_index)
            after_index = int(after_index)
            before_size = max(1.0, float(before_size))
            after_size = max(1.0, float(after_size))
        except Exception:
            return False
        if (before_index < 0 or after_index < 0
                or before_index >= len(children) or after_index >= len(children)
                or before_index == after_index):
            return False
        weights = list(node.get("weights") or ())
        while len(weights) < len(children):
            weights.append(1.0)
        weights = [max(0.0001, float(weight)) for weight in weights]
        pair_total = weights[before_index] + weights[after_index]
        requested_total = before_size + after_size
        weights[before_index] = pair_total * (before_size / requested_total)
        weights[after_index] = pair_total * (after_size / requested_total)
        total = sum(weights) or 1.0
        node["weights"] = [weight / total for weight in weights]
        return True

    @staticmethod
    def clamp_split_pair(before_size, after_size, delta, minimum=1):
        """Clamp a splitter drag while preserving the pair's total extent."""
        before = max(1.0, float(before_size))
        after = max(1.0, float(after_size))
        total = before + after
        minimum = max(1.0, float(minimum))
        # A very small container cannot satisfy two full minimums. In that
        # case split the available extent evenly rather than inverting a pane.
        minimum = min(minimum, max(1.0, (total - 1.0) * 0.5))
        target_before = before + float(delta)
        target_before = max(minimum, min(total - minimum, target_before))
        return target_before, total - target_before

    def resize_docks(self, docks, sizes, orientation):
        """Adjust sibling split weights using QMainWindow::resizeDocks rules."""
        keys = [str(key) for key in docks]
        requested = [max(1.0, float(size)) for size in sizes]
        if not keys or len(keys) != len(requested):
            return False
        orientation = self.normalize_orientation(orientation)
        located = [self._find(key) for key in keys]
        if any(found is None for found in located):
            return False
        parents = [found[2] for found in located]
        if parents[0] is None or any(parent is not parents[0] for parent in parents):
            return False
        parent = parents[0]
        if parent.get("type") != "split" or parent.get("orientation") != orientation:
            return False
        child_indices = [found[3] for found in located]
        if len(set(child_indices)) != len(child_indices):
            return False
        weights = list(parent.get("weights") or ())
        while len(weights) < len(parent.get("children") or ()):
            weights.append(1.0)
        target_total = sum(weights[index] for index in child_indices)
        if target_total <= 0.0:
            target_total = float(len(child_indices)) / max(1, len(weights))
        request_total = sum(requested) or 1.0
        for child_index, size in zip(child_indices, requested):
            weights[child_index] = target_total * (size / request_total)
        total = sum(max(0.0001, weight) for weight in weights) or 1.0
        parent["weights"] = [max(0.0001, weight) / total for weight in weights]
        return True

    def to_state(self, key_encoder=None):
        encode = key_encoder if callable(key_encoder) else (lambda key: key)

        def encode_node(node):
            if node is None:
                return None
            if node.get("type") == "tabs":
                keys = [str(encode(key)) for key in node.get("keys") or ()]
                active = node.get("active")
                return {
                    "type": "tabs",
                    "id": node.get("id"),
                    "keys": keys,
                    "active": None if active is None else str(encode(active)),
                }
            return {
                "type": "split",
                "orientation": self.normalize_orientation(node.get("orientation")),
                "weights": [float(weight) for weight in node.get("weights") or ()],
                "children": [encode_node(child) for child in node.get("children") or ()],
            }

        return {
            "format": 1,
            "areas": {area: encode_node(self.roots.get(area)) for area in self.AREAS},
        }

    @classmethod
    def from_state(cls, state, key_decoder=None):
        tree = cls()
        decode = key_decoder if callable(key_decoder) else (lambda key: key)
        state = dict(state or {})

        def decode_node(raw, depth=0):
            if not isinstance(raw, dict) or depth > 64:
                return None
            kind = str(raw.get("type") or "")
            if kind == "tabs":
                keys = []
                for key in raw.get("keys") or ():
                    decoded = str(decode(str(key)))
                    if decoded and decoded not in keys:
                        keys.append(decoded)
                if not keys:
                    return None
                active_raw = raw.get("active")
                active = str(decode(str(active_raw))) if active_raw is not None else None
                group = tree._tabs(keys, active=active, group_id=raw.get("id"))
                # Keep future-generated ids unique after restoring persisted ids.
                try:
                    suffix = int(str(group["id"]).rsplit("-", 1)[-1])
                    tree._group_counter = max(tree._group_counter, suffix)
                except Exception:
                    pass
                return group
            if kind != "split":
                return None
            children = [decode_node(child, depth + 1) for child in raw.get("children") or ()]
            children = [child for child in children if child is not None]
            if not children:
                return None
            if len(children) == 1:
                return children[0]
            # Persisted trees are binary today; fold extra children safely so a
            # future writer cannot create an unbounded renderer shape here.
            weights = list(raw.get("weights") or ())
            first = children[0]
            for child_index, child in enumerate(children[1:], 1):
                pair = (
                    weights[child_index - 1] if child_index - 1 < len(weights) else 1.0,
                    weights[child_index] if child_index < len(weights) else 1.0,
                )
                first = tree._split(raw.get("orientation"), first, child, pair)
            return first

        areas = dict(state.get("areas") or {})
        for area in cls.AREAS:
            tree.roots[area] = decode_node(areas.get(area))
        return tree

    def copy(self):
        other = DockLayoutTree()
        other.roots = deepcopy(self.roots)
        other._group_counter = self._group_counter
        return other


__all__ = ["DockLayoutTree"]
