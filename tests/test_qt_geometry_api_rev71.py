from collections import deque

from DearUIQt.QtCore import QCoreApplication, QPoint, QPointF, QRect, QSize
from DearUIQt.QtWidgets import QApplication, QWidget


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class Backend:
    def __init__(self):
        self.config = {1: {"width": 10, "height": 20}}
        self.state = {1: {}}

    def configure_item(self, tag, **values):
        self.config.setdefault(tag, {}).update(values)

    def does_item_exist(self, tag):
        return tag in self.config

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def get_item_parent(self, tag):
        return 0

    def get_item_state(self, tag):
        return dict(self.state.get(tag, {}))

    def get_item_pos(self, tag):
        return self.config.get(tag, {}).get("pos", (0, 0))

    def focus_item(self, tag):
        self.state.setdefault(tag, {})["focused"] = True

    def delete_item(self, tag):
        self.config.pop(tag, None)


def test_qpoint_qpointf_and_qsize_mutators_match_qt_shape():
    point = QPoint(2, -3)
    point.setX(5)
    point.setY(-7)
    assert point == (5, -7)
    assert point.manhattanLength() == 12

    float_point = QPointF(1.5, -2.0)
    float_point.setX(2.5)
    float_point.setY(-3.5)
    assert float_point == (2.5, -3.5)
    assert float_point.manhattanLength() == 6.0

    size = QSize(10, 20)
    size.setWidth(12)
    size.setHeight(18)
    assert size == (12, 18)
    assert size + QSize(3, 2) == QSize(15, 20)
    assert size - (2, 3) == QSize(10, 15)


def test_qrect_supports_qt_style_move_intersection_and_union():
    rect = QRect(10, 20, 8, 6)
    assert rect.topRight() == QPoint(17, 20)
    assert rect.bottomLeft() == QPoint(10, 25)
    assert rect.center() == QPoint(14, 23)

    rect.moveCenter(QPoint(50, 60))
    assert rect.center() == QPoint(50, 60)
    rect.moveRight(100)
    assert rect.right() == 100
    rect.moveBottom(200)
    assert rect.bottom() == 200

    a = QRect(0, 0, 10, 10)
    b = QRect(5, 5, 10, 10)
    assert a.intersects(b)
    assert a.intersected(b) == QRect(5, 5, 5, 5)
    assert a.united(b) == QRect(0, 0, 15, 15)

    moved = QRect(a)
    moved.translate(3, 4)
    assert moved == QRect(3, 4, 10, 10)
    assert a.translated(QPoint(3, 4)) == moved


def test_qcoreapplication_facade_reuses_qapplication_singleton():
    scheduler = Scheduler()
    app = QCoreApplication(after=scheduler.after)
    try:
        assert isinstance(app, QApplication)
        assert QCoreApplication.instance() is app
        assert QApplication.instance() is app
    finally:
        app.delete()


def test_qwidget_min_max_accessors_and_clear_focus_use_retained_application_state():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        widget = QWidget(1, backend=backend, after=scheduler.after)
        widget.setMinimumSize(11, 12)
        widget.setMaximumSize(101, 102)
        assert widget.minimumWidth() == 11
        assert widget.minimumHeight() == 12
        assert widget.maximumWidth() == 101
        assert widget.maximumHeight() == 102
        assert widget.setFocus() is True
        assert widget.hasFocus() is True
        assert widget.clearFocus() is True
        assert app.focusWidget() is None
    finally:
        app.delete()
