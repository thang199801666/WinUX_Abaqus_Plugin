"""Application menu construction and retained connection-status presentation."""
from __future__ import annotations

import os

from DearUIQt.gui import QAction
from DearUIQt.layouts import QHBoxLayout
from DearUIQt.widgets import QImageView, QMenuBar, QRetainedItem, QSpacer, QToolButton

from ...components import ResourceTextures
from ....platform.resources import resource_path


class ApplicationMenuMixin:
    def _build_menu(self):
        """Build the application QMenuBar using DearUIQt popup ownership.

        Dear PyGui's native ``dpg.menu`` popup is visually correct, but it is
        invisible to DearUIQt's application pointer grab. Explorer and splitter
        code intentionally perform geometry-based/global pointer polling, so a
        native menu can appear above them while they still react to the same
        mouse position.  A retained QMenuBar/QMenu stack gives the menu Qt-like
        popup semantics: while a menu is open the application body is logically
        pointer-blocked by QApplication/input_gate without a visual overlay.
        """
        menu_bar = getattr(self, "_menu_bar_wrapper", None)
        if menu_bar is None:
            menu_bar = QMenuBar(
                parent=getattr(self, "_main_window", None), height=20)
            self._menu_bar_wrapper = menu_bar

        def action(label, icon_name, callback, *, checkable=False, checked=False):
            item = QAction(
                label, menu_bar, checkable=bool(checkable), checked=bool(checked))
            texture = ResourceTextures.get(icon_name) if icon_name else None
            if texture:
                item.setIcon(texture)
            if checkable:
                item.toggled.connect(
                    lambda value, cb=callback: cb(bool(value)))
            else:
                item.triggered.connect(
                    lambda _checked=False, cb=callback: cb())
            return item

        separator = lambda key: {
            "id": "separator_{}".format(key), "label": "---",
            "separator": True, "action": "separator_{}".format(key),
        }

        menu_bar.addMenu("File", [
            action("Log-In...", "Login", self.show_login),
            action("Site Manager...", "SiteManager",
                   lambda: self.callbacks["site_manager"]()),
            action("Settings...", "Settings", self.show_settings),
            separator("file_1"),
            action("Exit", "Exit", self._request_close),
        ])

        menu_bar.addMenu("Bookmarks", [
            action("Add Local Folder", "Folder",
                   lambda: self.callbacks["bookmark_command"]("add_local")),
            action("Add Server Folder", "Folder",
                   lambda: self.callbacks["bookmark_command"]("add_server")),
            separator("bookmarks_1"),
            action("Manage Bookmarks...", "Bookmarks",
                   lambda: self.callbacks["bookmark_command"]("manage")),
        ])

        menu_bar.addMenu("Commands", [
            action("Synchronize Preview...", "Refresh",
                   lambda: self.callbacks["sync_preview"]()),
        ])

        menu_bar.addMenu("Reference", [
            action("Chart...", "ReferenceChart", self._show_reference_chart_dialog),
            action("Plot Digitizer...", "PlotDigitizer",
                   self._show_plot_digitizer_dialog),
        ])

        # QDockWidget owns its persistent toggleViewAction(). Reuse that exact
        # QAction in View instead of mirroring dock visibility in a second
        # action, matching QMainWindow/QDockWidget ownership semantics.
        console_action = self.console_dock.toggleViewAction()
        console_action.setText("Console")
        console_texture = ResourceTextures.get("Terminal")
        if console_texture:
            console_action.setIcon(console_texture)
        self.console_menu_item = console_action

        # Job Plots are created lazily for the selected Job, so unlike Console
        # there is no persistent QDockWidget instance whose toggleViewAction()
        # can be installed here at startup. Keep one application-level QAction
        # that always remains available: with no live Plot it controls the empty
        # Plot dock region, and once a Plot exists it controls that live dock.
        plots_action = action(
            "Plots", "ReferenceChart", self.set_plots_visible,
            checkable=True, checked=bool(getattr(self, "_plot_dock_visible", False)))
        self.plots_menu_item = plots_action

        menu_bar.addMenu("View", [
            console_action,
            plots_action,
            action("Transfer Center", "TransferCenter", self.show_transfer_center),
            separator("view_1"),
            action("Compact Job Monitor", "CompactMonitor", self.collapse_to_job_monitor),
            action("Job Schedule", "JobSchedule", self.show_job_schedule),
        ])

        menu_bar.addMenu("Help", [
            action("Manual", "Question", self.show_manual),
            action("Diagnostics...", "Diagnostics", self.show_diagnostics),
            separator("help_1"),
            action("About Winux", "Information", self.show_about),
        ])
        return menu_bar.tag

    @staticmethod
    def _add_icon_menu_item(parent, label, icon_name, callback):
        """Add one fixed-width menu command with a context-menu-sized icon."""
        row = QHBoxLayout(parent=parent, spacing=7)
        texture = ResourceTextures.get(icon_name)
        if texture:
            QImageView(texture, parent=row, width=18, height=18)
        else:
            QSpacer(width=18, height=18, parent=row)
        button = QToolButton(
            label, parent=row, width=188, height=23, auto_raise=True)
        button.clicked.connect(
            lambda: callback() if callable(callback) else None)
        return button.tag

    @staticmethod
    def _add_icon_toggle_menu_item(parent, label, icon_name, checked, callback):
        row = QHBoxLayout(parent=parent, spacing=7)
        texture = ResourceTextures.get(icon_name)
        if texture:
            QImageView(texture, parent=row, width=18, height=18)
        else:
            QSpacer(width=18, height=18, parent=row)
        button = QToolButton(
            label, parent=row, width=188, height=23, auto_raise=True)
        button.setCheckable(True)
        button.setChecked(bool(checked))
        button.toggled.connect(
            lambda value: callback(bool(value)) if callable(callback) else None)
        return button.tag

    @staticmethod
    def _run_icon_toggle_menu_item(sender=None, app_data=None, user_data=None):
        if callable(user_data):
            user_data(bool(app_data))

    @staticmethod
    def _run_icon_menu_item(sender=None, app_data=None, user_data=None):
        # Legacy retained commands may preserve a selected value after a popup
        # closes. Keep the reset behind DearUIQt rather than the renderer API.
        if sender is not None:
            try:
                QRetainedItem(sender).setValue(False)
            except Exception:
                pass
        if callable(user_data):
            user_data()

    def show_manual(self):
        manual = resource_path("WinUx_User_Manual_EN.pdf")
        if not manual.is_file():
            self.show_error("WinUx Manual", "Manual file was not found:\n{}".format(manual))
            return
        try:
            os.startfile(str(manual))
        except (AttributeError, OSError) as exc:
            self.show_error("WinUx Manual", "Could not open the manual:\n{}".format(exc))

    def show_about(self):
        self.show_message(
            "About Winux",
            "Winux - Abaqus Workspace\n\nSSH file transfer, job management, "
            "and Abaqus workflow tools.",
        )

    def _queue_server_connection_alignment(self, *_args):
        if self._server_connection_alignment_pending:
            return
        self._server_connection_alignment_pending = True
        self.after_render(self._align_server_connection_indicator)

    def _align_server_connection_indicator(self):
        self._server_connection_alignment_pending = False
        canvas = QRetainedItem(self._server_connection_canvas.tag).nativeState()
        text = QRetainedItem(self._right_items_label.tag).nativeState()
        if not (canvas.get('rect_min') and text.get('rect_min') and text.get('rect_size')):
            return
        # ImGui's text baseline adds padding relative to the preceding drawlist.
        # Align to rendered text bounds instead of assuming both start at y=0.
        # A one-pixel optical offset balances the dot with the visible glyphs
        # rather than the font line box's extra leading/descent space.
        center = (6, text['rect_min'][1] + text['rect_size'][1] / 2 - canvas['rect_min'][1] + 1)
        if center != self._server_connection_dot_center:
            QRetainedItem(self._server_connection_dot).setImmediateUpdates(True).configure(center=center)
            self._server_connection_dot_center = center

    def show_server_disconnected(self):
        self.set_server_connection_state(False)
        self.right.set_disconnected()

    def set_server_connection_state(self, connected):
        """Update the retained SSH status dot only when its state changes."""
        connected = bool(connected)
        if connected == self._server_connection_state:
            return
        color = (35, 160, 75, 255) if connected else (210, 55, 55, 255)
        border = (25, 125, 55, 255) if connected else (190, 45, 45, 255)
        QRetainedItem(self._server_connection_dot).setImmediateUpdates(True).configure(
            color=border, fill=color)
        self._server_connection_state = connected


__all__ = ["ApplicationMenuMixin"]
