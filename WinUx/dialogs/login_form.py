from __future__ import annotations

from ..preferences.login import LoginPreferences
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QComboBox
from DearUIQt.widgets import QCheckBox


class LoginForm(QtDialog):
    """Login client area shared by the standalone DPG dialog host and tests."""

    REUSABLE_HOST = True
    # Login is a compact credential form, not a workspace/tool window. Keep it
    # fixed in both the normal in-process QDialog path and the legacy floating
    # process host (FloatingDialogRuntime reads this compatibility contract).
    NATIVE_RESIZABLE = False
    # Modal credential dialogs are owned windows and therefore have no independent
    # taskbar entry. Do not expose Minimize: an iconic owned dialog cannot be
    # rediscovered from the taskbar while its modal owner is disabled.
    ALLOW_MINIMIZE = False
    ALLOW_MAXIMIZE = False

    def __init__(self, view, callback, initial=None):
        self.callback = callback
        self.preferences = LoginPreferences()
        initial = self.preferences.load() if initial is None else dict(initial)
        self._ports = dict(initial.get("ports", {}))
        self._cancelled = False
        self._busy = False
        self._last_values = {}
        self._combos = []
        # Match the pre-migration login geometry: one compact form, no nested
        # group-box chrome.  The controls themselves remain retained Dear ImGui
        # widgets and keep the newer focus/validation behavior.
        # The application's 15px Segoe UI font makes the five-row table a
        # little taller than the standalone host's 14px font. Leave breathing
        # room above the fixed footer: 204px caused a 2px body overflow and an
        # otherwise unnecessary scrollbar in the main application.
        super().__init__(view, "SSH Login", 420, 212, resizable=False)
        # A single QFormLayout-like table keeps all four editors on one shared
        # baseline/label column.  The previous one-table-per-field layout added
        # Dear ImGui ItemSpacing between every row and made this small dialog
        # look much looser than its Qt counterpart.
        self.preferred_size = (420, 212)
        self._form = self.form_layout(parent=self.content, label_width=78)
        self.host_combo = self._combo_field(
            "Host:", initial.get("hosts", []), initial.get("host", ""),
            self._host_changed, self._form)
        self.host = self.host_combo.lineEdit().tag
        self.port = self._line_field("Port:", initial.get("port", "22"), self._form)
        self.username_combo = self._combo_field(
            "Username:", initial.get("usernames", []), initial.get("username", ""),
            self._username_changed, self._form)
        self.username = self.username_combo.lineEdit().tag
        self.password = self._line_field(
            "Password:", initial.get("password", ""), self._form, password=True)
        # Keep the indicator on the editors' left edge without reserving an
        # empty 26 px label cell, which made the compact checkbox row too tall.
        self._remember_widget = self.form_layout_editor_row(
            self._form,
            lambda remember_cell: self.own_widget(QCheckBox(
                "Remember password for this Windows account",
                checked=initial.get("remember", False), parent=remember_cell,
                after=view.after)))
        self.remember = self._remember_widget.tag
        self.error = self.status_text(error=True, wrap=360)
        self.connect_button, self.cancel_button = self.button_box([
            ("Connect", self.submit, "primary", True),
            ("Cancel", self.cancel_from_window, "secondary", False)])

    def _combo_field(self, label, items, value, callback, parent=None):
        combo = self.form_layout_row(
            parent or self._form, label,
            lambda editor_parent: self.own_widget(QComboBox(
                items=items, current=value, width=-1, callback=callback,
                parent=self._qt_parent(editor_parent), after=self.view.after, editable=True)))
        # Emit edits as well as history selection; there is only one field per
        # value, with the arrow beside the editable text like QComboBox.
        # Host and Username are history-backed *editable* combos.  The value
        # does not have to exist in the dropdown: users can type a new server
        # or account name directly and a successful login will persist it via
        # LoginPreferences.save_success().
        combo.setEditable(True)
        combo.setMaxVisibleItems(6)
        combo.setPopupParent(self.tag)
        combo.lineEdit().configure(hint="Type or choose from history")
        self._control_wrappers[combo.tag] = combo
        self._control_wrappers[combo.lineEdit().tag] = combo
        self._remember_focusable(combo.lineEdit().tag)
        self._combos.append(combo)
        return combo

    def _line_field(self, label, value, parent=None, **kwargs):
        return self.form_layout_row(
            parent or self._form, label,
            lambda editor_parent: self.line_edit(
                value, parent=editor_parent, width=-1, **kwargs))

    def invoke_default(self):
        if not any(combo.popupVisible() for combo in self._combos):
            super().invoke_default()

    def destroy(self):
        if not self._destroy_scheduled:
            for combo in self._combos:
                combo.hidePopup()
        super().destroy()

    def _focus_initial(self):
        if not self.winfo_exists():
            return
        target = self.host if not str(self.control_value(self.host, "") or "").strip() else self.username
        if str(self.control_value(self.username, "") or "").strip() and not self.control_value(self.password, ""):
            target = self.password
        if target == self.host:
            self.host_combo.setFocus()
        elif target == self.username:
            self.username_combo.setFocus()
        else:
            self.focus_editor(target)

    def port_for_host(self, host):
        return self._ports.get(str(host).strip())

    def password_for(self, username):
        try:
            return self.preferences.password_for(str(username).strip())
        except Exception:
            return ""

    def _choose_host(self, value):
        self.set_control_value(self.host, value)
        self._host_changed(None, value)

    def _choose_username(self, value):
        self.set_control_value(self.username, value)
        self._username_changed(None, value)

    def _host_changed(self, sender, value, user_data=None):
        port = self.port_for_host(value)
        if port:
            self.set_control_value(self.port, str(port))

    def _username_changed(self, sender, value, user_data=None):
        self.set_control_value(self.password, self.password_for(value))

    def values(self):
        if self._last_values:
            return dict(self._last_values)
        return self._snapshot()

    def _snapshot(self):
        return {"host": str(self.control_value(self.host, "") or "").strip(),
                "port": str(self.control_value(self.port, "") or "").strip(),
                "username": str(self.control_value(self.username, "") or "").strip(),
                "password": self.control_value(self.password, "") or "",
                "remember": bool(self.control_value(self.remember, False))}

    def submit(self):
        if self._busy:
            return
        values = self._snapshot()
        if not values["host"] or not values["username"]:
            self.set_error("Host and username are required.")
            return
        try:
            if not 1 <= int(values["port"]) <= 65535:
                raise ValueError
        except ValueError:
            self.set_error("Port must be a number from 1 to 65535.")
            return
        self.set_busy(True)
        self.set_status_text(self.error, "", error=True)
        self.submit_from_window(values)

    def submit_from_window(self, values):
        self._last_values = dict(values)
        self.view.after(0, self.callback, self, dict(values))

    def set_busy(self, busy):
        self.on_ui(self._set_busy, busy)

    def _set_busy(self, busy):
        if not self.winfo_exists():
            return
        self._busy = bool(busy)
        enabled = not self._busy
        for combo in self._combos:
            combo.setEnabled(enabled)
        for item in (self.port, self.password, self.connect_button, self.cancel_button):
            self.set_control_enabled(item, enabled)
        self._remember_widget.setEnabled(enabled)
        self.set_control_value(self.connect_button, "Connecting" if busy else "Connect")

    def set_error(self, message):
        self.on_ui(self._set_error, message)

    def _set_error(self, message):
        if self.winfo_exists():
            text = str(message or "")
            self.set_status_text(self.error, text, error=True)
            self.set_busy(False)

    def handle_command(self, command, *args, **kwargs):
        {"set_busy": self.set_busy, "set_error": self.set_error}[command](*args)

    def cancel_from_window(self):
        for combo in self._combos:
            if combo.popupVisible():
                combo.hidePopup()
                return
        if not self._busy:
            self._cancelled = True
            self.destroy()

    _close_from_escape = cancel_from_window

    def save_preferences(self):
        values = self.values()
        remember = values.pop("remember", False)
        self.preferences.save_success(values, remember)
