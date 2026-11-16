"""Session tabs must not mutate the primary tree during native QDialog lifetime."""
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.ui.main_window import WinUXView
from DearUIQt.dialogs.qt_dialog import QtDialog


def _view_stub(safe=False):
    view = SimpleNamespace()
    view._alive = True
    view._pending_session_tabs_snapshot = None
    view._session_tabs_flush_scheduled = False
    view._layout_dirty = False
    view.after = Mock(return_value=1)
    view._session_tab_mutation_safe = Mock(return_value=safe)
    view._flush_session_tabs = lambda: WinUXView._flush_session_tabs(view)
    view.session_tabs = SimpleNamespace(set_sessions=Mock(return_value=True))
    view._apply_split_layout = Mock()
    return view


def test_session_tab_snapshot_is_deferred_while_native_dialog_is_active():
    view = _view_stub(safe=False)
    snapshot = {"sessions": [{"session_id": "A"}], "active_session_id": "A"}

    assert WinUXView.set_session_tabs(view, snapshot) is False
    assert view._pending_session_tabs_snapshot == snapshot
    assert view._session_tabs_flush_scheduled is True
    view.session_tabs.set_sessions.assert_not_called()
    view.after.assert_called_once_with(40, view._flush_session_tabs)


def test_deferred_session_tabs_commit_once_dialog_transaction_is_safe():
    view = _view_stub(safe=True)
    snapshot = {"sessions": [{"session_id": "A"}], "active_session_id": "A"}
    view._pending_session_tabs_snapshot = snapshot
    view._session_tabs_flush_scheduled = True

    assert WinUXView._flush_session_tabs(view) is True
    view.session_tabs.set_sessions.assert_called_once_with(snapshot)
    view._apply_split_layout.assert_called_once_with(force=True)
    assert view._pending_session_tabs_snapshot is None
    assert view._session_tabs_flush_scheduled is False


def test_qdialog_native_hide_fallback_does_not_require_owner_close_lease():
    backend = SimpleNamespace(hideSecondaryWindow=Mock(return_value=True))
    dialog = SimpleNamespace(tag=77, _native_window_backend=backend)

    assert QtDialog._hide_native_surface_now(dialog) is True
    backend.hideSecondaryWindow.assert_called_once_with(77)
