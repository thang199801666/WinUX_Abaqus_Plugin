from unittest.mock import MagicMock

from DearUIQt import (
    QAction,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    Qt,
    QWidget,
)


def backend():
    ui = MagicMock()
    ids = iter(range(100, 1000))
    for name in (
        "add_child_window", "add_window", "add_group", "add_button",
        "add_text", "add_separator", "add_spacer", "add_item_handler_registry",
    ):
        getattr(ui, name).side_effect = lambda *args, _ids=ids, **kwargs: next(_ids)
    ui.does_item_exist.return_value = True
    ui.get_item_parent.return_value = 10
    ui.get_item_rect_size.side_effect = lambda tag: (800, 400)
    ui.get_item_rect_min.return_value = (0, 0)
    ui.get_item_configuration.return_value = {"width": 800, "height": 400, "show": True, "enabled": True}
    ui.get_item_state.return_value = {}
    ui.get_mouse_pos.return_value = (400, 200)
    ui.mvMouseButton_Left = 0
    return ui


def test_new_widget_catalog_is_available_from_package_root():
    import DearUIQt

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 2, 0)
    for name in ("QToolButton", "QToolBar", "QStatusBar", "QScrollArea", "QSplitter"):
        assert name in DearUIQt.__all__
        assert getattr(DearUIQt, name).__name__ == name


def test_qscrollarea_owns_one_widget_and_can_detach_it():
    ui = backend()
    area = QScrollArea(parent=10, backend=ui)
    content = QWidget(parent=10, backend=ui)
    assert area.setWidget(content) is content
    assert area.widget() is content
    assert content.parent is area
    ui.move_item.assert_any_call(content.tag, parent=area.tag)
    detached = area.takeWidget()
    assert detached is content
    assert area.widget() is None
    assert content.parent is None


def test_qsplitter_manages_children_sizes_and_programmatic_handle_moves():
    ui = backend()
    splitter = QSplitter(Qt.Horizontal, parent=10, backend=ui, handle_width=5)
    left = QWidget(parent=10, backend=ui)
    right = QWidget(parent=10, backend=ui)
    splitter.addWidget(left)
    splitter.addWidget(right)
    assert splitter.count() == 2
    assert splitter.indexOf(left) == 0
    assert splitter.widget(1) is right

    splitter.setSizes([3, 5])
    sizes = splitter.sizes()
    assert sum(sizes) + splitter.handleWidth() == 800
    assert sizes[0] < sizes[1]

    moved = []
    splitter.splitterMoved.connect(lambda position, index: moved.append((position, index)))
    assert splitter.moveSplitter(400, 1)
    sizes = splitter.sizes()
    assert sizes == [400, 395]
    assert moved[-1] == (400, 1)

    state = splitter.saveState()
    splitter.setOrientation(Qt.Vertical)
    assert splitter.restoreState(state)
    assert splitter.orientation() == Qt.Horizontal


def test_qtoolbar_binds_actions_to_qtoolbuttons_without_application_resources():
    ui = backend()
    toolbar = QToolBar("Edit", parent=10, backend=ui)
    action = QAction("Refresh")
    toolbar.addAction(action)
    button = toolbar.widgetForAction(action)
    assert isinstance(button, QToolButton)
    assert toolbar.actions() == [action]
    assert button.defaultAction() is action
    assert button.text() == "Refresh"

    action.setText("Reload")
    assert button.text() == "Reload"
    assert toolbar.removeAction(action)
    assert toolbar.actions() == []


def test_qtoolbutton_menu_and_autoraise_are_framework_owned():
    ui = backend()
    button = QToolButton("Menu", parent=10, backend=ui)
    assert button.autoRaise() is True
    button.setAutoRaise(False)
    assert button.autoRaise() is False
    button.setPopupMode(QToolButton.InstantPopup)
    assert button.popupMode() == QToolButton.InstantPopup


def test_qstatusbar_retains_message_and_permanent_widgets():
    ui = backend()
    status = QStatusBar(parent=10, backend=ui)
    changed = []
    status.messageChanged.connect(changed.append)
    status.showMessage("Ready")
    assert status.currentMessage() == "Ready"
    assert changed[-1] == "Ready"
    permanent = QLabel("Ln 1", parent=10, backend=ui)
    status.addPermanentWidget(permanent)
    assert permanent.parent is status.layout()
    status.clearMessage()
    assert status.currentMessage() == ""
    assert changed[-1] == ""


def test_winux_workspace_toolbar_specializes_dearuiqt_toolbar():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx" / "ui" / "workspace.py").read_text(encoding="utf-8")
    assert "from DearUIQt.qt import QWidget, QGridLayout, QToolBar" in source
    assert "class ToolBar(QToolBar):" in source
    assert "QHBoxLayout" not in source
