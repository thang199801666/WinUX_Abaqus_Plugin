"""Behavior tests for UI-neutral dialog logic extracted during Phase 2."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import itertools
import threading
import unittest

from WinUx.dialogs.logic.job_schedule import JobEditScheduleLogic
from WinUx.dialogs.logic.job_manager import JobManagerLogic
from WinUx.dialogs.logic.odb import (
    format_bytes, format_check_number, history_item_label,
)
from WinUx.dialogs.logic.transfer import TransferCenterLogic


ROOT = Path(__file__).resolve().parents[1]


class JobScheduleLogicTests(unittest.TestCase):
    def test_delete_after_and_legacy_delete_at_contracts_are_preserved(self):
        self.assertEqual(
            JobEditScheduleLogic._parse_delete_after("01:02:03"),
            timedelta(hours=1, minutes=2, seconds=3),
        )
        parsed = JobEditScheduleLogic._parse_delete_at("12:30:00 10-03-2026")
        self.assertEqual(parsed, datetime(2026, 10, 3, 12, 30, 0))

    def test_job_run_at_live_mode_stays_in_future(self):
        now = datetime(2026, 10, 3, 8, 0, 0)
        self.assertEqual(
            JobManagerLogic._resolve_run_at_clock("", now=now, live=True),
            now + timedelta(seconds=1),
        )


class _View:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback, *args):
        self.callbacks.append((delay, callback, args))


class _TransferCenter(TransferCenterLogic):
    def __init__(self):
        self.view = _View()
        self.tasks = []
        self._active_batch_failed = False
        self._row_ids = itertools.count(1)
        self._row_to_task = {}
        self._row_update_lock = threading.Lock()
        self._pending_row_updates = {}
        self._row_update_scheduled = False
        self.commands = []
        self.visible = False

    def winfo_exists(self):
        return True

    def post(self, command, *args, **kwargs):
        self.commands.append((command, args, kwargs))
        return True

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class TransferLogicTests(unittest.TestCase):
    def test_progress_updates_are_coalesced_per_row(self):
        center = _TransferCenter()
        center.update_row(7, ratio=.1)
        center.update_row(7, status="Running")
        self.assertEqual(len(center.commands), 1)
        self.assertEqual(center.commands[0][0], "flush_row_updates")
        self.assertEqual(
            center._take_pending_row_updates(),
            [(7, {"ratio": .1, "status": "Running"})],
        )

    def test_task_creation_preserves_deduplication_and_visibility(self):
        center = _TransferCenter()
        cancel = threading.Event()
        task = center.add_task("Upload", cancel, ["a.inp", "a.inp", "b.inp"])
        self.assertEqual(task.items, ["a.inp", "b.inp"])
        self.assertEqual(len(task.rows), 2)
        self.assertTrue(center.visible)


class OdbDisplayLogicTests(unittest.TestCase):
    def test_odb_helpers_preserve_existing_display_contract(self):
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_check_number(None), "-")
        self.assertEqual(history_item_label({"displayName": "RF1 at Node 1", "output": "RF1"}),
                         "RF1 at Node 1")


class DialogArchitectureTests(unittest.TestCase):
    def test_active_dialog_stack_does_not_import_legacy_dialog_modules(self):
        for relative in (
            "WinUx/dialogs/floating_adapters.py",
            "WinUx/dialogs/job_edit_form.py",
            "WinUx/dialogs/job_manager_form.py",
            "WinUx/dialogs/transfer_center_form.py",
            "WinUx/dialogs/odb_check_form.py",
            "WinUx/dialogs/odb_extract_form.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("legacy_", source, relative)

    def test_obsolete_legacy_dialog_files_are_removed(self):
        dialog_dir = ROOT / "WinUx" / "dialogs"
        self.assertFalse(list(dialog_dir.glob("legacy_*_dialog.py")))


if __name__ == "__main__":
    unittest.main()
