from __future__ import annotations

from datetime import datetime, timezone

from DearUIQt.backends import dpg
from DearUIQt.core import Qt
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.layouts import QVBoxLayout
from DearUIQt.modelview import QTableWidget, QTableWidgetItem

from ..app.session_metrics import format_bytes


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_opened(value):
    stamp = _parse_time(value)
    if stamp is None:
        return "N/A"
    try:
        return stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value or "N/A")


def _format_duration(value, now=None):
    stamp = _parse_time(value)
    if stamp is None:
        return "N/A"
    now = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - stamp.astimezone(timezone.utc)).total_seconds()))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return "{}:{:02d}:{:02d}".format(hours, minutes, seconds)
    return "{:02d}:{:02d}".format(minutes, seconds)


class SessionManagerDialog(QtDialog):
    REUSABLE_HOST = True
    REFRESH_MS = 1000

    def __init__(self, view, snapshot_provider, on_activate=None, on_close=None):
        self._snapshot_provider = snapshot_provider
        self._on_activate = on_activate
        self._on_close = on_close
        self._row_session_ids = []
        super().__init__(view, "Session Manager", 900, 350, modal=False)
        self.setMinimumSize(760, 300)
        layout = QVBoxLayout(parent=self.content, spacing=8)
        self.setLayout(layout)
        self.header(
            "Session Manager",
            "Manage login sessions, runtime state, and resource usage.",
            parent=layout.tag,
        )
        self.table_widget = self.own_widget(QTableWidget(
            0, 7, parent=self._qt_parent(layout.tag), after=view.after, backend=dpg,
            header_row=True, scroll_y=True, height=190, width=-1, resizable=True,
            row_background=True, freeze_rows=1, grid_lines=True,
            sizing_policy=dpg.mvTable_SizingStretchProp,
        ))
        self.table = self.table_widget.tag
        self.table_widget.setHorizontalHeaderLabels((
            "Session", "State", "Opened", "Uptime", "Session RAM*", "Transport", "Tasks",
        ))
        for column, width in enumerate((250, 92, 164, 86, 112, 108, 72)):
            self.table_widget.setColumnWidth(column, width)
        self.table_widget.cellDoubleClicked.connect(lambda row, _column: self._activate_row(row))
        # Keep runtime summary on its own line. Putting it inside QDialogButtonBox
        # squeezed the action buttons and made the footer look crowded.
        self.status = self.status_text(parent=layout.tag)
        self.button_box(
            [("Close", self.destroy, "primary", True)],
            left_actions=[
                ("Activate", self.activate_selected, "secondary", False),
                ("Close Session", self.close_selected, "secondary", False),
                ("Refresh", self.refresh, "secondary", False),
            ],
        )
        self._refresh_timer = self.create_timer(self.REFRESH_MS, self.refresh)
        self.refresh()

    @staticmethod
    def _readonly_item(text):
        item = QTableWidgetItem(str(text))
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        return item

    def _selected_session_id(self):
        row = int(self.table_widget.currentRow())
        if 0 <= row < len(self._row_session_ids):
            return self._row_session_ids[row]
        return None

    def _activate_row(self, row):
        row = int(row)
        if not (0 <= row < len(self._row_session_ids)):
            return False
        sid = self._row_session_ids[row]
        if callable(self._on_activate):
            return bool(self._on_activate(sid))
        return False

    def activate_selected(self):
        sid = self._selected_session_id()
        if sid is None:
            self.set_control_value(self.status, "Select a session first")
            return False
        result = bool(self._on_activate(sid)) if callable(self._on_activate) else False
        self.refresh()
        return result

    def close_selected(self):
        sid = self._selected_session_id()
        if sid is None:
            self.set_control_value(self.status, "Select a session first")
            return False
        if callable(self._on_close):
            self._on_close(sid)
            return True
        return False

    def refresh(self, *_args):
        if not self.winfo_exists():
            return False
        try:
            snapshot = self._snapshot_provider() or {}
        except Exception as exc:
            self.set_control_value(self.status, "Could not read sessions: {}".format(exc))
            return False

        sessions = list(snapshot.get("sessions") or ())
        active_id = str(snapshot.get("active_session_id") or "")
        old_sid = self._selected_session_id()
        self.table_widget.setRowCount(len(sessions))
        self._row_session_ids = []
        now = datetime.now(timezone.utc)
        selected_row = -1
        for row, data in enumerate(sessions):
            sid = str(data.get("session_id") or "")
            self._row_session_ids.append(sid)
            if sid == old_sid:
                selected_row = row
            account = data.get("account_label") or sid[:8] or "Unknown"
            state = str(data.get("state") or "unknown").title()
            if sid == active_id:
                state = "ACTIVE"
            opened_at = data.get("connected_at") or data.get("created_at")
            tasks = data.get("tasks") or {}
            task_count = sum(int(tasks.get(key) or 0) for key in ("background", "transfer", "analysis"))
            values = (
                account,
                state,
                _format_opened(opened_at),
                _format_duration(opened_at, now),
                format_bytes(data.get("ram_estimate_bytes") or 0),
                "Connected" if data.get("transport_connected") else "Disconnected",
                str(task_count),
            )
            for column, value in enumerate(values):
                self.table_widget.setItem(row, column, self._readonly_item(value))
        if selected_row >= 0:
            self.table_widget.setCurrentCell(selected_row, 0)
        elif sessions:
            # On first open, select the active session rather than leaving an
            # apparently empty selection in a management dialog.
            active_row = next((index for index, item in enumerate(sessions)
                               if str(item.get("session_id") or "") == active_id), 0)
            self.table_widget.setCurrentCell(active_row, 0)

        # Fit the dialog to the actual number of sessions. Large session sets
        # still scroll, while the common 1-3 session case no longer leaves a
        # large empty white table surface.
        visible_rows = max(1, min(8, len(sessions)))
        table_height = 54 + visible_rows * 30
        try:
            dpg.configure_item(self.table, height=table_height)
        except Exception:
            pass
        target_height = max(300, min(570, 180 + table_height))
        if int(getattr(self, "height", target_height) or 0) != target_height:
            self.height = target_height
            try:
                self.resize(self.width, target_height)
            except Exception:
                pass

        process_ram = format_bytes(snapshot.get("process_ram_bytes") or 0)
        estimated_total = sum(int(item.get("ram_estimate_bytes") or 0) for item in sessions)
        self.set_control_value(
            self.status,
            "{} session{}   •   Session RAM*: {}   •   WinUx process RAM: {}".format(
                len(sessions), "" if len(sessions) == 1 else "s",
                format_bytes(estimated_total), process_ram),
        )
        return True


__all__ = ["SessionManagerDialog"]
