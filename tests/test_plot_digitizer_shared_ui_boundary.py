from pathlib import Path


def _root():
    return Path(__file__).resolve().parents[1]


def test_plot_digitizer_ui_uses_canonical_ui_facade():
    text = (_root() / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py').read_text(encoding='utf-8')
    assert 'from ...ui import' in text
    assert 'shared_ui' not in text
    assert 'ui_framework' not in text
    assert 'WinUx.widgets' not in text


def test_plot_digitizer_core_and_application_do_not_import_ui():
    for folder in ('core', 'application'):
        for path in (_root() / 'WinUx' / 'plotdigitizer' / folder).glob('*.py'):
            text = path.read_text(encoding='utf-8')
            imports = [line.strip().lower() for line in text.splitlines()
                       if line.lstrip().startswith(('import ', 'from '))]
            assert not any('winux.ui' in line or 'dearpygui' in line for line in imports)


def test_legacy_plot_digitizer_window_import_remains_compatible():
    text = (_root() / 'WinUx' / 'plotdigitizer' / 'integration' / 'winux.py').read_text(encoding='utf-8')
    assert 'PlotDigitizerWindow = StandalonePlotDigitizerController' in text
