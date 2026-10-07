from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / 'WinUx' / 'dialogs' / 'local_folder_form.py'
ADDRESS = ROOT / 'WinUx' / 'dialogs' / 'folder_browser_address.py'
FLOATING = ROOT / 'WinUx' / 'dialogs' / 'floating_dialog.py'
PROCESS = ROOT / 'WinUx' / 'services' / 'floating_dialog_process.py'
RUNTIME = ROOT / 'WinUx' / 'dialogs' / 'floating_runtime.py'


def test_folder_list_keeps_known_stable_outer_scroll_architecture():
    source = FORM.read_text(encoding='utf-8')
    assert 'scrollY=True' not in source
    assert 'resizable=self.details_mode' not in source
    assert 'browser_details_theme()' in source


def test_address_bar_uses_known_stable_line_edit_wrapper():
    source = ADDRESS.read_text(encoding='utf-8')
    assert 'self.editor = dialog.line_edit(' in source
    assert '_bind_editor_focus' not in source


def test_child_error_sends_full_traceback_and_stage():
    source = PROCESS.read_text(encoding='utf-8')
    assert 'trace_text = traceback.format_exc()' in source
    assert '"traceback": trace_text' in source
    assert '"stage": str(getattr' in source


def test_parent_guarantees_real_log_and_shows_trace_tail():
    source = FLOATING.read_text(encoding='utf-8')
    assert 'def floating_dialog_log_path' in source
    assert 'path.touch(exist_ok=True)' in source
    assert 'def _append_failure_log' in source
    assert 'Traceback (last lines):' in source
    assert 'Log could not be written.' in source


def test_runtime_reports_startup_stage():
    source = RUNTIME.read_text(encoding='utf-8')
    assert 'self.stage = "create-form:{}"' in source
    assert 'self.stage = "settle-layout"' in source
    assert 'self.stage = "ready-layout-diagnostics"' in source
