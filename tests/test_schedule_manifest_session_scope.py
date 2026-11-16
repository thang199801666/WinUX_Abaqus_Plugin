from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from WinUx.app.session import AppSessionManager
from WinUx.controllers.jobs.manifest import ScheduleManifestController


class _Handle:
    state = "done"


class _View:
    def after(self, _delay, callback, *args):
        return callback(*args)


class _Server:
    def __init__(self):
        self.host = ""
        self._port = 22
        self.username = ""
        self.connected = False
        self.remote_entries = []
        self.writes = []

    def ensure_schedule_storage(self):
        return None

    def read_schedule_manifest(self):
        return list(self.remote_entries)

    def write_schedule_manifest(self, entries):
        self.remote_entries = list(entries)
        self.writes.append(list(entries))


def _activate(app, host, port, username):
    session = app.session_manager.begin_login(host, port, username)
    app.session_manager.activate(session.session_id)
    app._connection_generation = app.session_manager.generation
    app.server.host = host
    app.server._port = port
    app.server.username = username
    return session


def _task(schedule_id):
    return {
        "schedule_id": schedule_id,
        "job_name": "case-1",
        "owner": "alice",
        "target": datetime(2030, 1, 1, tzinfo=timezone.utc),
        "mode": "later",
        "path": "/work",
        "job": {"name": "case-1"},
    }


def test_recovery_queue_never_crosses_login_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    manager = AppSessionManager()
    server = _Server()
    reconnects = []
    app = SimpleNamespace(
        _closing=False,
        _connection_generation=0,
        _connection_online=SimpleNamespace(clear=lambda: None),
        _start_reconnect=lambda: reconnects.append(True),
        _submit_background=lambda _name, worker, **_kwargs: (worker() or _Handle()),
        _install_shared_schedules=lambda _entries: None,
        session_manager=manager,
        server=server,
        view=_View(),
    )
    controller = ScheduleManifestController(app)

    # Account A queues a mutation while offline.
    _activate(app, "cluster-a", 22, "alice")
    server.connected = False
    assert controller.save(_task("A-1"), "run") is True
    assert reconnects
    assert not server.writes

    # Switching to B must not flush A's journal into B's shared manifest.
    _activate(app, "cluster-b", 22, "bob")
    server.connected = True
    controller.flush_async()
    assert not server.writes

    # Logging back into A resumes the original account-scoped journal.
    _activate(app, "cluster-a", 22, "alice")
    server.connected = True
    controller.flush_async()
    assert len(server.writes) == 1
    assert [row["schedule_id"] for row in server.writes[0]] == ["A-1"]


def test_recovery_file_schema_is_account_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    manager = AppSessionManager()
    server = _Server()
    app = SimpleNamespace(
        _closing=False,
        _connection_generation=0,
        _connection_online=SimpleNamespace(clear=lambda: None),
        _start_reconnect=lambda: None,
        _submit_background=lambda _name, _worker, **_kwargs: _Handle(),
        _install_shared_schedules=lambda _entries: None,
        session_manager=manager,
        server=server,
        view=_View(),
    )
    _activate(app, "cluster-a", 2222, "alice")
    controller = ScheduleManifestController(app)
    assert controller.save(_task("A-2"), "run") is True

    payload = controller._recovery_store.load()
    assert payload["schema_version"] == 2
    assert list(payload["accounts"]) == ["cluster-a|2222|alice"]
    account = payload["accounts"]["cluster-a|2222|alice"]
    assert "A-2" in account["pending_saves"]


def test_retry_callbacks_are_coalesced_and_do_not_cross_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    class QueuedView:
        def __init__(self):
            self.pending = []
        def after(self, delay, callback, *args):
            self.pending.append((delay, callback, args))
            return len(self.pending)

    manager = AppSessionManager()
    server = _Server()
    view = QueuedView()
    app = SimpleNamespace(
        _closing=False,
        _connection_generation=0,
        _connection_online=SimpleNamespace(clear=lambda: None),
        _start_reconnect=lambda: None,
        _submit_background=lambda _name, _worker, **_kwargs: _Handle(),
        _install_shared_schedules=lambda _entries: None,
        session_manager=manager,
        server=server,
        view=view,
    )
    controller = ScheduleManifestController(app)
    _activate(app, "cluster-a", 22, "alice")
    account_a = controller._account_key()
    calls = []

    assert controller._schedule_retry("flush", account_a, 1000, lambda: calls.append("A"))
    assert not controller._schedule_retry("flush", account_a, 1000, lambda: calls.append("dup"))
    assert len(view.pending) == 1

    # A delayed callback from A must become inert after switching to B.
    _activate(app, "cluster-b", 22, "bob")
    _delay, callback, args = view.pending.pop(0)
    callback(*args)
    assert calls == []
    assert not controller._retry_pending
