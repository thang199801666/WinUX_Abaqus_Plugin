import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt.qt.core import QEvent
from tests.test_ssh_console_menu_actions import load_methods

ROOT = Path(__file__).resolve().parents[1]
DOCKING_SOURCE = ROOT / 'WinUx' / 'ui' / 'behaviors' / 'console_docking.py'


def _load_docking_method(name, **namespace):
    tree = ast.parse(DOCKING_SOURCE.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'ConsoleDockingMixin')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(DOCKING_SOURCE), 'exec'), namespace)
    return namespace[name]


def test_docked_console_consumes_application_key_events_while_keyboard_owner():
    methods = load_methods('ConsoleDockPanel', ['event'], QEvent=QEvent, QObject=Mock())
    panel = SimpleNamespace(keyboard_active=lambda: True)
    for event_type in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
        assert methods['event'](panel, QEvent(event_type)) is True


def test_console_keyboard_ownership_becomes_qapplication_focus_object():
    application = Mock()
    QApplication = SimpleNamespace(instance=lambda: application)
    method = _load_docking_method('_set_console_keyboard_active', QApplication=QApplication)

    panel = SimpleNamespace()
    view = SimpleNamespace(
        _console_dock_visible=True,
        _console_dock_mode='docked',
        _console_keyboard_panel=None,
        console_panel=panel,
    )

    method(view, True, panel)
    assert view._console_keyboard_panel is panel
    application.setFocusObject.assert_called_once_with(panel)

    method(view, False, panel)
    assert view._console_keyboard_panel is None
    application.clearFocusObject.assert_called_once_with(panel)


def test_console_source_documents_enter_exclusivity_against_explorer():
    console = (ROOT / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    docking = DOCKING_SOURCE.read_text(encoding='utf-8')
    assert 'physical Enter cannot bubble into a previously focused Explorer view.' in console
    assert 'application.setFocusObject(target)' in docking
    assert 'application.clearFocusObject(previous)' in docking
