"""Application-level SSH session lifecycle for WinUx.

WinUx treats each explicit login as one logical *session document*.  Multiple
session documents may remain open at once and are presented as closable tabs in
the main window.  Exactly one session is *active* in the shared workspace at a
time; inactive tabs keep their SSH transport/resource owner but do not own the
visible Server Explorer/Job Viewer state.

The session object deliberately stores metadata only. Passwords and credentials
remain inside the per-session SSHServerModel/LoginPreferences objects and never
enter session diagnostics or logs.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import threading
import uuid


class SessionState:
    CONNECTING = "connecting"
    ACTIVE = "active"
    RECONNECTING = "reconnecting"
    INACTIVE = "inactive"
    ENDED = "ended"

    OPEN = frozenset((CONNECTING, ACTIVE, RECONNECTING, INACTIVE))
    LIVE = OPEN


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _account_key(host, port, username):
    return "{}|{}|{}".format(
        str(host or "").strip().lower(),
        int(port or 22),
        str(username or "").strip().lower(),
    )


@dataclass(frozen=True)
class SessionToken:
    """Immutable ownership token captured by session-scoped async work."""

    session_id: str
    generation: int
    account_key: str

    @property
    def task_scope(self):
        # Task ownership is stable for the full logical-session lifetime.
        # ``generation`` is an activation/UI epoch used to reject stale
        # callbacks; including it here would make long-running transfers from
        # an earlier activation impossible to cancel when the same tab is
        # activated again and later closed.
        return "session:{}".format(self.session_id)

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    generation: int
    state: str
    host: str
    port: int
    username: str
    automatic: bool
    created_at: str
    connected_at: str = ""
    ended_at: str = ""
    end_reason: str = ""
    home: str = ""
    current_path: str = ""
    reconnect_count: int = 0
    last_error: str = ""
    last_activity_at: str = ""
    last_state_change_at: str = ""

    @property
    def short_id(self):
        return self.session_id[:8]

    @property
    def account_label(self):
        if self.username and self.host:
            return "{}@{}".format(self.username, self.host)
        return self.host or self.username

    @property
    def account_key(self):
        return _account_key(self.host, self.port, self.username)

    @property
    def token(self):
        return SessionToken(self.session_id, self.generation, self.account_key)

    @property
    def task_scope(self):
        return self.token.task_scope

    def as_dict(self):
        value = asdict(self)
        value["account_key"] = self.account_key
        value["task_scope"] = self.task_scope
        value["short_id"] = self.short_id
        value["account_label"] = self.account_label
        return value


class AppSessionManager:
    """Thread-safe registry for open login sessions and the active tab.

    ``generation`` remains a monotonically increasing operation epoch.  A tab
    keeps the same ``session_id`` for its full lifetime, but every time it is
    re-activated it receives a fresh generation.  This is intentional: work
    queued before a tab switch can never become valid again merely because the
    user later returns to that tab.

    ``begin_login`` preserves the historical replacement behavior for focused
    integrations/tests. Production multi-tab login uses ``begin_tab_login``.
    """

    def __init__(self, initial_generation=0, history_limit=12):
        self._lock = threading.RLock()
        try:
            generation = int(initial_generation)
        except (TypeError, ValueError):
            generation = 0
        self._generation = max(0, generation)
        self._sessions = {}
        self._order = []
        self._active_id = None
        self._history = deque(maxlen=max(1, int(history_limit)))

    @property
    def generation(self):
        with self._lock:
            return self._generation

    @property
    def current(self):
        with self._lock:
            return self._sessions.get(self._active_id)

    @property
    def current_id(self):
        with self._lock:
            return self._active_id

    @property
    def current_token(self):
        return self.capture()

    def open_sessions(self):
        with self._lock:
            return tuple(
                self._sessions[sid] for sid in self._order
                if sid in self._sessions)

    sessions = open_sessions

    def get(self, session_id):
        with self._lock:
            return self._sessions.get(str(session_id))

    def index_of(self, session_id):
        with self._lock:
            try:
                return self._order.index(str(session_id))
            except ValueError:
                return -1

    def _new_snapshot(self, host, port, username, automatic):
        self._generation += 1
        try:
            parsed_port = int(port)
        except (TypeError, ValueError):
            parsed_port = 22
        now = _utc_now()
        return SessionSnapshot(
            session_id=uuid.uuid4().hex,
            generation=self._generation,
            state=SessionState.CONNECTING,
            host=str(host or "").strip(),
            port=parsed_port,
            username=str(username or "").strip(),
            automatic=bool(automatic),
            created_at=now,
            last_activity_at=now,
            last_state_change_at=now,
        )

    def begin_login(self, host, port, username, *, automatic=False):
        """Historical one-login replacement transaction."""
        with self._lock:
            if self._active_id is not None:
                self._archive_session_locked(self._active_id, "replaced")
            current = self._new_snapshot(host, port, username, automatic)
            self._sessions[current.session_id] = current
            self._order.append(current.session_id)
            self._active_id = current.session_id
            return current

    def begin_tab_login(self, host, port, username, *, automatic=False):
        """Create a new login tab without ending existing open sessions."""
        with self._lock:
            self._suspend_current_locked()
            current = self._new_snapshot(host, port, username, automatic)
            self._sessions[current.session_id] = current
            self._order.append(current.session_id)
            self._active_id = current.session_id
            return current

    def select(self, session_id):
        """Make one existing tab active and invalidate its previous UI epoch."""
        session_id = str(session_id)
        with self._lock:
            target = self._sessions.get(session_id)
            if target is None or target.state == SessionState.ENDED:
                return None
            if self._active_id == session_id:
                return target
            self._suspend_current_locked()
            self._generation += 1
            now = _utc_now()
            # A connected background tab becomes active.  Transport liveness is
            # checked by ConnectionController immediately after the switch; if
            # it dropped while inactive, that controller changes this to
            # RECONNECTING without creating a new session id.
            state = (SessionState.CONNECTING if target.state == SessionState.CONNECTING
                     else SessionState.ACTIVE)
            target = replace(
                target, generation=self._generation, state=state,
                last_activity_at=now, last_state_change_at=now)
            self._sessions[session_id] = target
            self._active_id = session_id
            return target

    def activate(self, session_id, *, home="", current_path=""):
        """Complete/restore a login, active or currently backgrounded."""
        session_id = str(session_id)
        with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                return None
            now = _utc_now()
            connected_at = current.connected_at or now
            state = (SessionState.ACTIVE if self._active_id == session_id
                     else SessionState.INACTIVE)
            current = replace(
                current,
                state=state,
                connected_at=connected_at,
                home=str(home or current.home or ""),
                current_path=str(current_path or current.current_path or ""),
                last_error="",
                last_activity_at=now,
                last_state_change_at=(
                    now if current.state != state
                    else current.last_state_change_at or now),
            )
            self._sessions[session_id] = current
            return current

    def mark_reconnecting(self, session_id, error=""):
        session_id = str(session_id)
        with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                return None
            now = _utc_now()
            # Inactive tabs do not run a reconnect supervisor. Preserve their
            # inactive presentation; activation will perform the liveness check.
            if self._active_id != session_id:
                if error:
                    current = replace(
                        current, last_error=str(error), last_activity_at=now)
                    self._sessions[session_id] = current
                return current
            if current.state != SessionState.RECONNECTING:
                current = replace(
                    current,
                    state=SessionState.RECONNECTING,
                    reconnect_count=current.reconnect_count + 1,
                    last_error=str(error or current.last_error or ""),
                    last_activity_at=now,
                    last_state_change_at=now,
                )
            elif error:
                current = replace(
                    current, last_error=str(error), last_activity_at=now)
            self._sessions[session_id] = current
            return current

    def restore(self, session_id, *, home="", current_path=""):
        return self.activate(session_id, home=home, current_path=current_path)

    def touch(self, session_id=None, *, current_path=None):
        with self._lock:
            sid = str(session_id) if session_id is not None else self._active_id
            current = self._sessions.get(sid)
            if current is None:
                return None
            changes = {"last_activity_at": _utc_now()}
            if current_path is not None:
                changes["current_path"] = str(current_path or "")
            current = replace(current, **changes)
            self._sessions[sid] = current
            return current

    def update_path(self, path, session_id=None):
        return self.touch(session_id, current_path=path)

    def fail(self, session_id, error=""):
        """End a failed tab login without disturbing sibling sessions."""
        session_id = str(session_id)
        with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                return None
            current = replace(
                current, last_error=str(error or ""), last_activity_at=_utc_now())
            self._sessions[session_id] = current
            ended = self._archive_session_locked(session_id, "login_failed")
            self._generation += 1
            return ended

    def close(self, session_id=None, reason="tab_closed"):
        """Close one tab/session and invalidate work owned by its generation."""
        with self._lock:
            sid = str(session_id) if session_id is not None else self._active_id
            if sid is None or sid not in self._sessions:
                return None
            ended = self._archive_session_locked(sid, reason)
            self._generation += 1
            return ended

    def end(self, reason="logout"):
        return self.close(None, reason=reason)

    def close_all(self, reason="app_close"):
        """Close every open tab/session and return their ended snapshots."""
        with self._lock:
            ended = []
            for sid in tuple(self._order):
                value = self._archive_session_locked(sid, reason)
                if value is not None:
                    ended.append(value)
            self._generation += 1
            return tuple(ended)

    def capture(self, *, require_live=True):
        with self._lock:
            current = self._sessions.get(self._active_id)
            if current is None:
                return None
            if require_live and current.state not in SessionState.OPEN:
                return None
            return current.token

    def task_scope(self, session=None):
        with self._lock:
            value = session if session is not None else self._sessions.get(self._active_id)
            if value is None:
                return None
            if isinstance(value, SessionToken):
                return value.task_scope
            if isinstance(value, SessionSnapshot):
                return value.task_scope
            session_id = getattr(value, "session_id", None)
            if session_id is None:
                return None
            return "session:{}".format(str(session_id))

    def is_token_current(self, token, *, require_active=False):
        if token is None:
            return False
        with self._lock:
            current = self._sessions.get(self._active_id)
            if current is None:
                return False
            if (current.session_id != str(token.session_id) or
                    current.generation != int(token.generation)):
                return False
            if require_active:
                return current.state == SessionState.ACTIVE
            return current.state in (SessionState.CONNECTING,
                                     SessionState.ACTIVE,
                                     SessionState.RECONNECTING)

    def is_current(self, session_id, *, generation=None):
        with self._lock:
            current = self._sessions.get(self._active_id)
            if current is None or current.session_id != str(session_id):
                return False
            if generation is not None and current.generation != int(generation):
                return False
            return current.state in (SessionState.CONNECTING,
                                     SessionState.ACTIVE,
                                     SessionState.RECONNECTING)

    def is_open(self, session_id, *, generation=None):
        with self._lock:
            current = self._sessions.get(str(session_id))
            if current is None or current.state == SessionState.ENDED:
                return False
            if generation is not None and current.generation != int(generation):
                return False
            return True

    def has_session(self):
        with self._lock:
            current = self._sessions.get(self._active_id)
            return current is not None and current.state in (
                SessionState.CONNECTING, SessionState.ACTIVE,
                SessionState.RECONNECTING)

    def has_open_sessions(self):
        with self._lock:
            return bool(self._sessions)

    def history(self):
        with self._lock:
            return tuple(self._history)

    def snapshot(self):
        """Return a diagnostics-safe multi-session snapshot."""
        with self._lock:
            current = self._sessions.get(self._active_id)
            token = current.token if current is not None else None
            open_values = [
                self._sessions[sid] for sid in self._order if sid in self._sessions]
            return {
                "generation": self._generation,
                "active": current is not None and current.state in (
                    SessionState.CONNECTING, SessionState.ACTIVE,
                    SessionState.RECONNECTING),
                "active_session_id": self._active_id,
                "open_count": len(open_values),
                "task_scope": token.task_scope if token is not None else None,
                "current": current.as_dict() if current is not None else None,
                "sessions": [item.as_dict() for item in open_values],
                "recent": [item.as_dict() for item in list(self._history)[-4:]],
            }

    def _suspend_current_locked(self):
        current = self._sessions.get(self._active_id)
        if current is None:
            self._active_id = None
            return None
        now = _utc_now()
        if current.state != SessionState.CONNECTING:
            current = replace(
                current, state=SessionState.INACTIVE,
                last_activity_at=now, last_state_change_at=now)
            self._sessions[current.session_id] = current
        self._active_id = None
        return current

    def _matching_locked(self, session_id):
        current = self._sessions.get(self._active_id)
        if current is None or current.session_id != str(session_id):
            return None
        return current

    def _archive_session_locked(self, session_id, reason):
        sid = str(session_id)
        current = self._sessions.get(sid)
        if current is None:
            return None
        now = _utc_now()
        ended = replace(
            current,
            state=SessionState.ENDED,
            ended_at=now,
            end_reason=str(reason or "ended"),
            last_activity_at=now,
            last_state_change_at=now,
        )
        self._history.append(ended)
        self._sessions.pop(sid, None)
        try:
            self._order.remove(sid)
        except ValueError:
            pass
        if self._active_id == sid:
            self._active_id = None
        return ended


__all__ = [
    "AppSessionManager", "SessionSnapshot", "SessionState", "SessionToken",
]
