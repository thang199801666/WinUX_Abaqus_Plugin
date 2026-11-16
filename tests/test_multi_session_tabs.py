from WinUx.app.session import AppSessionManager, SessionState
from WinUx.app.session_workspace import SessionWorkspaceRegistry


def test_multiple_login_tabs_keep_identity_and_switch_generation():
    manager = AppSessionManager(initial_generation=3)
    first = manager.begin_tab_login("alpha", 22, "alice")
    manager.activate(first.session_id, home="/home/alice", current_path="/a")
    first_generation = manager.current.generation

    second = manager.begin_tab_login("beta", 22, "bob")
    manager.activate(second.session_id, home="/home/bob", current_path="/b")

    assert manager.current_id == second.session_id
    assert manager.get(first.session_id).state == SessionState.INACTIVE
    assert [s.session_id for s in manager.open_sessions()] == [first.session_id, second.session_id]

    selected = manager.select(first.session_id)
    assert selected.session_id == first.session_id
    assert selected.generation > first_generation
    assert manager.get(second.session_id).state == SessionState.INACTIVE
    assert manager.current_id == first.session_id


def test_closing_background_session_does_not_close_active_session():
    manager = AppSessionManager()
    first = manager.begin_tab_login("alpha", 22, "alice")
    manager.activate(first.session_id)
    second = manager.begin_tab_login("beta", 22, "bob")
    manager.activate(second.session_id)

    ended = manager.close(first.session_id)
    assert ended.session_id == first.session_id
    assert ended.state == SessionState.ENDED
    assert manager.current_id == second.session_id
    assert manager.is_open(second.session_id)


def test_workspace_registry_owns_distinct_server_instances():
    registry = SessionWorkspaceRegistry()
    one = object()
    two = object()
    registry.add("one", one)
    registry.add("two", two)
    assert registry.server_for("one") is one
    assert registry.server_for("two") is two
    assert registry.remove("one").server is one
    assert registry.server_for("one") is None


def test_switch_keeps_session_transfer_lane_alive_but_close_cancels_it():
    import threading
    from types import SimpleNamespace
    from WinUx.controllers.connection import ConnectionController

    class Tasks:
        def __init__(self):
            self.cancelled = []
        def cancel_scope(self, scope):
            self.cancelled.append(scope)

    class View:
        def clear_server_session(self):
            pass

    manager = AppSessionManager()
    session = manager.begin_tab_login("alpha", 22, "alice")
    manager.activate(session.session_id)
    background, transfer, analysis = Tasks(), Tasks(), Tasks()
    app = SimpleNamespace(
        session_manager=manager,
        _session_workspaces=SessionWorkspaceRegistry(),
        _background_tasks=background,
        _transfer_tasks=transfer,
        _analysis_tasks=analysis,
        _stop_job_polling=lambda: None,
        _stop_all_job_plots=lambda: None,
        _schedule_execution=None,
        _server_notepad=None,
        _connection_online=SimpleNamespace(clear=lambda: None),
        _server_nav_generation=0,
        _reconnect_lock=threading.Lock(),
        _reconnect_active=False,
        view=View(),
        server=SimpleNamespace(request_shutdown=lambda **_kwargs: None),
    )
    controller = ConnectionController(app, adopt_existing=True)
    scope = manager.task_scope(session)

    controller._deactivate_remote_runtime(
        session=session, clear_view=False, disconnect=False, server=app.server)
    assert background.cancelled == [scope]
    assert analysis.cancelled == [scope]
    assert transfer.cancelled == []

    controller._deactivate_remote_runtime(
        session=session, clear_view=False, disconnect=True, server=app.server)
    assert transfer.cancelled == [scope]
