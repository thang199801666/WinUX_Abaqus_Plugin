from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "WinUx" / "dialogs" / "transfer_center_form.py",
    ROOT / "WinUx" / "dialogs" / "settings_form.py",
    ROOT / "WinUx" / "dialogs" / "local_folder_form.py",
    ROOT / "WinUx" / "dialogs" / "inprocess" / "diagnostics.py",
    ROOT / "DearUIQt" / "ribbon" / "bar.py",
    ROOT / "DearUIQt" / "ribbon" / "internals.py",
]

FORBIDDEN = tuple(chr(value) for value in (
    0x2191, 0x2193, 0x2194, 0x21C4, 0x25CB, 0x21BB, 0x2713, 0x26A0,
    0x2715, 0x2026, 0x2014, 0x2198, 0x25BE,
))


def test_user_facing_dialog_and_ribbon_sources_avoid_fragile_unicode_symbols():
    for path in TARGETS:
        source = path.read_text(encoding="utf-8")
        for symbol in FORBIDDEN:
            assert symbol not in source, "{} still contains {!r}".format(path, symbol)


def test_transfer_center_does_not_prefix_status_or_operation_with_symbols():
    source = (ROOT / "WinUx" / "dialogs" / "transfer_center_form.py").read_text(encoding="utf-8")
    assert "def _operation_icon" not in source
    assert "def _state_icon" not in source
    assert 'return "{}: {}".format(operation, name)' in source
    assert 'dpg.set_value(row["status_text"], str(label).strip())' in source
