from pathlib import Path

from WinUx.ui.hosting.host import QDialogHostPool

ROOT = Path(__file__).resolve().parents[1]


def test_pool_preserves_two_idle_hosts_when_second_resident_window_is_leased():
    pool = object.__new__(QDialogHostPool)
    pool.capacity = 3
    pool.resident_headroom = 1
    pool._leased = set()
    assert pool._desired_idle_count(0) == 3
    assert pool._desired_idle_count(1) == 2
    assert pool._desired_idle_count(2) == 2
    assert pool._desired_idle_count(3) == 1
    assert pool._desired_idle_count(4) == 0


def test_retained_close_supports_modal_qdialog_semantics():
    controller = (ROOT / "WinUx/ui/hosting/floating_dialog.py").read_text(encoding="utf-8")
    runtime = (ROOT / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
    assert "bool(retain_on_close and not modal)" not in controller
    assert 'bool(initial.get("retain_on_close") and not initial.get("modal"))' not in runtime


def test_high_frequency_owned_dialogs_opt_into_retained_qt_lifetime():
    source = (ROOT / "WinUx/dialogs/floating_adapters.py").read_text(encoding="utf-8")
    settings = source[source.index("class SettingsDialog"):source.index("class DiagnosticsDialog")]
    schedule = source[source.index("class JobScheduleDialog"):source.index("class JobManagerDialog")]
    transfer = source[source.index("class TransferCenterDialog"):]
    assert "retain_on_close=True" in settings
    assert "retain_on_close=True" in schedule
    assert "retain_on_close=True" in transfer
