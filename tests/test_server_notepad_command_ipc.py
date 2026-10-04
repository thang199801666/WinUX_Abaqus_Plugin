"""Portable behavior coverage for Server Notepad command and IPC extraction."""
from __future__ import annotations

import base64
import io
import json
import queue
import threading
import zlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.services.server_notepad_commands import ServerNotepadCommandMixin
from WinUx.services.server_notepad_ipc import ServerNotepadProcessBridge


class _CommandView(ServerNotepadCommandMixin):
    pass


def test_shortcut_adapters_preserve_actions_and_break_contract():
    view = _CommandView()
    view._open_server_path = Mock()
    view._save_active = Mock()
    view._save_all = Mock()
    view._find_next = Mock()
    view._switch_tab = Mock()

    assert view._shortcut_open() == "break"
    assert view._shortcut_save() == "break"
    assert view._shortcut_save_all() == "break"
    assert view._shortcut_find_next() == "break"
    assert view._shortcut_find_previous() == "break"
    assert view._shortcut_next_tab() == "break"
    assert view._shortcut_previous_tab() == "break"

    view._open_server_path.assert_called_once_with()
    view._save_active.assert_called_once_with()
    view._save_all.assert_called_once_with()
    assert view._find_next.call_args_list[0].args == (True,)
    assert view._find_next.call_args_list[1].args == (False,)
    assert view._switch_tab.call_args_list[0].args == (1,)
    assert view._switch_tab.call_args_list[1].args == (-1,)


def test_command_dispatch_preserves_focus_and_lifecycle_routes():
    view = _CommandView()
    text = SimpleNamespace(focus_set=Mock())
    doc = SimpleNamespace(loaded=True, text=text)
    view._activate_native_window = Mock()
    view._active_doc = Mock(return_value=doc)
    view.withdraw = Mock()
    view._queue_open_ui = Mock()
    view._load_succeeded_ui = Mock()
    view._save_succeeded_ui = Mock()
    view._close_window_ui = Mock()

    view.handle_command("activate")
    view._activate_native_window.assert_called_once_with(center=False)
    text.focus_set.assert_called_once_with()

    view.handle_command("hide")
    view.withdraw.assert_called_once_with()
    view.handle_command("queue_open", "/scratch/a.inp")
    view._queue_open_ui.assert_called_once_with("/scratch/a.inp")
    view.handle_command("load_succeeded", {"path": "/scratch/a.inp"})
    view._load_succeeded_ui.assert_called_once_with({"path": "/scratch/a.inp"})
    view.handle_command("save_succeeded", {"path": "/scratch/a.inp"})
    view._save_succeeded_ui.assert_called_once_with({"path": "/scratch/a.inp"})
    view.handle_command("close")
    view._close_window_ui.assert_called_once_with()


def _bare_bridge():
    bridge = ServerNotepadProcessBridge.__new__(ServerNotepadProcessBridge)
    bridge.window = None
    bridge._incoming = queue.Queue(maxsize=24)
    bridge._outgoing = queue.Queue(maxsize=32)
    bridge._write_lock = threading.Lock()
    bridge._closed = threading.Event()
    return bridge


def test_ipc_pump_keeps_snapshot_stream_off_generic_command_dispatch():
    bridge = _bare_bridge()
    window = SimpleNamespace(
        IPC_PUMP_MAX_MESSAGES=8,
        IPC_PUMP_BUDGET_MS=1000.0,
        handle_command=Mock(),
        _snapshot_begin_ui=Mock(),
        _snapshot_chunk_ui=Mock(),
        _snapshot_end_ui=Mock(),
        after=Mock(),
    )
    bridge.window = window
    bridge._incoming.put({
        "command": "snapshot_begin", "operation": "load",
        "snapshot": {"path": "/scratch/a.inp"},
    })
    bridge._incoming.put({
        "command": "snapshot_chunk", "operation": "load",
        "path": "/scratch/a.inp", "text": "*Node\n", "source_bytes": 6,
    })
    bridge._incoming.put({
        "command": "snapshot_end", "operation": "load",
        "path": "/scratch/a.inp", "snapshot": {"sha256": "abc"},
    })
    bridge._incoming.put({"command": "activate"})

    bridge.pump()

    window._snapshot_begin_ui.assert_called_once_with(
        "load", {"path": "/scratch/a.inp"})
    window._snapshot_chunk_ui.assert_called_once_with(
        "load", "/scratch/a.inp", "*Node\n", 6)
    window._snapshot_end_ui.assert_called_once_with(
        "load", "/scratch/a.inp", {"sha256": "abc"})
    window.handle_command.assert_called_once_with("activate")
    window.after.assert_called_once()


def test_ipc_writer_compresses_large_save_payload_off_ui_thread():
    bridge = _bare_bridge()
    text = "*Node\n" * 20000
    bridge._outgoing.put({
        "event": "save_request", "path": "/scratch/a.inp", "text": text,
        "encoding": "utf-8", "signature": {}, "force": False,
    })
    bridge._outgoing.put(None)
    output = io.BytesIO()
    with patch("WinUx.services.server_notepad_ipc.sys.stdout",
               SimpleNamespace(buffer=output)):
        bridge._writer_loop()

    payload = json.loads(output.getvalue().decode("utf-8").strip())
    assert payload["codec"] == "zlib+base64"
    restored = zlib.decompress(base64.b64decode(payload["data"])).decode("utf-8")
    assert restored == text
    assert "text" not in payload


def test_ipc_reader_expands_compressed_snapshot_before_tk_queue():
    bridge = _bare_bridge()
    text = "*Element\n1, 1, 2\n" * 2000
    data = base64.b64encode(zlib.compress(text.encode("utf-8"), 1)).decode("ascii")
    raw = (json.dumps({
        "command": "snapshot_chunk", "path": "/scratch/a.inp",
        "codec": "zlib+base64", "data": data,
    }) + "\n").encode("utf-8")
    with patch("WinUx.services.server_notepad_ipc.sys.stdin",
               SimpleNamespace(buffer=io.BytesIO(raw))):
        bridge._reader_loop()

    message = bridge._incoming.get_nowait()
    assert message["command"] == "snapshot_chunk"
    assert message["text"] == text
    assert "codec" not in message
    assert "data" not in message
    assert bridge._incoming.get_nowait() == {"command": "close"}
