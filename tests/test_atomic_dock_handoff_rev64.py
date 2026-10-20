from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / 'WinUx' / 'ui' / 'behaviors' / 'console_docking.py').read_text(encoding='utf-8')
PLOTS = (ROOT / 'WinUx' / 'ui' / 'behaviors' / 'plot_docking.py').read_text(encoding='utf-8')


def test_console_undock_keeps_embedded_widget_until_native_first_present():
    block = CONSOLE.split('def undock_console(', 1)[1].split('def dock_console(', 1)[0]
    assert 'self._console_undock_pending_host = host' in block
    assert 'def commit_float():' in block
    assert 'host.after_first_present(commit_float)' in block
    commit = block.split('def commit_float():', 1)[1].split('host.after_first_present', 1)[0]
    assert 'QRetainedItem(self.console_dock.root).hide()' in commit
    prefix = block.split('def commit_float():', 1)[0]
    assert 'QRetainedItem(self.console_dock.root).hide()' not in prefix
    # The closed(...) restore path in the prefix only re-shows the embedded
    # dock on failure; it must never hide the live embedded dock early.
    assert '.hide()' not in prefix


def test_console_failed_pending_undock_restores_embedded_dock():
    block = CONSOLE.split('def undock_console(', 1)[1].split('def dock_console(', 1)[0]
    assert 'if getattr(self, "_console_undock_pending_host", None) is closing:' in block
    assert 'self._console_dock_mode = "docked"' in block
    assert 'QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)' in block


def test_plot_undock_uses_first_present_atomic_handoff():
    block = PLOTS.split('def undock_job_plots(', 1)[1].split('def dock_job_plots(', 1)[0]
    assert 'pending_hosts[key] = host' in block
    assert 'def commit_float():' in block
    assert 'host.after_first_present(commit_float)' in block
    commit = block.split('def commit_float():', 1)[1].split('host.after_first_present', 1)[0]
    assert 'panel.set_dock_mode("floating")' in commit
    assert 'QRetainedItem(panel.root).hide()' in commit
    prefix = block.split('def commit_float():', 1)[0]
    assert 'QRetainedItem(panel.root).hide()' not in prefix


def test_pending_plot_undock_can_be_cancelled_without_blank_frame():
    block = PLOTS.split('def dock_job_plots(', 1)[1].split('def ', 1)[0]
    assert 'pending_host = pending_hosts.pop(key, None)' in block
    assert 'pending_host.destroy()' in block
    assert 'QRetainedItem(window.root).show()' in block
