from pathlib import Path
from unittest.mock import Mock

from DearUIQt.qt import QApplication, QSize, QWidget, QVBoxLayout, QStackedWidget

ROOT = Path(__file__).resolve().parents[1]


def _backend():
    backend = Mock()
    backend.add_group.side_effect = iter(range(100, 300))
    backend.add_child_window.side_effect = iter(range(300, 400))
    backend.add_window.side_effect = iter(range(400, 500))
    backend.get_item_parent.return_value = 999
    backend.get_item_configuration.return_value = {"show": True, "enabled": True}
    backend.does_item_exist.return_value = True
    return backend


def test_qsize_and_layout_size_hints_are_qt_style_and_cached():
    backend = _backend()
    owner = QWidget(1, backend=backend)
    layout = QVBoxLayout(parent=owner, backend=backend, spacing=5)
    owner.setLayout(layout)
    first = QWidget(2, backend=backend)
    second = QWidget(3, backend=backend)
    first.setFixedSize(80, 20)
    second.setFixedSize(120, 30)
    layout.addWidget(first)
    layout.addWidget(second)
    assert layout.sizeHint() == QSize(120, 55)
    assert owner.sizeHint() == QSize(120, 55)
    # Child geometry changes invalidate the parent layout cache and propagate.
    second.setFixedSize(150, 40)
    assert layout.sizeHint() == QSize(150, 65)
    assert QSize(10, 20).transposed() == QSize(20, 10)
    fixed = QWidget(4, backend=backend)
    fixed.setFixedSize(90, 25)
    fixed.resize(140, 60)
    # resize() changes geometry without mutating Qt min/max constraints.
    assert fixed.minimumSize() == QSize(90, 25)
    assert fixed.maximumSize() == QSize(90, 25)


def test_layout_request_activates_installed_layout_once_until_invalidated():
    backend = _backend()
    queued = []
    after = lambda delay, callback, *args: queued.append((callback, args))
    owner = QWidget(1, backend=backend, after=after)
    layout = QVBoxLayout(parent=owner, backend=backend, after=after)
    owner.setLayout(layout)
    assert layout.activate() is True
    assert layout.activate() is False
    child = QWidget(2, backend=backend, after=after)
    layout.addWidget(child)
    assert layout.activate() is True
    assert layout.activate() is False
    # Multiple invalidations share the owner's queued layout wake-up.
    assert len(queued) == 1


def test_qstackedwidget_switches_only_old_and_new_pages():
    backend = _backend()
    stack = QStackedWidget(parent=99, backend=backend)
    first = stack.addPage()
    second = stack.addPage()
    third = stack.addPage()
    backend.configure_item.reset_mock()
    assert stack.currentWidget() is first
    assert stack.setCurrentWidget(third) is True
    show_calls = [call for call in backend.configure_item.call_args_list if "show" in call.kwargs]
    assert len(show_calls) == 2
    assert show_calls[0].args[0] == first.tag and show_calls[0].kwargs["show"] is False
    assert show_calls[1].args[0] == third.tag and show_calls[1].kwargs["show"] is True
    backend.configure_item.reset_mock()
    assert stack.setCurrentWidget(third) is True
    assert backend.configure_item.call_count == 0
    assert stack.count() == 3 and stack.indexOf(second) == 1



def test_hiding_widget_drops_queued_layout_work_for_its_subtree():
    backend = _backend()
    scheduled = []
    after = lambda delay, callback, *args: scheduled.append((callback, args))
    app = QApplication(after=after)
    try:
        parent = QWidget(1, backend=backend, after=after)
        child = QWidget(2, parent=parent, backend=backend, after=after)
        assert child.updateGeometry() is True
        assert any(receiver is child for receiver, _event in app._posted.values())
        parent.hide()
        assert not any(receiver is child for receiver, _event in app._posted.values())
    finally:
        app.delete()

def test_settings_uses_qstackedwidget_and_no_longer_reconfigures_every_page():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    assert "QStackedWidget" in source
    assert "self.page_stack.setCurrentWidget(self._page_widgets[key])" in source
    block = source[source.index("    def _show_page"):source.index("    def _build_general_page")]
    assert "for name, page in self.pages.items()" not in block


def test_retained_dialog_layout_is_deferred_while_hidden_and_native_layout_is_cached():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    update = source[source.index("    def updateGeometry(self):"):source.index("    def _on_native_resize")]
    assert "if not self.isVisible():" in update
    assert "self._retained_layout_dirty = True" in update
    show = source[source.index("    def _show_now(self):"):source.index("    def raise_(self):")]
    assert "if self._retained_layout_dirty:" in show
    assert "self.sendEvent(QEvent(QEvent.LayoutRequest))" in show
    apply = source[source.index("    def _configure_layout_item"):source.index("    def updateGeometry(self):")]
    assert "if not changed:" in apply
    assert "self._layout_native_state" in apply


def test_inprocess_diagnostics_collects_report_off_gui_thread():
    source = (ROOT / "WinUx/dialogs/inprocess/diagnostics.py").read_text(encoding="utf-8")
    assert "self.runAsync(" in source
    assert "on_result=self._diagnostics_ready" in source
    assert "Refreshing diagnostics" in source
