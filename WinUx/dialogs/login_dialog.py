"""Public SSH Login API backed by a real process-isolated desktop dialog."""
from __future__ import annotations

from ..login_preferences import LoginPreferences
from .floating_dialog import FloatingDialogController


class LoginDialog(FloatingDialogController):
    def __init__(self, view, callback):
        self.callback = callback
        self.preferences = LoginPreferences()
        self._last_values = {}
        self._busy = False
        self._cancelled = False
        # Login uses the same Dear ImGui/Dear PyGui floating runtime as every
        # other WinUx dialog.  Qt names refer only to reusable visual/behavior
        # contracts; there is no Qt or Tk widget backend.
        super().__init__(view, "login", "SSH Login", {"initial": self.preferences.load()},
                         width=420, height=252, modal=True, resizable=False)

    def handle_event(self, event, message):
        if event == "submit" and not self._busy:
            values = message.get("values") or {}
            self._last_values = {key: str(values.get(key, "")) for key in ("host", "port", "username", "password")}
            self._last_values["remember"] = bool(values.get("remember", False))
            self._busy = True
            # Already delivered on the main WinUx UI queue; SSH stays in its
            # existing controller/worker pipeline, never in the child process.
            self.callback(self, dict(self._last_values))

    def values(self):
        return dict(self._last_values)

    def set_busy(self, busy):
        self._busy = bool(busy)
        return self.post("set_busy", bool(busy))

    def set_error(self, message):
        self._busy = False
        return self.post("set_error", str(message))

    def save_preferences(self):
        values = self.values()
        remember = values.pop("remember", False)
        self.preferences.save_success(values, remember)

    def cancel_from_window(self):
        if not self._busy:
            self._cancelled = True
            self.destroy()
