from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
FORMS = ROOT / "WinUx" / "dialogs" / "floating_forms.py"
ADAPTERS = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
FILE_DIALOG = ROOT / "WinUx" / "ui" / "file_dialog.py"
FLOATING = ROOT / "WinUx" / "ui" / "hosting" / "floating_dialog.py"


def test_inprocess_dialogs_are_the_default_policy():
    source = VIEW.read_text(encoding="utf-8")
    assert 'os.environ.get("WINUX_INPROCESS_DIALOGS", "1")' in source
    assert 'os.environ.get("WINUX_DIALOG_PROCESS_HOSTS", "0")' in source
    assert "def _use_inprocess_dialogs():" in source
    assert "if name in _INPROCESS_DIALOG_TYPES:" in source
    assert "if _use_inprocess_dialogs():" in source


def test_hidden_worker_is_legacy_only_not_normal_startup():
    source = VIEW.read_text(encoding="utf-8")
    assert "if not _use_inprocess_dialogs():" in source
    assert "from .dialogs.prewarm_pool import start_dialog_prewarm" in source


def test_settings_and_schedule_are_retained_modeless_native_top_levels():
    source = ADAPTERS.read_text(encoding="utf-8")
    settings = source[source.index("class SettingsDialog"):source.index("class DiagnosticsDialog")]
    schedule = source[source.index("class JobScheduleDialog"):source.index("class JobManagerDialog")]
    for block in (settings, schedule):
        assert "retain_on_close=True" in block
        assert "modal=False" in block
        assert "modal=True" not in block


def test_file_selectors_share_main_event_loop_by_default():
    view = VIEW.read_text(encoding="utf-8")
    selector = FILE_DIALOG.read_text(encoding="utf-8")
    assert "use_native_file_selectors = False" in view
    assert 'getattr(self.view, "use_native_file_selectors", False)' in selector
    assert "from ..dialogs import inprocess_adapters" in selector
    assert "inprocess_adapters.LocalFileDialog" in selector
    assert "inprocess_adapters.LocalFolderDialog" in selector


def test_floating_controller_exposes_qt_visibility_contract():
    source = FLOATING.read_text(encoding="utf-8")
    assert "def isVisible(self):" in source
    assert "def isHidden(self):" in source
    assert "def activateWindow(self):" in source
    assert "return self.show()" in source[source.index("def activateWindow(self):"):source.index("def after_first_present", source.index("def activateWindow(self):"))]
