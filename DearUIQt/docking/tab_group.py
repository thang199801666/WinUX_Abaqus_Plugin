"""Retained QTabBar-like state for QMainWindow dock groups.

The controller mirrors canonical tab groups owned by :class:`DockLayoutTree`.
It deliberately does not mutate layout topology itself; commands are delegated
back to the owning DockManager so there is only one source of truth for order,
active-tab identity and group membership.
"""
from __future__ import annotations

import weakref

from ..core.object import Signal
from .command import QDockCommand


class QDockTabGroupController:
    """Mirror dock-tab groups and expose Qt-style semantic signals.

    Renderer tab strips remain responsible for pointer hit-testing and drawing.
    DockManager remains the canonical topology owner.  This controller owns the
    retained interaction/state surface consumed by QMainWindow/QDockWidget code.
    """

    def __init__(self, manager=None):
        self.groupChanged = Signal()
        self.activeTabChanged = Signal()
        self.tabOrderChanged = Signal()
        self.tabVisibilityChanged = Signal()
        self.dragStarted = Signal()
        self.dragUpdated = Signal()
        self.dragFinished = Signal()
        self.commandRequested = Signal()
        self.commandFinished = Signal()
        self.commandObjectRequested = Signal()
        self.commandObjectFinished = Signal()
        self.stateChanged = Signal()
        self._manager_ref = None
        self._groups = {}
        self._dock_to_group = {}
        self._drag = None
        if manager is not None:
            self.bindManager(manager)

    def bindManager(self, manager):
        if manager is None:
            self._manager_ref = None
            self.clear()
            return False
        current = self.manager()
        if current is manager:
            return False
        try:
            self._manager_ref = weakref.ref(manager)
        except TypeError:
            self._manager_ref = manager
        self.sync()
        return True

    def manager(self):
        ref = self._manager_ref
        if ref is None:
            return None
        try:
            return ref()
        except TypeError:
            return ref

    @staticmethod
    def _snapshot(group_id, keys, active, visible):
        keys = tuple(str(key) for key in keys)
        visible = tuple(str(key) for key in visible if str(key) in keys)
        active = None if active is None else str(active)
        return {
            "groupId": str(group_id),
            "keys": keys,
            "activeKey": active,
            "visibleKeys": visible,
        }

    def sync(self):
        manager = self.manager()
        if manager is None:
            return False
        tree = getattr(manager, "_layout_tree", None)
        entries = getattr(manager, "_entries", {})
        if tree is None:
            return False

        groups = {}
        dock_to_group = {}
        seen = set()
        for key in tuple(entries):
            group = tree.group_of(key)
            if group is None:
                continue
            group_id = str(group.get("id") or "")
            if not group_id:
                continue
            dock_to_group[str(key)] = group_id
            if group_id in seen:
                continue
            seen.add(group_id)
            keys = tuple(str(item) for item in (group.get("keys") or ()))
            visible = []
            for item in keys:
                entry = entries.get(item)
                if entry is None or bool(entry.get("floating")):
                    continue
                try:
                    requested = bool(manager._window_requested_visible(entry.get("window")))
                except Exception:
                    requested = True
                if requested:
                    visible.append(item)
            groups[group_id] = self._snapshot(
                group_id, keys, group.get("active"), visible)

        old_groups = self._groups
        changed = old_groups != groups or self._dock_to_group != dock_to_group
        if not changed:
            return False

        all_ids = set(old_groups) | set(groups)
        for group_id in sorted(all_ids):
            old = old_groups.get(group_id)
            new = groups.get(group_id)
            if old == new:
                continue
            self.groupChanged.emit(group_id, None if new is None else dict(new))
            old_active = None if old is None else old.get("activeKey")
            new_active = None if new is None else new.get("activeKey")
            if old_active != new_active:
                self.activeTabChanged.emit(group_id, new_active)
            old_order = () if old is None else tuple(old.get("keys") or ())
            new_order = () if new is None else tuple(new.get("keys") or ())
            if old_order != new_order:
                self.tabOrderChanged.emit(group_id, new_order)
            old_visible = () if old is None else tuple(old.get("visibleKeys") or ())
            new_visible = () if new is None else tuple(new.get("visibleKeys") or ())
            if old_visible != new_visible:
                self.tabVisibilityChanged.emit(group_id, new_visible)

        self._groups = groups
        self._dock_to_group = dock_to_group
        self.stateChanged.emit(self.snapshot())
        return True

    def clear(self):
        if not self._groups and not self._dock_to_group and self._drag is None:
            return False
        self._groups = {}
        self._dock_to_group = {}
        self._drag = None
        self.stateChanged.emit(self.snapshot())
        return True

    def groupIdForDock(self, key):
        return self._dock_to_group.get(str(key))

    def groupSnapshot(self, group_or_key):
        name = str(group_or_key)
        group_id = self._dock_to_group.get(name, name)
        snapshot = self._groups.get(group_id)
        return None if snapshot is None else dict(snapshot)

    def groups(self):
        return tuple(dict(self._groups[group_id]) for group_id in sorted(self._groups))

    def tabOrder(self, group_or_key):
        group = self.groupSnapshot(group_or_key)
        return () if group is None else tuple(group.get("keys") or ())

    def visibleTabs(self, group_or_key):
        group = self.groupSnapshot(group_or_key)
        return () if group is None else tuple(group.get("visibleKeys") or ())

    def activeTab(self, group_or_key):
        group = self.groupSnapshot(group_or_key)
        return None if group is None else group.get("activeKey")

    def executeCommand(self, command, **payload):
        """Execute one semantic tab command through the owning DockManager.

        Every request is represented by :class:`QDockCommand`; the historical
        dictionary signals remain available for source compatibility.
        """
        manager = self.manager()
        if manager is None:
            return False
        item = QDockCommand.coerce(command, payload, source="tab")
        item._requested()
        request = {"command": item.command()}
        request.update(item.payload())
        self.commandRequested.emit(dict(request))
        self.commandObjectRequested.emit(item)
        executor = getattr(manager, "execute_tab_command", None)
        if not callable(executor):
            executor = getattr(manager, "executeTabCommand", None)
        item._running()
        args = item.payload()
        name = item.command()
        try:
            if callable(executor):
                if bool(getattr(manager, "_qt_accepts_dock_command_object", False)):
                    result = bool(executor(item))
                else:
                    result = bool(executor(name, **args))
            elif name == "activate" and hasattr(manager, "raise_dock_widget"):
                result = bool(manager.raise_dock_widget(str(args.get("key"))))
            elif name == "move" and hasattr(manager, "reorder_dock_widget"):
                result = bool(manager.reorder_dock_widget(
                    str(args.get("key")), int(args.get("index", 0))))
            else:
                result = False
            item._finished(bool(result))
        except Exception as exc:
            item._failed(exc)
            self.commandObjectFinished.emit(item)
            raise
        self.sync()
        completed = dict(request)
        completed["accepted"] = bool(result)
        self.commandFinished.emit(completed)
        self.commandObjectFinished.emit(item)
        return bool(result)

    execute = executeCommand

    def activateTab(self, key):
        return self.executeCommand("activate", key=str(key))

    def setActiveTab(self, key):
        return self.activateTab(key)

    def moveTab(self, key, index):
        return self.executeCommand("move", key=str(key), index=int(index))

    def dockTab(self, key, target_key, zone="center", grouped=False):
        return self.executeCommand(
            "dock", key=str(key), targetKey=str(target_key),
            zone=str(zone or "center"), grouped=bool(grouped))

    def detachTab(self, key, position=None, drag_anchor=None, grouped=False, keys=None):
        payload = {
            "key": str(key),
            "position": position,
            "dragAnchor": drag_anchor,
            "grouped": bool(grouped),
        }
        if keys is not None:
            payload["keys"] = tuple(str(item) for item in keys)
        return self.executeCommand("detach", **payload)

    def cancelCommand(self):
        return self.executeCommand("cancel")

    def beginDrag(self, key, position=None, grouped=False):
        key = str(key)
        group_id = self.groupIdForDock(key)
        if group_id is None:
            return False
        if self._drag is not None and self._drag.get("key") == key:
            return False
        self._drag = {
            "key": key,
            "groupId": group_id,
            "position": position,
            "insertIndex": None,
            "outside": False,
            "grouped": bool(grouped),
        }
        self.dragStarted.emit(dict(self._drag))
        self.stateChanged.emit(self.snapshot())
        return True

    def updateDrag(self, position=None, insert_index=None, outside=None):
        if self._drag is None:
            return False
        changed = False
        if position != self._drag.get("position"):
            self._drag["position"] = position
            changed = True
        if insert_index != self._drag.get("insertIndex"):
            self._drag["insertIndex"] = insert_index
            changed = True
        if outside is not None and bool(outside) != bool(self._drag.get("outside")):
            self._drag["outside"] = bool(outside)
            changed = True
        if changed:
            self.dragUpdated.emit(dict(self._drag))
            self.stateChanged.emit(self.snapshot())
        return changed

    def endDrag(self, result="completed"):
        if self._drag is None:
            return False
        payload = dict(self._drag)
        payload["result"] = str(result or "completed")
        self._drag = None
        self.dragFinished.emit(payload)
        self.stateChanged.emit(self.snapshot())
        return True

    def cancelDrag(self):
        return self.endDrag("cancelled")

    def dragState(self):
        return None if self._drag is None else dict(self._drag)

    def snapshot(self):
        return {
            "groups": tuple(dict(self._groups[group_id]) for group_id in sorted(self._groups)),
            "dockToGroup": dict(self._dock_to_group),
            "drag": self.dragState(),
        }
