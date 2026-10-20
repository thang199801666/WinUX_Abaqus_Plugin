from pathlib import Path

from WinUx.ui.hosting.inprocess_dialog import (
    RetainedInProcessDialogMixin,
    close_inprocess_dialogs,
)

ROOT = Path(__file__).resolve().parents[1]


class _View:
    def __init__(self):
        self._inprocess_dialogs = set()
        self.calls = []

    def after(self, delay, callback, *args):
        self.calls.append((delay, callback, args))
        return len(self.calls)


class _Base:
    def __init__(self):
        self.hidden = 0
        self.destroyed = 0
        self.exists = True

    def winfo_exists(self):
        return self.exists

    def hide(self):
        self.hidden += 1
        return True

    def destroy(self):
        self.destroyed += 1
        self.exists = False


class _Dialog(RetainedInProcessDialogMixin, _Base):
    def __init__(self, view):
        _Base.__init__(self)
        self._init_inprocess_lifetime(view)


def test_retained_inprocess_close_is_constant_time_hide():
    view = _View()
    dialog = _Dialog(view)
    assert dialog in view._inprocess_dialogs
    assert dialog.destroy() is True
    assert dialog.hidden == 1
    assert dialog.destroyed == 0
    assert dialog.winfo_exists()


def test_application_shutdown_terminally_deletes_retained_dialogs():
    view = _View()
    first = _Dialog(view)
    second = _Dialog(view)
    close_inprocess_dialogs(view)
    assert first.destroyed == second.destroyed == 1
    assert not first.winfo_exists() and not second.winfo_exists()
    assert not view._inprocess_dialogs


def test_main_view_routes_application_dialogs_inprocess_by_default():
    source = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    routed = source[source.index("_INPROCESS_DIALOG_TYPES"):source.index("def _dialog_type")]
    for name in (
        "BlockingDialog", "LoginDialog", "JobEditDialog", "JobManagerDialog",
        "LocalFolderDialog", "ServerPathDialog", "ODBCheckDialog",
        "ODBExtractDialog", "ODBXYResultDialog", "SettingsDialog",
        "DiagnosticsDialog", "BookmarksDialog", "SiteManagerDialog",
        "SyncPreviewDialog", "JobScheduleDialog", "TransferCenterDialog",
    ):
        assert '"{}"'.format(name) in routed
    assert 'os.environ.get("WINUX_INPROCESS_DIALOGS", "1")' in source
    assert 'os.environ.get("WINUX_DIALOG_PROCESS_HOSTS", "0")' in source
    assert "from .dialogs import inprocess_adapters" in source


def test_public_dialog_api_uses_shared_event_loop_and_legacy_is_explicit():
    expected = {
        "settings_dialog.py": "from .inprocess_adapters import SettingsDialog",
        "job_schedule_dialog.py": "from .inprocess_adapters import JobScheduleDialog",
        "transfer_center_dialog.py": "from .inprocess_adapters import TransferCenterDialog",
        "login_dialog.py": "from .inprocess_adapters import LoginDialog",
    }
    for filename, token in expected.items():
        source = (ROOT / "WinUx/dialogs" / filename).read_text(encoding="utf-8")
        assert token in source
    view = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    assert "from .dialogs import floating_adapters" in view
    assert "Explicit compatibility mode only" in view


def test_job_schedule_timer_sleeps_while_hidden():
    source = (ROOT / "WinUx/dialogs/job_schedule_form.py").read_text(encoding="utf-8")
    assert "def showEvent(self, event):" in source
    assert "timer.start(1000)" in source
    assert "def hideEvent(self, event):" in source
    assert "timer.stop()" in source


def test_qdialog_close_defaults_to_hide_not_destroy():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    section = source[source.index("    def close(self):"):source.index("    def delete(self):")]
    assert "self.hide()" in section
    assert "WA_DeleteOnClose" in section
    assert "self.reject()" not in section


def test_inprocess_facade_is_lazy_and_does_not_import_forms():
    import importlib, sys
    module = importlib.import_module("WinUx.dialogs.inprocess_adapters")
    assert module is not None
    assert "WinUx.dialogs.settings_form" not in sys.modules
    assert "WinUx.dialogs.bookmarks_form" not in sys.modules
    assert "WinUx.dialogs.transfer_center_form" not in sys.modules



def test_process_prewarm_is_not_started_on_normal_main_view_path():
    source = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    assert "if not _use_inprocess_dialogs():" in source
    assert "from .dialogs.prewarm_pool import start_dialog_prewarm" in source
    assert "start_dialog_prewarm(self)" in source
