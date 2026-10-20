from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_controller_exposes_qt_style_retained_close_without_destroying_host():
    text = source('WinUx/ui/hosting/floating_dialog.py')
    tree = ast.parse(text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'FloatingDialogController')
    init = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                and node.name == '__init__')
    assert 'retain_on_close' in [arg.arg for arg in init.args.args + init.args.kwonlyargs]
    close = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'close')
    close_text = ast.get_source_segment(text, close)
    assert 'self.hide()' in close_text
    assert 'self.destroy()' in close_text


def test_plot_digitizer_opts_into_retained_close():
    text = source('WinUx/plotdigitizer/integration/winux.py')
    assert 'retain_on_close=True' in text
    assert 'return super().close()' in text


def test_child_runtime_distinguishes_user_hide_from_terminal_destroy():
    text = source('WinUx/ui/hosting/floating_runtime.py')
    assert 'self._hard_destroy_form = self.form.destroy' in text
    assert 'self.form.destroy = self._resident_close' in text
    assert 'self.hide(user_close=True)' in text
    assert 'user_close=bool(user_close)' in text
    # Terminal IPC close must bypass retained hide and execute real cleanup.
    assert 'destroy = self._hard_destroy_form or self.form.destroy' in text


def test_reusable_dialog_visual_close_is_not_delayed_by_idle_ack():
    text = source('WinUx/ui/hosting/floating_dialog.py')
    marker = '# Visual close is synchronous and independent of host recycling.'
    assert marker in text
    section = text[text.index(marker):text.index('self._closed = self._finalized = True', text.index(marker))]
    assert 'set_native_window_visible(self._hwnd, False)' in section
    assert '_reuse_host' not in section


def test_pool_keeps_headroom_for_resident_heavy_tool():
    text = source('WinUx/ui/hosting/host.py')
    assert 'def __init__(self, capacity=3' in text
