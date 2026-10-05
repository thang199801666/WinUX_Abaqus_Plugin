from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog


class SiteManagerDialog(QtDialog):
    def __init__(self, view, sites, on_save, on_delete, on_connect):
        self._sites = []
        self._selected_id = None
        self._on_save, self._on_delete, self._on_connect = on_save, on_delete, on_connect
        super().__init__(view, "Site Manager", 700, 420, modal=False)
        self.preferred_size = (670, 380)
        self.header("Saved sites", "Manage reusable SSH connection profiles.")
        self.site_list = self.labeled_widget(
            "Saved sites",
            lambda: self.combo([], callback=self._selection_changed),
        )
        with self.section("Site details") as details:
            form = self.form_layout(parent=details)
            self.fields = {}
            for name, label in (
                    ("name", "Site name"), ("host", "Host"), ("port", "Port"),
                    ("username", "Username"), ("remote_path", "Initial remote folder")):
                initial = "22" if name == "port" else ""
                self.fields[name] = self.form_layout_row(
                    form, label,
                    lambda parent, value=initial: self.line_edit(value, parent=parent),
                )
        self.note("Passwords use the DPAPI-protected credentials for the selected username.",
                  wrap=650)
        self.error = self.status_text(error=True)
        self.button_box([("Connect", self._connect, "primary", True),
                         ("Close", self.destroy, "secondary", False)],
            left_actions=[("New", self._new, "secondary", False),
                          ("Save", self._save, "secondary", False),
                          ("Delete", self._delete, "danger", False)])
        self.refresh(sites)

    def refresh(self, sites, selected_id=None):
        self._sites = [dict(site) for site in sites or []]
        selected_id = self._selected_id if selected_id is None else selected_id
        # Include an index so identically named profiles remain distinct.
        self._labels = ["{}: {}".format(i+1, site.get("name") or site.get("host") or "Site")
                        for i, site in enumerate(self._sites)]
        dpg.configure_item(self.site_list, items=self._labels)
        index = next((i for i, site in enumerate(self._sites) if str(site.get("id")) == str(selected_id)), 0)
        if self._sites:
            dpg.set_value(self.site_list, self._labels[index])
            self._load_site(self._sites[index])
        else:
            self._new()

    def _selection_changed(self, sender, value):
        if value in self._labels:
            self._load_site(self._sites[self._labels.index(value)])

    def _load_site(self, site):
        self._selected_id = str(site.get("id") or "") or None
        for name, item in self.fields.items():
            dpg.set_value(item, str(site.get(name) or (22 if name == "port" else "")))
        self.set_status_text(self.error, "", error=True)

    def _new(self):
        self._load_site({})
        dpg.set_value(self.site_list, "")
        dpg.focus_item(self.fields["name"])

    def _snapshot(self):
        values = {name: dpg.get_value(item).strip() for name, item in self.fields.items()}
        values["id"] = self._selected_id
        try:
            values["port"] = int(values["port"])
        except ValueError:
            values["port"] = 0
        return values

    def _validate(self):
        values = self._snapshot()
        error = "Host is required." if not values["host"] else (
            "Port must be a number from 1 to 65535." if not 1 <= values["port"] <= 65535 else "")
        self.show_error(error)
        return None if error else values

    def show_error(self, message):
        self.set_status_text(self.error, message, error=True)

    def request_save(self, values):
        self.view.after(0, self._on_save, dict(values))

    def request_delete(self, site):
        self.view.after(0, self._on_delete, dict(site))

    def request_connect(self, values):
        self.view.after(0, self._on_connect, dict(values))

    def _save(self):
        values = self._validate()
        if values:
            self.request_save(values)

    def _delete(self):
        site = next((site for site in self._sites if str(site.get("id")) == self._selected_id), None)
        if site:
            self.request_delete(site)

    def _connect(self):
        values = self._validate()
        if values:
            self.request_connect(values)

    def handle_command(self, command, *args):
        if command == "refresh":
            self.refresh(*args)
        elif command == "error":
            self.show_error(*args)
