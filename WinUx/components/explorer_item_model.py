"""GUI-independent row ordering and identity reconciliation for Explorer."""
from __future__ import annotations

from dataclasses import dataclass
import os


def stable_item_identity(item):
    data = getattr(item, "data", None) or {}
    job_id = data.get("job_id")
    if job_id not in (None, ""):
        return ("job", str(job_id))
    path = str(getattr(item, "path", "") or "")
    if path:
        return ("path", os.path.normcase(path))
    return ("name", str(getattr(item, "name", "") or ""))


@dataclass
class RowReconciliation:
    old_topology: list
    new_topology: list
    selected: set
    anchor: object
    current: object


class ExplorerItemModel:
    def __init__(self):
        self.items = []

    def sort(self, key="name", ascending=True):
        def value(item):
            if key == "date":
                return item.mtime
            if key == "size":
                return item.size
            if key == "type":
                cached = getattr(item, "cached_type_sort", None)
                return cached if cached is not None else item.item_type.casefold()
            cached = getattr(item, "cached_name_sort", None)
            return cached if cached is not None else item.name.casefold()

        parents, folders, files = [], [], []
        for item in self.items:
            group = parents if item.is_dir and item.name == ".." else folders if item.is_dir else files
            group.append(item)
        reverse = not ascending
        folders.sort(key=value, reverse=reverse)
        files.sort(key=value, reverse=reverse)
        self.items = parents + folders + files

    def replace(self, items, selected=(), anchor=None, current=None,
                key="name", ascending=True, identity=stable_item_identity):
        old_topology = [identity(item) for item in self.items]
        selected_keys = {old_topology[index] for index in selected
                         if 0 <= index < len(old_topology)}
        def old_key(index):
            return old_topology[index] if index is not None and 0 <= index < len(old_topology) else None
        anchor_key, current_key = old_key(anchor), old_key(current)
        self.items = list(items)
        self.sort(key, ascending)
        new_topology = [identity(item) for item in self.items]
        new_selected, new_anchor, new_current = set(), None, None
        for index, item_key in enumerate(new_topology):
            if item_key in selected_keys:
                new_selected.add(index)
            if anchor_key is not None and new_anchor is None and item_key == anchor_key:
                new_anchor = index
            if current_key is not None and new_current is None and item_key == current_key:
                new_current = index
        if new_current is None and new_selected:
            new_current = min(new_selected)
        return RowReconciliation(old_topology, new_topology, new_selected, new_anchor, new_current)

    def reorder(self, selected=(), anchor=None, current=None, key="name", ascending=True):
        selected_ids = {id(self.items[index]) for index in selected if 0 <= index < len(self.items)}
        def object_id(index):
            return id(self.items[index]) if index is not None and 0 <= index < len(self.items) else None
        anchor_id, current_id = object_id(anchor), object_id(current)
        self.sort(key, ascending)
        new_selected, new_anchor, new_current = set(), None, None
        for index, item in enumerate(self.items):
            item_id = id(item)
            if item_id in selected_ids:
                new_selected.add(index)
            if new_anchor is None and item_id == anchor_id:
                new_anchor = index
            if new_current is None and item_id == current_id:
                new_current = index
        if new_current is None and new_selected:
            new_current = min(new_selected)
        return RowReconciliation([], [], new_selected, new_anchor, new_current)
