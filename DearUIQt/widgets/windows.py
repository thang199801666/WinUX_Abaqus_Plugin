"""Top-level Qt-style window containers over retained backend items."""
from __future__ import annotations

from ..core.object import QObject, Qt, Signal
from .widget import QWidget


class QMainWindow(QWidget):
    """Reusable QMainWindow-like shell.

    QMainWindow owns one central widget plus optional menu bar, toolbars and
    status bar.  A :class:`~DearUIQt.docking.DockManager` is created lazily the
    first time a Qt docking API is used, so existing windows that manage their
    own layout pay no docking cost and keep their historical geometry.
    """

    NoDockWidgetArea = Qt.NoDockWidgetArea
    LeftDockWidgetArea = Qt.LeftDockWidgetArea
    RightDockWidgetArea = Qt.RightDockWidgetArea
    TopDockWidgetArea = Qt.TopDockWidgetArea
    BottomDockWidgetArea = Qt.BottomDockWidgetArea
    AllDockWidgetAreas = Qt.AllDockWidgetAreas

    # QMainWindow::DockOption values mirror DockManager without importing the
    # renderer-backed docking module at class-import time.
    AnimatedDocks = 0x01
    AllowNestedDocks = 0x02
    AllowTabbedDocks = 0x04
    ForceTabbedDocks = 0x08
    VerticalTabs = 0x10
    GroupedDragging = 0x20

    def __init__(self, title="", *, width=960, height=640, parent=None,
                 after=None, backend=None, tag=None, no_scrollbar=False,
                 no_scroll_with_mouse=False, no_collapse=False):
        backend, options = self._construction(parent, backend)
        if options:
            raise ValueError("QMainWindow must be a top-level window")
        kwargs = {
            "label": str(title or ""),
            "width": int(width),
            "height": int(height),
            "no_collapse": bool(no_collapse),
        }
        if tag is not None:
            kwargs["tag"] = tag
        if no_scrollbar:
            kwargs["no_scrollbar"] = True
        if no_scroll_with_mouse:
            kwargs["no_scroll_with_mouse"] = True
        native = backend.add_window(**kwargs)
        super().__init__(native, parent=None, after=after, backend=backend)
        self._window_title = str(title or "")
        self._central_widget = None
        self._menu_bar = None
        self._status_bar = None
        self._tool_bars = []
        self._container_stack_depth = 0
        self._dock_manager = None
        self._dock_manager_options = {}
        self._dock_keys = {}
        self._dock_topology_connections = {}
        self.dockTopologyChanged = Signal()
        self.dockTabGroupChanged = Signal()
        self.dockActiveTabChanged = Signal()
        self.dockTabOrderChanged = Signal()
        self.dockTabVisibilityChanged = Signal()
        self.dockTabDragStarted = Signal()
        self.dockTabDragFinished = Signal()
        self._dock_tab_group_connections = []
        from ..docking.main_window_commands import QMainWindowDockCommandBus
        from ..docking.history import QDockCommandHistory
        self._dock_command_history = QDockCommandHistory(
            self._capture_dock_history_checkpoint,
            self._restore_dock_history_checkpoint,
            parent=self)
        from ..gui.undo import QUndoStack
        self._dock_undo_stack = QUndoStack(self._dock_command_history, parent=self)
        self._dock_command_bus = QMainWindowDockCommandBus(self._execute_dock_command, parent=self)
        self._dock_command_bus.setHistory(self._dock_command_history)
        self.dockCommandRequested = self._dock_command_bus.commandRequested
        self.dockCommandStarted = self._dock_command_bus.commandStarted
        self.dockCommandFinished = self._dock_command_bus.commandFinished
        self.dockCommandFailed = self._dock_command_bus.commandFailed

    def __enter__(self):
        """Temporarily make this window the native construction parent.

        This mirrors renderer context-manager construction while keeping the
        stack operation inside DearUIQt.  New code should still prefer explicit
        QObject parents when practical.
        """
        push = getattr(self.backend, "push_container_stack", None)
        if callable(push):
            push(self.tag)
            self._container_stack_depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._container_stack_depth > 0:
            pop = getattr(self.backend, "pop_container_stack", None)
            if callable(pop):
                pop()
            self._container_stack_depth -= 1
        return False

    def windowTitle(self):
        return self._window_title

    def setWindowTitle(self, title):
        self._window_title = str(title or "")
        self._configure("label", self._window_title)

    # ------------------------------------------------------------- central widget
    def setCentralWidget(self, widget):
        self._require_ui()
        if not isinstance(widget, QWidget):
            raise TypeError("central widget must be QWidget")
        if widget._deleted:
            raise RuntimeError("cannot install a deleted central widget")
        if widget.backend is not self.backend:
            raise ValueError("main window and central widget must use the same backend")
        if self._central_widget is widget:
            return widget
        old = self.centralWidget()
        if old is not None and old is not widget:
            self._central_widget = None
            old.delete()
        self._adopt_native_widget(widget)
        widget.setVisible(True)
        self._central_widget = widget
        return widget

    def centralWidget(self):
        widget = self._central_widget
        if widget is not None and widget._deleted:
            self._central_widget = None
            return None
        return widget

    def takeCentralWidget(self):
        self._require_ui()
        widget = self.centralWidget()
        if widget is None:
            return None
        self._park_widget(widget)
        self._central_widget = None
        return widget

    # ------------------------------------------------------------- chrome ownership
    def setMenuBar(self, menu_bar):
        self._require_ui()
        if menu_bar is None:
            return self.takeMenuBar()
        from .menu_bar import QMenuBar
        if not isinstance(menu_bar, QMenuBar):
            raise TypeError("menu bar must be QMenuBar")
        if menu_bar.backend is not self.backend:
            raise ValueError("main window and menu bar must use the same backend")
        old = self._menu_bar
        if old is menu_bar:
            return menu_bar
        if old is not None:
            old.delete()
        self.backend.move_item(menu_bar.tag, parent=self.tag)
        if isinstance(menu_bar, QObject) and menu_bar.parent is not self:
            menu_bar.setParent(self)
        self._menu_bar = menu_bar
        return menu_bar

    def menuBar(self):
        menu = self._menu_bar
        if menu is not None and getattr(menu, "_deleted", False):
            self._menu_bar = None
            return None
        return menu

    def takeMenuBar(self):
        menu = self.menuBar()
        if menu is None:
            return None
        self._park_object_item(menu)
        self._menu_bar = None
        return menu

    def setStatusBar(self, status_bar):
        self._require_ui()
        if status_bar is None:
            old = self._status_bar
            self._status_bar = None
            if old is not None:
                old.delete()
            return None
        from .tool_bar import QStatusBar
        if not isinstance(status_bar, QStatusBar):
            raise TypeError("status bar must be QStatusBar")
        if status_bar.backend is not self.backend:
            raise ValueError("main window and status bar must use the same backend")
        old = self._status_bar
        if old is not None and old is not status_bar:
            old.delete()
        self._adopt_native_widget(status_bar)
        self._status_bar = status_bar
        return status_bar

    def statusBar(self):
        status = self._status_bar
        if status is not None and status._deleted:
            self._status_bar = None
            status = None
        if status is None:
            from .tool_bar import QStatusBar
            status = QStatusBar(parent=self, after=self._after, backend=self.backend)
            self._status_bar = status
        return status

    def addToolBar(self, area_or_toolbar, toolbar=None):
        self._require_ui()
        # Qt overload: addToolBar(toolbar) or addToolBar(area, toolbar). DearUIQt
        # retains area as policy metadata; vertical area layout can be layered on
        # by a host without changing toolbar ownership.
        if toolbar is None:
            area, toolbar = None, area_or_toolbar
        else:
            area = area_or_toolbar
        from .tool_bar import QToolBar
        if isinstance(toolbar, str):
            toolbar = QToolBar(toolbar, parent=self, after=self._after, backend=self.backend)
        if not isinstance(toolbar, QToolBar):
            raise TypeError("toolbar must be QToolBar or title text")
        if toolbar.backend is not self.backend:
            raise ValueError("main window and toolbar must use the same backend")
        if toolbar not in self._tool_bars:
            self._adopt_native_widget(toolbar)
            toolbar.setProperty("toolBarArea", area)
            self._tool_bars.append(toolbar)
        return toolbar

    def insertToolBar(self, before, toolbar):
        self.addToolBar(toolbar)
        if before not in self._tool_bars or before is toolbar:
            return toolbar
        self._tool_bars.remove(toolbar)
        self._tool_bars.insert(self._tool_bars.index(before), toolbar)
        try:
            self.backend.move_item(toolbar.tag, before=before.tag, parent=self.tag)
        except Exception:
            pass
        return toolbar

    def removeToolBar(self, toolbar):
        if toolbar not in self._tool_bars:
            return False
        self._tool_bars.remove(toolbar)
        self._park_widget(toolbar)
        return True

    def toolBars(self):
        self._tool_bars[:] = [bar for bar in self._tool_bars if not bar._deleted]
        return tuple(self._tool_bars)

    # ------------------------------------------------------------- docking facade
    @staticmethod
    def _dock_area_name(area):
        """Return DockManager's area name for a Qt dock-area value."""
        if isinstance(area, str):
            value = area.strip().lower()
            aliases = {
                "leftdockwidgetarea": "left", "left": "left",
                "rightdockwidgetarea": "right", "right": "right",
                "topdockwidgetarea": "top", "top": "top",
                "bottomdockwidgetarea": "bottom", "bottom": "bottom",
            }
            if value in aliases:
                return aliases[value]
            raise ValueError("unsupported dock widget area: {!r}".format(area))
        value = int(area)
        mapping = {
            Qt.LeftDockWidgetArea: "left",
            Qt.RightDockWidgetArea: "right",
            Qt.TopDockWidgetArea: "top",
            Qt.BottomDockWidgetArea: "bottom",
        }
        try:
            return mapping[value]
        except KeyError:
            raise ValueError("unsupported dock widget area: {!r}".format(area))

    @staticmethod
    def _dock_area_flag(area):
        if area is None:
            return Qt.NoDockWidgetArea
        value = str(area).strip().lower()
        return {
            "left": Qt.LeftDockWidgetArea,
            "right": Qt.RightDockWidgetArea,
            "top": Qt.TopDockWidgetArea,
            "bottom": Qt.BottomDockWidgetArea,
        }.get(value, Qt.NoDockWidgetArea)

    def _ensure_dock_manager(self, **options):
        manager = self._dock_manager
        if manager is not None:
            if options:
                raise RuntimeError(
                    "QMainWindow DockManager is already initialized; "
                    "host/options can only be supplied on first access")
            return manager
        from ..docking import DockManager
        config = dict(self._dock_manager_options)
        config.update(options)
        parent = config.pop("parent", self.tag)
        manager = DockManager(parent, **config)
        self._dock_manager = manager
        self._dock_manager_options = {}
        controller = manager.tabGroupController()
        self._dock_tab_group_connections = [
            controller.groupChanged.connect(self.dockTabGroupChanged.emit),
            controller.activeTabChanged.connect(self.dockActiveTabChanged.emit),
            controller.tabOrderChanged.connect(self.dockTabOrderChanged.emit),
            controller.tabVisibilityChanged.connect(self.dockTabVisibilityChanged.emit),
            controller.dragStarted.connect(self.dockTabDragStarted.emit),
            controller.dragFinished.connect(self.dockTabDragFinished.emit),
        ]
        return manager

    def configureDockManager(self, **options):
        """Configure the lazy dock host before its first use.

        This is a DearUIQt extension for retained applications that already own
        a central-workspace subregion.  The public docking operations remain
        QMainWindow-compatible; only the native host tag/callback wiring is
        supplied here before the manager is materialized.
        """
        self._require_ui()
        if self._dock_manager is not None:
            raise RuntimeError("QMainWindow DockManager is already initialized")
        self._dock_manager_options = dict(options)
        return self

    def dockManager(self, **options):
        """Return the lazy DockManager backing the QMainWindow dock facade.

        Optional arguments are a DearUIQt compatibility extension and are only
        accepted on first access.  Prefer :meth:`configureDockManager` when the
        host needs a retained subregion instead of the whole main window.
        """
        return self._ensure_dock_manager(**options)

    def dockTabGroupController(self):
        """Return the retained QTabBar-like controller for dock groups."""
        return self._ensure_dock_manager().tabGroupController()

    @staticmethod
    def _dock_identity(dock):
        getter = getattr(dock, "objectName", None)
        if callable(getter):
            try:
                name = str(getter() or "")
                if name:
                    return name
            except Exception:
                pass
        tag = str(getattr(dock, "tag", "") or "")
        if tag:
            return tag
        return "dock-{}".format(id(dock))

    @staticmethod
    def _dock_state_controller(dock):
        getter = getattr(dock, "stateController", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _connect_dock_topology_signal(self, dock, controller):
        dock_id = id(dock)
        connections = getattr(self, "_dock_topology_connections", None)
        if connections is None:
            connections = {}
            self._dock_topology_connections = connections
        if dock_id in connections:
            return
        signal = getattr(controller, "topologyChanged", None)
        if signal is None:
            return
        connection = signal.connect(
            lambda snapshot, dock=dock: self.dockTopologyChanged.emit(dock, snapshot))
        connections[dock_id] = connection

    def _disconnect_dock_topology_signal(self, dock):
        connections = getattr(self, "_dock_topology_connections", {})
        connection = connections.pop(id(dock), None)
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

    def _attach_dock_controller(self, dock, area=None):
        controller = self._dock_state_controller(dock)
        if controller is None:
            setter = getattr(dock, "set_dock_area", None)
            if area is not None and callable(setter):
                try:
                    setter(area)
                except Exception:
                    pass
            return False
        self._connect_dock_topology_signal(dock, controller)
        attach = getattr(controller, "attachToMainWindow", None)
        if callable(attach):
            return bool(attach(self, area))
        return False

    def _detach_dock_controller(self, dock):
        self._disconnect_dock_topology_signal(dock)
        controller = self._dock_state_controller(dock)
        if controller is None:
            return False
        clear = getattr(controller, "clearTopology", None)
        if callable(clear):
            try:
                clear()
            except Exception:
                pass
        detach = getattr(controller, "detachFromMainWindow", None)
        if callable(detach):
            return bool(detach(self))
        return False

    def _sync_dock_controller_from_manager(self, dock, key=None):
        manager = self._dock_manager
        if manager is None:
            return False
        if key is None:
            key = self._dock_keys.get(id(dock))
        if key is None:
            resolver = getattr(manager, "_resolve_key", None)
            if callable(resolver):
                try:
                    key = resolver(dock)
                except Exception:
                    key = None
        if key is None:
            return False
        area = None
        getter = getattr(manager, "dockWidgetArea", None)
        if callable(getter):
            try:
                area = getter(key)
            except Exception:
                area = None
        self._attach_dock_controller(dock, area)
        controller = self._dock_state_controller(dock)
        entry = getattr(manager, "_entries", {}).get(str(key), {})
        if controller is not None and "floating" in entry:
            adopter = getattr(controller, "adoptFloating", None)
            if callable(adopter):
                try:
                    adopter(bool(entry.get("floating")))
                except Exception:
                    pass
            topology_adopter = getattr(controller, "adoptTopology", None)
            topology_getter = getattr(manager, "dockTopology", None)
            if callable(topology_adopter) and callable(topology_getter):
                try:
                    topology_adopter(topology_getter(key))
                except Exception:
                    pass
        return True

    def _ensure_dock_command_bus(self):
        bus = getattr(self, "_dock_command_bus", None)
        if bus is not None:
            return bus
        from ..docking.main_window_commands import QMainWindowDockCommandBus
        try:
            bus = QMainWindowDockCommandBus(self._execute_dock_command, parent=self)
        except Exception:
            # Lightweight unit/embedder facades may construct QMainWindow via
            # __new__ without QObject initialization. Keep command semantics
            # available without pretending such a facade owns a QObject child.
            bus = QMainWindowDockCommandBus(self._execute_dock_command)
        self._dock_command_bus = bus
        history = getattr(self, "_dock_command_history", None)
        if history is not None:
            bus.setHistory(history)
        self.dockCommandRequested = bus.commandRequested
        self.dockCommandStarted = bus.commandStarted
        self.dockCommandFinished = bus.commandFinished
        self.dockCommandFailed = bus.commandFailed
        return bus

    def dockCommandBus(self):
        """Return the semantic command bus for QMainWindow dock mutations."""
        return self._ensure_dock_command_bus()

    def executeDockCommand(self, command, **payload):
        """Execute one semantic dock command through the shared command bus."""
        self._require_ui()
        return self._ensure_dock_command_bus().execute(command, **payload)

    execute_dock_command = executeDockCommand

    def _ensure_dock_command_history(self):
        history = getattr(self, "_dock_command_history", None)
        if history is not None:
            return history
        from ..docking.history import QDockCommandHistory
        try:
            history = QDockCommandHistory(
                self._capture_dock_history_checkpoint,
                self._restore_dock_history_checkpoint, parent=self)
        except Exception:
            history = QDockCommandHistory(
                self._capture_dock_history_checkpoint,
                self._restore_dock_history_checkpoint)
        self._dock_command_history = history
        bus = getattr(self, "_dock_command_bus", None)
        if bus is not None:
            bus.setHistory(history)
        stack = getattr(self, "_dock_undo_stack", None)
        if stack is not None:
            setter = getattr(stack, "setHistory", None)
            if callable(setter):
                setter(history)
        return history

    def dockCommandHistory(self):
        return self._ensure_dock_command_history()

    def _ensure_dock_undo_stack(self):
        stack = getattr(self, "_dock_undo_stack", None)
        if stack is not None:
            return stack
        from ..gui.undo import QUndoStack
        history = self._ensure_dock_command_history()
        try:
            stack = QUndoStack(history, parent=self)
        except Exception:
            stack = QUndoStack(history)
        self._dock_undo_stack = stack
        return stack

    def dockUndoStack(self):
        return self._ensure_dock_undo_stack()

    def createDockUndoAction(self, parent=None, prefix="Undo"):
        return self._ensure_dock_undo_stack().createUndoAction(
            self if parent is None else parent, prefix)

    def createDockRedoAction(self, parent=None, prefix="Redo"):
        return self._ensure_dock_undo_stack().createRedoAction(
            self if parent is None else parent, prefix)

    def canUndoDockCommand(self):
        return self._ensure_dock_command_history().canUndo()

    def canRedoDockCommand(self):
        return self._ensure_dock_command_history().canRedo()

    def undoDockCommand(self):
        self._require_ui()
        return self._ensure_dock_command_history().undo()

    def redoDockCommand(self):
        self._require_ui()
        return self._ensure_dock_command_history().redo()

    def clearDockCommandHistory(self):
        return self._ensure_dock_command_history().clear()

    def _capture_dock_history_checkpoint(self):
        manager = getattr(self, "_dock_manager", None)
        registry = []
        if manager is not None:
            for key, entry in tuple(getattr(manager, "_entries", {}).items()):
                registry.append((
                    str(key),
                    entry.get("window"),
                    entry.get("title"),
                    entry.get("area"),
                ))
        return {
            "state": self.saveState(),
            "registry": tuple(registry),
        }

    def _restore_dock_history_checkpoint(self, checkpoint):
        checkpoint = dict(checkpoint or {})
        desired = tuple(checkpoint.get("registry") or ())
        desired_by_key = {str(item[0]): item for item in desired if item}
        manager = self._ensure_dock_manager()
        if not hasattr(self, "_dock_keys"):
            self._dock_keys = {}

        # Remove runtime registrations that did not exist at the checkpoint.
        for key, entry in tuple(getattr(manager, "_entries", {}).items()):
            if str(key) in desired_by_key:
                continue
            window = entry.get("window")
            manager.removeDockWidget(key)
            if window is not None:
                self._dock_keys.pop(id(window), None)
                self._detach_dock_controller(window)

        # Re-register exact live QDockWidget objects before restoring the tree.
        for key, window, title, area in desired:
            key = str(key)
            entry = getattr(manager, "_entries", {}).get(key)
            if entry is None or entry.get("window") is not window:
                if entry is not None:
                    manager.removeDockWidget(key)
                result = manager.addDockWidget(
                    key, window, title=title, area=area, activate=False)
                if result is False:
                    return False
                key = str(result)
            if window is not None:
                self._dock_keys[id(window)] = key

        restored = bool(manager.restoreState(checkpoint.get("state") or {}, 0))
        if not restored:
            return False
        for key, window, _title, _area in desired:
            if window is None:
                continue
            resolved = self._dock_keys.get(id(window), str(key))
            self._sync_dock_controller_from_manager(window, resolved)
        return True

    def _execute_dock_command(self, command, payload):
        command = str(command or "").strip().lower()
        if command == "add":
            return self._addDockWidget_impl(payload.get("area"), payload.get("dockWidget"), payload.get("orientation"))
        if command == "remove":
            return self._removeDockWidget_impl(payload.get("dockWidget"))
        if command == "restore":
            if "state" in payload:
                return self._restoreState_impl(payload.get("state"), payload.get("version", 0))
            return self._restoreDockWidget_impl(payload.get("dockWidget"))
        if command == "tabify":
            return self._tabifyDockWidget_impl(payload.get("first"), payload.get("second"))
        if command == "split":
            return self._splitDockWidget_impl(payload.get("first"), payload.get("second"), payload.get("orientation"))
        if command in ("float", "dock"):
            dock = payload.get("dockWidget")
            if dock is None:
                raise ValueError("dockWidget is required for {} command".format(command))
            setter = getattr(dock, "setFloating", None)
            if not callable(setter):
                raise TypeError("dockWidget does not support setFloating()")
            setter(command == "float")
            return True
        raise ValueError("unknown QMainWindow dock command: {}".format(command))

    def addDockWidget(self, area, dock_widget, orientation=None):
        return self.executeDockCommand("add", area=area, dockWidget=dock_widget, orientation=orientation)

    def removeDockWidget(self, dock_widget):
        return self.executeDockCommand("remove", dockWidget=dock_widget)

    def restoreDockWidget(self, dock_widget):
        return self.executeDockCommand("restore", dockWidget=dock_widget)

    def tabifyDockWidget(self, first, second):
        return self.executeDockCommand("tabify", first=first, second=second)

    def splitDockWidget(self, first, second, orientation):
        return self.executeDockCommand("split", first=first, second=second, orientation=orientation)

    def setDockWidgetFloating(self, dock_widget, floating=True):
        return self.executeDockCommand("float" if floating else "dock", dockWidget=dock_widget)

    def _addDockWidget_impl(self, area, dock_widget, orientation=None):
        """Add *dock_widget* using QMainWindow-compatible spelling.

        ``orientation`` is accepted for Qt source compatibility.  Nested split
        placement remains explicit through :meth:`splitDockWidget`, matching
        DockManager's retained-mode topology model.
        """
        self._require_ui()
        from ..docking import QDockWidget
        if not isinstance(dock_widget, QDockWidget):
            raise TypeError("dock widget must be QDockWidget")
        area_name = self._dock_area_name(area)
        key = self._dock_identity(dock_widget)
        manager = self._ensure_dock_manager()
        result = manager.addDockWidget(
            key, dock_widget, title=getattr(dock_widget, "title", key),
            area=area_name, activate=True)
        if result is False:
            return False
        self._dock_keys[id(dock_widget)] = str(result)
        self._sync_dock_controller_from_manager(dock_widget, str(result))
        return None

    def _removeDockWidget_impl(self, dock_widget):
        manager = self._dock_manager
        if manager is None:
            return None
        key = self._dock_keys.pop(id(dock_widget), None)
        if key is None:
            key = manager._resolve_key(dock_widget)
        if key is not None:
            manager.removeDockWidget(key)
        self._detach_dock_controller(dock_widget)
        return None

    def dockWidgetArea(self, dock_widget):
        manager = self._dock_manager
        if manager is None:
            return Qt.NoDockWidgetArea
        key = self._dock_keys.get(id(dock_widget))
        if key is None:
            key = manager._resolve_key(dock_widget)
        if key is None:
            return Qt.NoDockWidgetArea
        return self._dock_area_flag(manager.dockWidgetArea(key))

    def _restoreDockWidget_impl(self, dock_widget):
        manager = self._ensure_dock_manager()
        key = self._dock_keys.get(id(dock_widget)) or self._dock_identity(dock_widget)
        # Late-created docks must be registered before restoreDockWidget can
        # replace persisted objectName placeholders in the layout tree.
        if manager._resolve_key(dock_widget) is None:
            area = getattr(dock_widget, "dock_area", "right")
            result = manager.addDockWidget(
                key, dock_widget, title=getattr(dock_widget, "title", key),
                area=area, activate=False)
            if result is False:
                return False
            key = str(result)
            self._dock_keys[id(dock_widget)] = key
        restored = bool(manager.restoreDockWidget(key))
        if restored:
            self._sync_dock_controller_from_manager(dock_widget, key)
        return restored

    def _tabifyDockWidget_impl(self, first, second):
        manager = self._ensure_dock_manager()
        result = bool(manager.tabifyDockWidget(first, second))
        if result:
            self._sync_dock_controller_from_manager(first)
            self._sync_dock_controller_from_manager(second)
        return result

    def tabifiedDockWidgets(self, dock_widget):
        manager = self._dock_manager
        if manager is None:
            return []
        keys = manager.tabifiedDockWidgets(dock_widget)
        result = []
        for key in keys:
            entry = manager._entries.get(str(key))
            if entry is not None:
                window = entry.get("window")
                if window is not None:
                    result.append(window)
        return result

    def _splitDockWidget_impl(self, first, second, orientation):
        manager = self._ensure_dock_manager()
        result = bool(manager.splitDockWidget(first, second, orientation))
        if result:
            self._sync_dock_controller_from_manager(first)
            self._sync_dock_controller_from_manager(second)
        return result

    def resizeDocks(self, docks, sizes, orientation):
        manager = self._ensure_dock_manager()
        return bool(manager.resizeDocks(docks, sizes, orientation))

    def setDockOptions(self, options):
        return self._ensure_dock_manager().setDockOptions(options)

    def dockOptions(self):
        return self._ensure_dock_manager().dockOptions()

    def setDockNestingEnabled(self, enabled):
        return self._ensure_dock_manager().setDockNestingEnabled(enabled)

    def isDockNestingEnabled(self):
        return self._ensure_dock_manager().isDockNestingEnabled()

    def setAnimated(self, enabled):
        return self._ensure_dock_manager().setAnimated(enabled)

    def isAnimated(self):
        return self._ensure_dock_manager().isAnimated()

    def setDocumentMode(self, enabled):
        return self._ensure_dock_manager().setDocumentMode(enabled)

    def documentMode(self):
        return self._ensure_dock_manager().documentMode()

    def setTabPosition(self, areas, tab_position):
        return self._ensure_dock_manager().setTabPosition(areas, tab_position)

    def tabPosition(self, area):
        return self._ensure_dock_manager().tabPosition(area)

    def saveState(self, version=0):
        """Serialize QMainWindow dock topology by QDockWidget.objectName()."""
        manager = self._dock_manager
        if manager is None:
            return {"format": 3, "version": int(version), "docks": [], "order": []}
        return manager.saveState(version)

    def restoreState(self, state, version=0):
        return self.executeDockCommand("restore", state=state, version=version)

    def _restoreState_impl(self, state, version=0):
        """Restore dock topology and adopt it into registered dock controllers."""
        manager = self._ensure_dock_manager()
        restored = bool(manager.restoreState(state, version))
        if restored:
            for dock_id, key in tuple(self._dock_keys.items()):
                entry = getattr(manager, "_entries", {}).get(str(key))
                if entry is None:
                    continue
                dock = entry.get("window")
                if dock is not None:
                    self._sync_dock_controller_from_manager(dock, key)
        return restored

    def layoutDocks(self, width=None, height=None, force=False):
        """Lay out the current dock topology inside the main-window client area.

        This explicit hook keeps M4f source-compatible with existing WinUx
        layouts; a later migration can call it from resizeEvent once every
        QMainWindow user has moved to the canonical dock layout.
        """
        manager = self._dock_manager
        if manager is None:
            return False
        if width is None:
            width = self.width()
        if height is None:
            height = self.height()
        manager.layout(width, height, force=force)
        return True

    # ------------------------------------------------------------- native adoption
    def _adopt_native_widget(self, widget):
        parking = getattr(widget, "_qt_detached_host", None)
        parking_connection = getattr(widget, "_qt_detached_host_connection", None)
        self.backend.move_item(widget._layout_tag(), parent=self.tag)
        if parking_connection is not None:
            parking_connection.disconnect()
        if parking is not None and self.backend.does_item_exist(parking):
            self.backend.delete_item(parking)
        for name in ("_qt_detached_host", "_qt_detached_host_connection"):
            if hasattr(widget, name):
                delattr(widget, name)
        widget.setParent(self)
        return widget

    def _park_widget(self, widget):
        parking = self.backend.add_window(
            label="", width=1, height=1, show=False, no_saved_settings=True,
            no_title_bar=True, no_move=True, no_resize=True,
        )
        self.backend.move_item(widget._layout_tag(), parent=parking)
        widget.setParent(None)

        def cleanup(_object=None, _parking=parking, _backend=self.backend):
            try:
                if _backend.does_item_exist(_parking):
                    _backend.delete_item(_parking)
            except Exception:
                pass

        widget._qt_detached_host = parking
        widget._qt_detached_host_connection = widget.destroyed.connect(cleanup)
        return widget

    def _park_object_item(self, obj):
        parking = self.backend.add_window(
            label="", width=1, height=1, show=False, no_saved_settings=True,
            no_title_bar=True, no_move=True, no_resize=True,
        )
        self.backend.move_item(obj.tag, parent=parking)
        obj.setParent(None)
        obj._qt_detached_host = parking
        obj.destroyed.connect(lambda *_: self.backend.delete_item(parking)
                              if self.backend.does_item_exist(parking) else None)
        return obj

    def delete(self):
        if self._deleted:
            return
        # QObject ownership disposes chrome; clear retained references first so
        # subclass callbacks cannot observe stale objects during deletion.
        self._central_widget = None
        self._menu_bar = None
        self._status_bar = None
        self._tool_bars = []
        manager = self._dock_manager
        self._dock_manager = None
        self._dock_keys.clear()
        if manager is not None:
            try:
                manager.close()
            except Exception:
                pass
        super().delete()


__all__ = ["QMainWindow"]
