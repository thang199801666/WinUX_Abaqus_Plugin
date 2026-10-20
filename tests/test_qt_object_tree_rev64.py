from collections import deque

from DearUIQt.qt import (
    QApplication,
    QChildEvent,
    QEvent,
    QObject,
    QPointer,
    QWidget,
)


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump(self):
        while self.pending:
            callback, args = self.pending.popleft()
            callback(*args)


class TreeObserver(QObject):
    def __init__(self, *args, **kwargs):
        self.child_events = []
        super().__init__(*args, **kwargs)

    def childEvent(self, event):
        assert isinstance(event, QChildEvent)
        self.child_events.append((event.type(), event.child()))




class NamingParent(TreeObserver):
    def childEvent(self, event):
        super().childEvent(event)
        if event.added():
            event.child().setObjectName("owned-child")


class EventFilter(QObject):
    def __init__(self, *, block_type=None, **kwargs):
        super().__init__(**kwargs)
        self.block_type = block_type
        self.seen = []

    def eventFilter(self, watched, event):
        self.seen.append((watched, event.type()))
        return event.type() == self.block_type


class EventTarget(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def event(self, event):
        self.events.append(event.type())
        return super().event(event)


class Backend:
    def __init__(self):
        self.parents = {}
        self.deleted = set()

    def get_item_parent(self, tag):
        return self.parents.get(tag, 0)

    def does_item_exist(self, tag):
        return tag not in self.deleted

    def configure_item(self, _tag, **_values):
        pass

    def delete_item(self, tag):
        self.deleted.add(tag)


def test_qobject_child_events_follow_reparenting_order():
    first = TreeObserver()
    second = TreeObserver()
    child = QObject(parent=first)
    assert first.child_events == [(QEvent.ChildAdded, child)]

    child.setParent(second)
    assert first.child_events[-1] == (QEvent.ChildRemoved, child)
    assert second.child_events == [(QEvent.ChildAdded, child)]

    child.setParent(None)
    assert second.child_events[-1] == (QEvent.ChildRemoved, child)

    child.setParent(first)
    child.delete()
    assert first.child_events[-1] == (QEvent.ChildRemoved, child)
    assert child.parent is None


def test_qwidget_keeps_core_object_name_assigned_during_parent_child_event():
    backend = Backend()
    parent = NamingParent()
    child = QWidget(7, parent=parent, backend=backend)
    assert child.objectName() == "owned-child"


def test_qobject_object_name_is_core_state_and_emits_change_signal():
    obj = QObject()
    changes = []
    obj.objectNameChanged.connect(changes.append)

    assert obj.setObjectName("explorer") is True
    assert obj.objectName() == "explorer"
    assert changes == ["explorer"]
    assert obj.setObjectName("explorer") is False
    assert changes == ["explorer"]


def test_qpointer_does_not_own_target_and_nulls_after_qobject_delete():
    obj = QObject()
    guard = QPointer(obj)
    assert guard.data() is obj
    assert guard

    obj.delete()
    assert guard.data() is None
    assert guard.isNull()
    assert not guard


def test_qapplication_filter_observes_all_receiver_events_and_can_stop_delivery():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        target = EventTarget(after=scheduler.after)
        filter_object = EventFilter(after=scheduler.after, block_type=QEvent.User)
        app.installEventFilter(filter_object)

        # Wrapper-generated direct sendEvent() calls must still cross the
        # QApplication-wide filter before receiver-local dispatch.
        assert target.sendEvent(QEvent(QEvent.FocusIn)) is False
        assert target.events == [QEvent.FocusIn]
        assert filter_object.seen[-1] == (target, QEvent.FocusIn)

        assert QApplication.sendEvent(target, QEvent(QEvent.User)) is True
        assert target.events == [QEvent.FocusIn]
        assert filter_object.seen[-1] == (target, QEvent.User)
    finally:
        app.delete()


def test_qwidget_hierarchy_helpers_use_logical_qobject_tree():
    backend = Backend()
    root = QWidget(1, backend=backend)
    helper = QObject(parent=root)
    child = QWidget(2, parent=helper, backend=backend)

    assert child.parentWidget() is root
    assert child.window() is root
    assert child.topLevelWidget() is root
    assert root.isAncestorOf(child)
