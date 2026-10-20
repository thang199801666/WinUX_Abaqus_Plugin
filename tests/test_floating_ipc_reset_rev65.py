from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = (ROOT / 'WinUx' / 'ui' / 'hosting' / 'host.py').read_text(encoding='utf-8')
FLOAT = (ROOT / 'WinUx' / 'ui' / 'hosting' / 'floating_dialog.py').read_text(encoding='utf-8')
DOCK = (ROOT / 'WinUx' / 'dialogs' / 'native_dock_hosts.py').read_text(encoding='utf-8')
QUEUE = (ROOT / 'WinUx' / 'runtime' / 'command_queue.py').read_text(encoding='utf-8')


def test_prewarm_pool_rejects_dead_ipc_channel_before_lease():
    assert 'def channel_healthy(self):' in HOST
    assert 'socket.MSG_PEEK' in HOST
    assert 'and worker.channel_healthy()' in HOST
    assert 'and not worker.channel_healthy()]' in HOST


def test_floating_controller_retries_stale_prewarm_once_with_fresh_host():
    assert 'def _retry_startup_with_fresh_host(self, exc):' in FLOAT
    assert 'self._ipc_retry_count >= 1' in FLOAT
    assert 'fresh=True' in FLOAT
    assert 'initial = dict(self._initial_message)' in FLOAT
    assert 'self._outgoing.put_nowait(initial)' in FLOAT
    assert 'self._transport_generation += 1' in FLOAT
    assert 'message["authorized_hwnd"] = None' in FLOAT


def test_native_dock_tearoffs_use_fresh_host_to_avoid_stale_prewarm_socket():
    assert DOCK.count('fresh_host=True') >= 2
    assert '"console_dock"' in DOCK
    assert '"plot_dock"' in DOCK


def test_pending_commands_can_be_rebound_to_retry_lease_without_reordering():
    assert 'def mutate_pending(self, callback):' in QUEUE
    assert 'with self.mutex:' in QUEUE


def test_native_dock_startup_ipc_failure_falls_back_without_modal_error_popup():
    block = DOCK.split('class _DockClose:', 1)[1].split('def _deliver_event', 1)[0]
    assert 'if not getattr(self, "_ready", False):' in block
    assert 'self._append_failure_log(message, details, stage)' in block
    assert 'self.destroy()' in block
    assert 'super()._failed(message, details=details, stage=stage)' in block
