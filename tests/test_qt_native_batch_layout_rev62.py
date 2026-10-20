from pathlib import Path
from unittest.mock import Mock

from DearUIQt.qt import QMargins, QSize, QSizePolicy, Qt, QWidget, QVBoxLayout, QGridLayout
from DearUIQt.qt.core import QObject

ROOT = Path(__file__).resolve().parents[1]


def _backend():
    backend = Mock()
    backend.add_group.side_effect = iter(range(100, 500))
    backend.add_child_window.side_effect = iter(range(500, 700))
    backend.add_window.side_effect = iter(range(700, 900))
    backend.add_table.return_value = 900
    backend.add_table_column.return_value = 901
    backend.add_table_row.side_effect = iter(range(910, 980))
    backend.get_item_parent.return_value = 999
    backend.does_item_exist.return_value = True
    backend.mvTable_SizingStretchProp = 1
    return backend


class ConstructionOwner(QObject):
    def __init__(self):
        super().__init__()
        self.pending = {}

    def isConstructing(self):
        return True

    def _queue_construction_widget_config(self, widget, values):
        self.pending.setdefault(widget, {}).update(values)
        return True


def test_qwidget_batches_native_config_during_hidden_construction():
    backend = _backend()
    owner = ConstructionOwner()
    widget = QWidget(1, parent=owner, backend=backend)

    widget.setFixedWidth(100)
    widget.setFixedHeight(30)
    widget.move(7, 9)

    # Retained state is immediately correct, but no native mutation is paid yet.
    assert widget.width() == 100
    assert widget.height() == 30
    backend.configure_item.assert_not_called()
    assert owner.pending[widget] == {"width": 100, "height": 30, "pos": (7, 9)}


def test_qdialog_first_show_flushes_native_widget_batch_before_polish():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    finish = source[source.index("    def _finish_initial_construction"):
                    source.index("    def _configure_layout_item")]
    assert "self._flush_construction_widget_configs()" in finish
    assert finish.index("self._flush_construction_widget_configs()") < finish.index("QEvent(QEvent.Polish)")
    flush = source[source.index("    def _flush_construction_widget_configs"):
                   source.index("    def _finish_initial_construction")]
    assert "widget.backend.configure_item(widget.tag, **values)" in flush


def test_box_layout_contents_margins_participate_in_size_hint():
    backend = _backend()
    owner = QWidget(1, backend=backend)
    layout = QVBoxLayout(parent=owner, backend=backend, spacing=5)
    owner.setLayout(layout)
    first = QWidget(2, backend=backend)
    second = QWidget(3, backend=backend)
    first.setFixedSize(80, 20)
    second.setFixedSize(100, 30)
    layout.addWidget(first)
    layout.addWidget(second)
    layout.setContentsMargins(QMargins(2, 3, 4, 5))

    assert layout.contentsMargins() == QMargins(2, 3, 4, 5)
    assert layout.sizeHint() == QSize(106, 63)


def test_box_layout_reports_expansion_from_policy_and_stretch():
    backend = _backend()
    owner = QWidget(1, backend=backend)
    layout = QVBoxLayout(parent=owner, backend=backend)
    child = QWidget(2, backend=backend)
    layout.addWidget(child)

    child.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
    assert layout.expandingDirections() & Qt.Vertical
    policy = child.sizePolicy()
    policy.setVerticalPolicy(QSizePolicy.Preferred)
    child.setSizePolicy(policy)
    layout.setStretch(0, 2)
    assert layout.expandingDirections() & Qt.Vertical


def test_grid_layout_margins_and_spacing_are_retained_in_hints():
    backend = _backend()
    owner = QWidget(1, backend=backend)
    grid = QGridLayout(columns=2, parent=owner, backend=backend)
    owner.setLayout(grid)
    left = QWidget(2, backend=backend)
    right = QWidget(3, backend=backend)
    left.setFixedSize(40, 20)
    right.setFixedSize(60, 30)
    grid.addWidget(left, 0, 0)
    grid.addWidget(right, 0, 1)
    grid.setContentsMargins(1, 2, 3, 4)
    grid.setHorizontalSpacing(7)
    grid.setVerticalSpacing(5)

    assert grid.contentsMargins() == QMargins(1, 2, 3, 4)
    assert grid.horizontalSpacing() == 7
    assert grid.verticalSpacing() == 5
    assert grid.sizeHint() == QSize(111, 36)


def test_settings_secondary_io_uses_dialog_thread_pool_bridge():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    update = source[source.index("    def _refresh_update_recovery"):
                    source.index("    def _clear_update_quarantine")]
    login = source[source.index("    def _refresh_login"):
                   source.index("    def _clear_login")]
    assert "self.runAsync(" in update
    assert "collect_update_diagnostics()" in update
    assert "self.runAsync(" in login
    assert "LoginPreferences().load()" in login
