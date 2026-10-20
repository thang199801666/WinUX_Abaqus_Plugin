"""Top-level Qt-style window containers over retained backend items."""
from __future__ import annotations

from ..core.object import QObject
from .widget import QWidget


class QMainWindow(QWidget):
    """Reusable QMainWindow-like shell.

    QMainWindow owns one central widget plus optional menu bar, toolbars and
    status bar. Docking remains delegated to :mod:`DearUIQt.docking`, keeping
    the core window free from application-specific layout policy.
    """

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
        super().delete()


__all__ = ["QMainWindow"]
