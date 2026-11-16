from __future__ import annotations

from types import SimpleNamespace

from WinUx.app.session import AppSessionManager
from WinUx.runtime.operation_context import OperationContext


def test_remote_operation_is_scoped_to_logical_session_id():
    manager = AppSessionManager()
    session = manager.begin_login("host-a", 22, "alice")
    manager.activate(session.session_id)
    app = SimpleNamespace(
        _closing=False,
        _connection_generation=manager.generation,
        session_manager=manager,
    )
    context = OperationContext(app, remote=True)
    assert context.current()

    replacement = manager.begin_login("host-b", 22, "bob")
    app._connection_generation = manager.generation
    assert replacement.session_id != session.session_id
    assert not context.current()
