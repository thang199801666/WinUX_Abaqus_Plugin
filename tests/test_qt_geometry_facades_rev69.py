from DearUIQt.QtCore import QPoint, QPointF, QRect, QSize
from DearUIQt.QtGui import QAction
from DearUIQt.QtWidgets import QWidget


class Backend:
    def __init__(self):
        self.config = {1: {"pos": (0, 0), "width": 0, "height": 0, "show": True, "enabled": True}}

    def configure_item(self, tag, **values):
        self.config.setdefault(tag, {}).update(values)

    def does_item_exist(self, tag):
        return tag in self.config

    def get_item_configuration(self, tag):
        return dict(self.config[tag])

    def get_item_pos(self, tag):
        return self.config[tag].get("pos", (0, 0))

    def get_item_parent(self, tag):
        return 0

    def delete_item(self, tag):
        self.config.pop(tag, None)


def test_qt_geometry_values_are_tuple_compatible_and_expose_qt_accessors():
    point = QPoint(7, 9)
    floating = QPointF(7.5, 9.25)
    rect = QRect(point, QSize(120, 40))

    assert point == (7, 9)
    assert point[0] == 7 and point.y() == 9
    assert floating == (7.5, 9.25)
    assert floating.x() == 7.5
    assert rect == (7, 9, 120, 40)
    assert rect.topLeft() == point
    assert rect.size() == QSize(120, 40)
    assert rect.contains(QPoint(10, 10))


def test_qwidget_accepts_qt_geometry_overloads_and_returns_retained_values():
    backend = Backend()
    widget = QWidget(1, backend=backend)
    widget.move(QPoint(11, 13))
    widget.resize(QSize(200, 80))
    assert widget.pos() == QPoint(11, 13)
    assert widget.size() == QSize(200, 80)
    assert widget.geometry() == QRect(11, 13, 200, 80)
    assert widget.rect() == QRect(0, 0, 200, 80)

    widget.setGeometry(QRect(20, 25, 320, 140))
    assert backend.config[1]["pos"] == (20, 25)
    assert widget.x() == 20 and widget.y() == 25
    assert widget.width() == 320 and widget.height() == 140


def test_qt_style_facades_resolve_to_the_existing_wrapper_types():
    from DearUIQt.qt import QPoint as LegacyPoint, QWidget as LegacyWidget
    from DearUIQt.qt.action import QAction as LegacyAction

    assert QPoint is LegacyPoint
    assert QWidget is LegacyWidget
    assert QAction is LegacyAction
