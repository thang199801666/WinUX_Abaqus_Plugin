from __future__ import annotations

from WinUx.app.session import AppSessionManager, SessionState


def test_one_login_is_one_session_and_reconnect_keeps_identity():
    manager = AppSessionManager(initial_generation=4)
    first = manager.begin_login("cluster-a", 22, "alice")
    assert first.generation == 5
    assert first.state == SessionState.CONNECTING

    active = manager.activate(first.session_id, home="/home/alice", current_path="/work")
    assert active.session_id == first.session_id
    assert active.state == SessionState.ACTIVE

    reconnecting = manager.mark_reconnecting(first.session_id)
    assert reconnecting.session_id == first.session_id
    assert reconnecting.reconnect_count == 1
    restored = manager.restore(first.session_id, current_path="/work/job")
    assert restored.session_id == first.session_id
    assert restored.state == SessionState.ACTIVE
    assert restored.generation == 5

    second = manager.begin_login("cluster-b", 2222, "bob")
    assert second.session_id != first.session_id
    assert second.generation == 6
    assert manager.current_id == second.session_id
    assert manager.history()[-1].session_id == first.session_id
    assert manager.history()[-1].end_reason == "replaced"


def test_logout_invalidates_generation_and_snapshot_never_contains_password():
    manager = AppSessionManager()
    session = manager.begin_login("server", 22, "user")
    manager.activate(session.session_id)
    before = manager.generation
    ended = manager.end("logout")

    assert ended.session_id == session.session_id
    assert ended.state == SessionState.ENDED
    assert ended.end_reason == "logout"
    assert manager.current is None
    assert manager.generation == before + 1
    snapshot = manager.snapshot()
    assert snapshot["active"] is False
    assert "password" not in repr(snapshot).lower()


def test_failed_login_is_not_left_as_current_session():
    manager = AppSessionManager()
    session = manager.begin_login("server", 22, "user", automatic=True)
    before = manager.generation
    ended = manager.fail(session.session_id, "denied")

    assert ended.last_error == "denied"
    assert ended.end_reason == "login_failed"
    assert manager.current is None
    assert manager.generation == before + 1


def test_session_token_scope_is_stable_across_reconnect_and_invalid_after_switch():
    manager = AppSessionManager()
    first = manager.begin_login("cluster-a", 22, "Alice")
    manager.activate(first.session_id, current_path="/work")
    token = manager.capture()

    assert token is not None
    assert manager.is_token_current(token)
    assert token.task_scope == first.task_scope
    assert token.account_key == "cluster-a|22|alice"

    manager.mark_reconnecting(first.session_id, "temporary network loss")
    assert manager.is_token_current(token)
    manager.restore(first.session_id, current_path="/work/case")
    assert manager.capture() == token

    second = manager.begin_login("cluster-a", 22, "Alice")
    assert second.session_id != first.session_id
    assert not manager.is_token_current(token)
    assert manager.task_scope(first) != manager.task_scope(second)


def test_session_snapshot_exposes_management_metadata_without_credentials():
    manager = AppSessionManager()
    session = manager.begin_login("Cluster-A", 2222, "Alice")
    manager.activate(session.session_id, home="/home/alice", current_path="/work")
    manager.touch(current_path="/work/job-1")

    snapshot = manager.snapshot()
    current = snapshot["current"]
    assert snapshot["task_scope"] == current["task_scope"]
    assert current["account_key"] == "cluster-a|2222|alice"
    assert current["current_path"] == "/work/job-1"
    assert current["last_activity_at"]
    assert current["last_state_change_at"]
    assert "password" not in repr(snapshot).lower()


def test_task_scope_is_stable_across_tab_reactivation_while_token_epoch_changes():
    manager = AppSessionManager()
    first = manager.begin_tab_login("cluster-a", 22, "alice")
    manager.activate(first.session_id)
    first_token = manager.capture()
    first_scope = manager.task_scope(first)

    second = manager.begin_tab_login("cluster-b", 22, "bob")
    manager.activate(second.session_id)
    reactivated = manager.select(first.session_id)
    second_token = manager.capture()

    assert reactivated.session_id == first.session_id
    assert second_token.generation != first_token.generation
    assert manager.task_scope(reactivated) == first_scope
    assert second_token.task_scope == first_scope
