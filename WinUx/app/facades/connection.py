"""Connection/login compatibility methods exposed by the application controller."""
from __future__ import annotations



class ConnectionFacadeMixin:
    def _auto_login_from_preferences(self):
        return self._connection_controller().auto_login_from_preferences()
    def login(self, dialog, values, automatic=False):
        return self._connection_controller().login(
            dialog, values, automatic=automatic)
    def _login_failed(self, dialog, error, automatic=False):
        return self._connection_controller().login_failed(
            dialog, error, automatic=automatic)
    def _login_succeeded(self, dialog, folder, items, automatic=False):
        return self._connection_controller().login_succeeded(
            dialog, folder, items, automatic=automatic)
    def _start_reconnect(self):
        return self._connection_controller().start_reconnect()
    def _ensure_server_online(self):
        return self._connection_controller().ensure_online()
    def _connection_restored(self, generation):
        return self._connection_controller().restored(generation)
