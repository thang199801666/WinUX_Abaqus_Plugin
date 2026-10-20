from pathlib import Path
import re
import sys
from unittest.mock import patch

import DearUIQt

ROOT = Path(__file__).resolve().parents[1]


def test_public_gui_library_namespaces_and_version():
    assert tuple(map(int, DearUIQt.__version__.split('.'))) >= (1, 13, 0)
    for package in ('core', 'gui', 'widgets', 'layouts', 'modelview', 'backends', 'themes'):
        assert (ROOT / 'DearUIQt' / package / '__init__.py').is_file(), package
    readme = (ROOT / 'DearUIQt' / 'README.md').read_text(encoding='utf-8')
    assert 'DearUIQt.core' in readme
    assert 'DearUIQt.backends' in readme
    assert 'must not import WinUx' in readme


def test_public_namespaces_resolve_without_eager_dearpygui_import():
    # The test process may have imported DPG through another test, so use a
    # clean interpreter-shaped module snapshot by evicting only for this check.
    before = {name for name in sys.modules if name.startswith('dearpygui')}
    from DearUIQt.core import QObject, QTimer
    from DearUIQt.widgets import QPushButton, QSlider
    from DearUIQt.layouts import QSplitterHandle
    from DearUIQt.modelview import QListView
    assert QObject and QTimer and QPushButton and QSlider and QSplitterHandle and QListView
    after = {name for name in sys.modules if name.startswith('dearpygui')}
    assert after == before


def test_renderer_import_is_centralized_in_backends_package():
    offenders = []
    for path in (ROOT / 'DearUIQt').rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        if re.search(r'\b(?:from|import)\s+dearpygui', source):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == ['DearUIQt/backends/__init__.py']


def test_backend_injection_context_restores_previous_backend():
    from DearUIQt.backends import get_backend, set_backend, use_backend, reset_backend
    first = object()
    second = object()
    previous = set_backend(first)
    try:
        assert get_backend() is first
        with use_backend(second):
            assert get_backend() is second
        assert get_backend() is first
    finally:
        reset_backend()
        if previous is not None:
            set_backend(previous)


class _FakeBackend:
    def __init__(self):
        self.next = 1
        self.config = {}

    def add_button(self, **kwargs):
        tag = self.next
        self.next += 1
        self.config[tag] = dict(kwargs)
        return tag

    def configure_item(self, tag, **kwargs):
        self.config[tag].update(kwargs)

    def does_item_exist(self, tag):
        return tag in self.config

    def delete_item(self, tag):
        self.config.pop(tag, None)


def test_qsplitterhandle_owns_visual_line_and_hitbox_geometry():
    from DearUIQt.core import Qt
    from DearUIQt.layouts import QSplitterHandle
    backend = _FakeBackend()
    with patch('DearUIQt.qt.splitter.bind_theme', lambda *args, **kwargs: None):
        handle = QSplitterHandle(
            Qt.Horizontal, parent='root', backend=backend,
            handle_width=9, line_width=1)
        handle.setGeometry(100, 10, 9, 80)
    assert handle.hitBoxTag() == handle.tag
    assert handle.lineTag() != handle.tag
    assert backend.config[handle.tag]['pos'] == (100, 10)
    assert backend.config[handle.tag]['width'] == 9
    assert backend.config[handle.lineTag()]['pos'] == (104, 10)
    assert backend.config[handle.lineTag()]['width'] == 1


def test_winux_common_controls_are_constructed_through_dearuiqt():
    pattern = re.compile(r'dpg\.add_(?:button|image_button|input_text|checkbox)\s*\(')
    offenders = []
    for path in (ROOT / 'WinUx').rglob('*.py'):
        if pattern.search(path.read_text(encoding='utf-8')):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_main_view_uses_qsplitterhandle_instead_of_raw_button_hitboxes():
    source = (ROOT / 'WinUx' / 'view.py').read_text(encoding='utf-8')
    assert 'from DearUIQt.layouts import QSplitterHandle' in source
    assert 'self._file_panel_splitter_handle = QSplitterHandle(' in source
    assert 'self._horizontal_splitter_handle = QSplitterHandle(' in source
    assert 'dpg.add_button(' not in source


def test_winux_uses_public_dearuiqt_namespaces_not_internal_qt_modules():
    offenders = []
    for path in (ROOT / 'WinUx').rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        if 'DearUIQt.qt' in source:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_dearuiqt_source_has_no_winux_dependency():
    offenders = []
    for path in (ROOT / 'DearUIQt').rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        if re.search(r'\b(?:from|import)\s+WinUx\b', source):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
