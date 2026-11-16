"""Saved paths, bookmarks and site-profile controller facade."""
from __future__ import annotations

from pathlib import Path, PurePosixPath


def _record_user_activity(controller):
    method = getattr(controller, "user_activity", None)
    if callable(method):
        return method()
    from ...app.controller import WinUXController
    return WinUXController.user_activity(controller)


class SavedNavigationMixin:
    def _bookmark_entries(self):
        entries = []
        for item in self.navigation_preferences.load_bookmarks("local"):
            entry = dict(item)
            entry["panel_id"] = "local"
            entries.append(entry)
        if self.server.connected:
            for item in self.navigation_preferences.load_bookmarks(
                    "server", host=self.server.host,
                    username=self.server.username):
                entry = dict(item)
                entry.update({
                    "panel_id": "server",
                    "host": self.server.host,
                    "username": self.server.username,
                })
                entries.append(entry)
        return entries

    @staticmethod
    def _bookmark_label(path, panel_id):
        try:
            value = (PurePosixPath(str(path)) if panel_id == "server"
                     else Path(str(path)))
            return value.name or str(value)
        except Exception:
            return str(path)

    def bookmark_command(self, action):
        _record_user_activity(self)
        action = str(action or "")
        if action == "add_local":
            panel = self.view.left
            path = panel.current_path
            self.navigation_preferences.add_bookmark(
                "local", path,
                label=self._bookmark_label(path, "local"))
            panel.status.set("Bookmarked {}".format(path))
            self._refresh_bookmarks_dialog()
            return
        if action == "add_server":
            if not self._ensure_server_online():
                return
            panel = self.view.right
            path = panel.current_path
            self.navigation_preferences.add_bookmark(
                "server", path,
                label=self._bookmark_label(path, "server"),
                host=self.server.host, username=self.server.username)
            panel.status.set("Bookmarked {}".format(path))
            self._refresh_bookmarks_dialog()
            return
        if action == "manage":
            self.view.show_bookmarks(
                self._bookmark_entries(), self._open_bookmark,
                self._remove_bookmark, self._rename_bookmark)

    def _refresh_bookmarks_dialog(self):
        dialog = getattr(self.view, "bookmarks_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(self._bookmark_entries())

    def _open_bookmark(self, entry):
        _record_user_activity(self)
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        if not path:
            return
        if panel_id == "server":
            if not self._ensure_server_online():
                return
            expected_host = str(entry.get("host") or self.server.host)
            expected_user = str(entry.get("username") or self.server.username)
            if (expected_host.casefold() != str(self.server.host).casefold() or
                    expected_user.casefold() != str(self.server.username).casefold()):
                self.view.show_message(
                    "Bookmarks",
                    "This bookmark belongs to {}@{}. Connect to that site first.".format(
                        expected_user, expected_host))
                return
            self.open_path(self.view.right, self.server.normalize(path))
        else:
            self.open_path(self.view.left, Path(path))

    def _remove_bookmark(self, entry):
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        self.navigation_preferences.remove_bookmark(
            panel_id, path,
            host=entry.get("host") or self.server.host,
            username=entry.get("username") or self.server.username)
        self._refresh_bookmarks_dialog()

    def _rename_bookmark(self, entry, label):
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        self.navigation_preferences.rename_bookmark(
            panel_id, path, label,
            host=entry.get("host") or self.server.host,
            username=entry.get("username") or self.server.username)
        self._refresh_bookmarks_dialog()

    def site_manager(self):
        self.view.show_site_manager(
            self.site_preferences.load(), self._save_site_profile,
            self._delete_site_profile, self._connect_site_profile)

    def _refresh_site_manager(self, selected_id=None):
        dialog = getattr(self.view, "site_manager_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(self.site_preferences.load(), selected_id)

    def _save_site_profile(self, values):
        _record_user_activity(self)
        dialog = getattr(self.view, "site_manager_dialog", None)
        try:
            saved = self.site_preferences.save_site(values)
        except (OSError, ValueError) as exc:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(str(exc))
            return
        self._refresh_site_manager(saved.get("id"))

    def _delete_site_profile(self, site):
        _record_user_activity(self)
        site_id = str(site.get("id") or "")
        if not site_id:
            return

        def complete(confirmed):
            if not confirmed:
                return
            self.site_preferences.delete(site_id)
            self._refresh_site_manager()

        self.view.confirm_action_async(
            "Delete Site?",
            "Delete the saved site profile '{}'?\n\nStored passwords are managed separately and will not be deleted.".format(
                site.get("name") or site.get("host") or "Site"),
            complete,
            primary_text="Delete", secondary_text="Cancel", intent="danger")

    def _connect_site_profile(self, values):
        _record_user_activity(self)
        dialog = getattr(self.view, "site_manager_dialog", None)
        try:
            saved = self.site_preferences.save_site(values)
        except (OSError, ValueError) as exc:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(str(exc))
            return
        username = str(saved.get("username") or "")
        from ...preferences.login import LoginPreferences
        password = LoginPreferences().password_for(username) if username else ""
        if not username or not password:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(
                    "This site has no saved username/password. Use Log-In once and "
                    "enable 'Remember password', then connect from Site Manager.")
            return
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        self.login(None, {
            "host": saved["host"],
            "port": saved["port"],
            "username": username,
            "password": password,
            "remember": True,
            "remote_path": saved.get("remote_path") or "",
        })
