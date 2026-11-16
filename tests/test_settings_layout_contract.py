"""Static layout contract for the Settings dialog.

Portable regression that can run without a DearPyGui display.  The real-window
coverage remains in test_settings_layout.py for Abaqus/Windows.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / 'WinUx' / 'dialogs' / 'settings' / 'settings_form.py'
COLORS = ROOT / 'WinUx' / 'dialogs' / 'settings' / 'settings_file_colors.py'
DIALOG = ROOT / 'DearUIQt' / 'dialogs' / 'qt_dialog.py'


def _method(path, class_name, method_name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return item
    raise AssertionError(f'{class_name}.{method_name} not found in {path}')


def test_layout_contract():
    qt_form = _method(DIALOG, 'QtDialog', 'form_layout')
    assert any(arg.arg == 'editor_width' for arg in qt_form.args.kwonlyargs), (
        'QFormLayout helper must support a preferred editor column width')

    form_source = FORM.read_text(encoding='utf-8')
    colors_source = COLORS.read_text(encoding='utf-8')

    assert 'NAV_WIDTH = DialogMetrics.NAV_WIDTH' in form_source
    assert 'FORM_LABEL_WIDTH = DialogMetrics.LABEL_WIDTH' in form_source
    assert 'FORM_EDITOR_WIDTH = 270' in form_source
    assert 'WIDE_EDITOR_WIDTH = 330' in form_source
    assert 'NUMERIC_EDITOR_WIDTH = 190' in form_source

    for builder in (
        '_build_general_page', '_build_updates_page', '_build_performance_page',
        '_build_abaqus_page', '_build_account_page',
    ):
        node = _method(FORM, 'SettingsDialog', builder)
        text = ast.get_source_segment(form_source, node) or ''
        assert 'self.header(' in text, f'{builder} must keep the shared page header'
        assert 'self.section(' in text, f'{builder} must use shared Settings sections'

    performance = ast.get_source_segment(
        form_source, _method(FORM, 'SettingsDialog', '_build_performance_page')) or ''
    assert performance.count('editor_width=self.NUMERIC_EDITOR_WIDTH') >= 3

    abaqus = ast.get_source_segment(
        form_source, _method(FORM, 'SettingsDialog', '_build_abaqus_page')) or ''
    assert abaqus.count('editor_width=self.WIDE_EDITOR_WIDTH') >= 2

    account = ast.get_source_segment(
        form_source, _method(FORM, 'SettingsDialog', '_build_account_page')) or ''
    for attr in ('login_host_value', 'login_username_value', 'login_password_value'):
        assert attr in account

    assert "with self.section('Rules'" in colors_source
    assert "with self.section('Selected rule'" in colors_source
    assert "editor_width=getattr(self, 'WIDE_EDITOR_WIDTH', 330)" in colors_source
    assert "('Move Up', 'up'), ('Move Down', 'down')" in colors_source

    print('PASS: Settings pages share compact Qt form widths, sections and aligned account/version layouts')


if __name__ == '__main__':
    test_layout_contract()
