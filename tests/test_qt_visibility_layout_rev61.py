from unittest.mock import Mock

from DearUIQt.qt import QApplication, QSize, QSizePolicy, QWidget, QVBoxLayout


def _backend():
    backend = Mock()
    backend.add_group.side_effect = iter(range(100, 300))
    backend.add_child_window.side_effect = iter(range(300, 400))
    backend.add_window.side_effect = iter(range(400, 500))
    backend.get_item_parent.return_value = 999
    backend.get_item_configuration.return_value = {"show": True, "enabled": True}
    backend.does_item_exist.return_value = True
    return backend


def test_parent_visibility_propagates_effectively_without_hiding_child_explicitly():
    backend = _backend()
    root = QWidget(1, backend=backend)
    child = QWidget(2, parent=root, backend=backend)
    child.hideEvent = Mock()
    child.showEvent = Mock()

    backend.configure_item.reset_mock()
    root.hide()
    assert root.isHidden() is True
    assert child.isVisible() is False
    assert child.isHidden() is False
    child.hideEvent.assert_called_once()
    # Parent propagation must not mutate the child's native explicit show flag.
    assert not any(call.args and call.args[0] == child.tag for call in backend.configure_item.call_args_list)

    root.show()
    assert child.isVisible() is True
    assert child.isHidden() is False
    child.showEvent.assert_called_once()


def test_explicitly_hidden_child_stays_hidden_across_parent_hide_show():
    backend = _backend()
    root = QWidget(1, backend=backend)
    child = QWidget(2, parent=root, backend=backend)
    child.hide()
    assert child.isHidden() is True
    root.hide()
    root.show()
    assert root.isVisible() is True
    assert child.isVisible() is False
    assert child.isHidden() is True
    child.show()
    assert child.isVisible() is True


def test_hidden_layout_items_are_excluded_unless_size_policy_retains_them():
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
    assert layout.sizeHint() == QSize(100, 55)

    second.hide()
    assert layout.sizeHint() == QSize(80, 20)

    policy = second.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    second.setSizePolicy(policy)
    assert layout.sizeHint() == QSize(100, 55)


def test_qsizepolicy_stretch_metadata_round_trips_through_box_layout():
    backend = _backend()
    owner = QWidget(1, backend=backend)
    layout = QVBoxLayout(parent=owner, backend=backend)
    child = QWidget(2, backend=backend)
    layout.addWidget(child)
    assert layout.setStretch(0, 3) is True
    assert layout.stretch(0) == 3
    assert child.sizePolicy().verticalStretch() == 3
    assert isinstance(child.sizePolicy(), QSizePolicy)


def test_qapplication_compresses_layout_requests_by_subtree():
    backend = _backend()
    scheduled = []
    after = lambda delay, callback, *args: scheduled.append((callback, args))
    app = QApplication(after=after)
    try:
        parent = QWidget(1, backend=backend, after=after)
        child = QWidget(2, parent=parent, backend=backend, after=after)
        child.updateGeometry()
        parent.updateGeometry()
        pending = [(receiver, event) for receiver, event in app._posted.values()
                   if event.type() == event.LayoutRequest]
        assert len(pending) == 1
        assert pending[0][0] is parent
        assert len(scheduled) == 1

        app.processEvents()
        parent.updateGeometry()
        child.updateGeometry()
        pending = [(receiver, event) for receiver, event in app._posted.values()
                   if event.type() == event.LayoutRequest]
        assert len(pending) == 1
        assert pending[0][0] is parent
    finally:
        app.delete()


def test_job_schedule_uses_nonblocking_controller_snapshot_on_gui_timer():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/dialogs/job_schedule_form.py").read_text(encoding="utf-8")
    assert "inspect.signature(schedule_provider)" in source
    assert "self.schedule_provider(blocking=False)" in source
    refresh = source[source.index("    def refresh(self):"):source.index("    def set_rows", source.index("    def refresh(self):"))]
    assert "if rows is None:" in refresh
    assert "self.set_rows([tuple(row) for row in rows])" in refresh


def test_settings_hidden_page_preferences_load_off_gui_thread():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    ensure = source[source.index("    def _ensure_page"):source.index("    def _ensure_all_pages")]
    assert "self.runAsync(" in ensure
    assert "self._load_page_data, key" in ensure
    assert 'key in ("general", "updates", "performance", "abaqus")' in ensure
    assert 'QLabel("Loading settings..."' in ensure
    assert "defer_io=False" in source[source.index("    def _ensure_all_pages"):source.index("    def _show_page")]


def test_qdialog_propagates_effective_visibility_to_owned_qwidgets():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    assert "def _sync_owned_widget_visibility" in source
    assert "QWidget._direct_widget_children(self._widget_owner)" in source
    show = source[source.index("    def _show_now"):source.index("    def raise_", source.index("    def _show_now"))]
    hide = source[source.index("    def hide(self):"):source.index("    def event(self, event):", source.index("    def hide(self):"))]
    assert "self._sync_owned_widget_visibility()" in show
    assert "self._sync_owned_widget_visibility()" in hide


def test_settings_first_open_general_preferences_are_not_read_on_click_path():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    init = source[source.index("    def __init__(self, view"):source.index("    def _set_status")]
    assert "INPPreferences().load()" not in init
    assert "GeneralPreferences().load()" not in init
    assert 'self._ensure_page("general")' in init
    loader = source[source.index("    def _load_page_data"):source.index("    def _materialize_page")]
    assert "INPPreferences().load()" in loader
    assert "GeneralPreferences().load()" in loader


def test_widget_visibility_and_enabled_queries_use_retained_state():
    backend = _backend()
    widget = QWidget(1, backend=backend)
    # Construction no longer asks native configuration for default visibility.
    assert backend.get_item_configuration.call_count == 0
    assert widget.isVisible() is True
    assert widget.isEnabled() is True
    assert backend.get_item_configuration.call_count == 0
    widget.setEnabled(False)
    widget.hide()
    backend.get_item_configuration.reset_mock()
    assert widget.isVisible() is False
    assert widget.isHidden() is True
    assert widget.isEnabled() is False
    assert backend.get_item_configuration.call_count == 0
