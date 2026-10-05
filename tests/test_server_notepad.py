"""Regression coverage for the internal direct-on-server text editor."""

import io
import importlib.util
import stat
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from WinUx.server_model import RemoteTextConflictError, SSHServerModel


ROOT = Path(__file__).resolve().parents[1]
SERVER_MODEL = ROOT / "WinUx" / "server_model.py"
SERVER_TEXT = ROOT / "WinUx" / "services" / "server_text.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
CALLBACKS = ROOT / "WinUx" / "controllers" / "callbacks.py"
DIALOG = ROOT / "WinUx" / "dialogs" / "server_notepad_dialog.py"
PROCESS = ROOT / "WinUx" / "services" / "server_notepad_process.py"
STATE = ROOT / "WinUx" / "services" / "server_notepad_state.py"
WINDOWING = ROOT / "WinUx" / "services" / "server_notepad_windowing.py"
BACKGROUND = ROOT / "WinUx" / "services" / "server_notepad_background.py"
LOADING = ROOT / "WinUx" / "services" / "server_notepad_loading.py"
SAVE = ROOT / "WinUx" / "services" / "server_notepad_save.py"
EDITOR = ROOT / "WinUx" / "services" / "server_notepad_editor.py"
SEARCH = ROOT / "WinUx" / "services" / "server_notepad_search.py"
HIGHLIGHT = ROOT / "WinUx" / "services" / "server_notepad_highlight.py"
COMMANDS = ROOT / "WinUx" / "services" / "server_notepad_commands.py"
IPC = ROOT / "WinUx" / "services" / "server_notepad_ipc.py"
TABS = ROOT / "WinUx" / "components" / "server_notepad_tabs.py"
LAYOUT = ROOT / "WinUx" / "services" / "server_notepad_layout.py"
TYPES = ROOT / "WinUx" / "services" / "server_notepad_types.py"
SERVER_NOTEPAD_RUNTIME_SOURCE = "\n".join(
    path.read_text(encoding="utf-8") for path in (
        PROCESS, EDITOR, TYPES, SEARCH, HIGHLIGHT, COMMANDS, IPC, TABS, LAYOUT)
)
VIEW = ROOT / "WinUx" / "view.py"
RESOURCES = ROOT / "WinUx" / "Resources"


class _Transport:
    def is_active(self):
        return True


class _Client:
    def get_transport(self):
        return _Transport()


class _WriteBuffer(io.BytesIO):
    def __init__(self, sftp, path):
        super().__init__()
        self._sftp = sftp
        self._path = path

    def close(self):
        if not self.closed:
            self._sftp._set(self._path, self.getvalue())
        super().close()


class _FakeSFTP:
    def __init__(self, initial=None):
        self.files = {}
        self.modes = {}
        self._clock = 100
        for path, payload in dict(initial or {}).items():
            self._set(path, payload)

    def _set(self, path, payload):
        path = str(path)
        self._clock += 1
        self.files[path] = (bytes(payload), self._clock)
        self.modes.setdefault(path, stat.S_IFREG | 0o640)

    def stat(self, path):
        path = str(path)
        if path not in self.files:
            raise OSError(2, "not found")
        payload, mtime = self.files[path]
        return SimpleNamespace(
            st_size=len(payload),
            st_mtime=mtime,
            st_mode=self.modes.get(path, stat.S_IFREG | 0o640),
        )

    def open(self, path, mode):
        path = str(path)
        if "r" in mode:
            if path not in self.files:
                raise OSError(2, "not found")
            return io.BytesIO(self.files[path][0])
        if "w" in mode:
            return _WriteBuffer(self, path)
        raise AssertionError("unsupported mode {}".format(mode))

    def chmod(self, path, mode):
        path = str(path)
        existing = self.modes.get(path, stat.S_IFREG | 0o640)
        self.modes[path] = stat.S_IFMT(existing) | int(mode)

    def remove(self, path):
        path = str(path)
        if path not in self.files:
            raise OSError(2, "not found")
        self.files.pop(path, None)
        self.modes.pop(path, None)

    def posix_rename(self, source, target):
        source, target = str(source), str(target)
        payload, _mtime = self.files.pop(source)
        mode = self.modes.pop(source, stat.S_IFREG | 0o640)
        self._set(target, payload)
        self.modes[target] = mode


class _PrefetchSFTP(_FakeSFTP):
    def __init__(self, initial=None):
        super().__init__(initial)
        self.getfo_calls = []

    def lstat(self, path):
        return self.stat(path)

    def getfo(self, path, destination, callback=None, prefetch=True,
              max_concurrent_prefetch_requests=None):
        payload = self.files[str(path)][0]
        destination.write(payload)
        self.getfo_calls.append({
            "path": str(path),
            "prefetch": bool(prefetch),
            "requests": max_concurrent_prefetch_requests,
        })
        if callback:
            callback(len(payload), len(payload))
        return len(payload)



    def test_toolbar_uses_prebuilt_28px_icons_without_runtime_pixel_scan(self):
        source = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('"EditorToolbar28"', source)
        self.assertNotIn("def visible_bbox(image):", source)
        self.assertNotIn("def scaled_visible_icon(source, target):", source)
        self.assertNotIn("transparency_get(x, y)", source)
        resources = ROOT / "WinUx" / "Resources" / "EditorToolbar28"
        expected = (
            "Editor_OpenServer.png", "Editor_Save.png", "Editor_SaveAll.png",
            "Editor_Reload.png", "Editor_Undo.png", "Editor_Redo.png",
            "Cut.png", "Copy.png", "Paste.png", "Editor_Find.png",
            "Editor_Replace.png", "Editor_Goto.png", "Editor_Bookmark.png",
            "Editor_ZoomOut.png", "Editor_ZoomReset.png", "Editor_ZoomIn.png",
            "Upload.png", "Editor_New.png",
        )
        for name in expected:
            path = resources / name
            self.assertTrue(path.is_file(), name)
            data = path.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"), name)
            self.assertEqual(int.from_bytes(data[16:20], "big"), 28, name)
            self.assertEqual(int.from_bytes(data[20:24], "big"), 28, name)

class ServerNotepadModelTests(unittest.TestCase):
    def make_model(self, payload=b"alpha\nbeta\n"):
        model = SSHServerModel()
        model.client = _Client()
        model.sftp = _FakeSFTP({"/work/model.inp": payload})
        model.shell = SimpleNamespace(closed=False, active=True)
        return model

    def test_read_snapshot_is_direct_text_with_sha_signature(self):
        model = self.make_model()
        snapshot = model.read_text_snapshot("/work/model.inp")
        self.assertEqual(snapshot["text"], "alpha\nbeta\n")
        self.assertEqual(snapshot["encoding"], "utf-8")
        self.assertEqual(snapshot["size"], len(b"alpha\nbeta\n"))
        self.assertEqual(len(snapshot["signature"]["sha256"]), 64)

    def test_read_snapshot_uses_prefetched_sftp_pipeline_when_available(self):
        model = SSHServerModel()
        model.client = _Client()
        model.sftp = _PrefetchSFTP({"/work/model.inp": b"alpha\nbeta\n"})
        model.shell = SimpleNamespace(closed=False, active=True)
        snapshot = model.read_text_snapshot("/work/model.inp")
        self.assertEqual(snapshot["text"], "alpha\nbeta\n")
        self.assertEqual(len(model.sftp.getfo_calls), 1)
        self.assertTrue(model.sftp.getfo_calls[0]["prefetch"])
        self.assertEqual(
            model.sftp.getfo_calls[0]["requests"],
            model.DOWNLOAD_PREFETCH_REQUESTS)

    def test_stream_snapshot_forwards_text_incrementally_with_final_signature(self):
        payload = ("alpha\r\nbeta\n" * 60000).encode("utf-8")
        model = self.make_model(payload)
        begins = []
        chunks = []
        ends = []
        result = model.stream_text_snapshot(
            "/work/model.inp",
            begins.append,
            lambda text, byte_count: chunks.append((text, byte_count)),
            ends.append,
        )
        self.assertEqual(len(begins), 1)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(sum(byte_count for _text, byte_count in chunks), len(payload))
        self.assertEqual("".join(text for text, _count in chunks), payload.decode("utf-8"))
        self.assertEqual(ends[0]["signature"]["sha256"], result["signature"]["sha256"])
        self.assertEqual(ends[0]["eol"], "\r\n")

    def test_save_is_atomic_and_preserves_mode(self):
        model = self.make_model()
        before = model.read_text_snapshot("/work/model.inp")
        old_mode = model.sftp.stat("/work/model.inp").st_mode

        after = model.write_text_snapshot(
            "/work/model.inp", "changed\n", before["signature"],
            encoding=before["encoding"],
        )

        self.assertEqual(model.sftp.files["/work/model.inp"][0], b"changed\n")
        self.assertEqual(stat.S_IMODE(model.sftp.stat("/work/model.inp").st_mode),
                         stat.S_IMODE(old_mode))
        self.assertEqual(after["text"], "changed\n")
        self.assertFalse(any("winux-edit" in name for name in model.sftp.files))

    def test_concurrent_server_change_blocks_normal_save(self):
        model = self.make_model()
        opened = model.read_text_snapshot("/work/model.inp")
        model.sftp._set("/work/model.inp", b"changed elsewhere\n")

        with self.assertRaises(RemoteTextConflictError):
            model.write_text_snapshot(
                "/work/model.inp", "my edit\n", opened["signature"])

        self.assertEqual(
            model.sftp.files["/work/model.inp"][0], b"changed elsewhere\n")

    def test_force_save_explicitly_overwrites_conflict(self):
        model = self.make_model()
        opened = model.read_text_snapshot("/work/model.inp")
        model.sftp._set("/work/model.inp", b"changed elsewhere\n")

        model.write_text_snapshot(
            "/work/model.inp", "forced\n", opened["signature"], force=True)

        self.assertEqual(model.sftp.files["/work/model.inp"][0], b"forced\n")

    def test_binary_file_is_rejected(self):
        model = self.make_model(b"abc\x00def")
        with self.assertRaisesRegex(ValueError, "binary"):
            model.read_text_snapshot("/work/model.inp")

    def test_utf16_bom_round_trips(self):
        import codecs
        model = self.make_model(codecs.BOM_UTF16_LE + "A\nB".encode("utf-16-le"))
        opened = model.read_text_snapshot("/work/model.inp")
        self.assertEqual(opened["encoding"], "utf-16-le-bom")
        model.write_text_snapshot(
            "/work/model.inp", "C\nD", opened["signature"],
            encoding=opened["encoding"])
        self.assertEqual(
            model.sftp.files["/work/model.inp"][0],
            codecs.BOM_UTF16_LE + "C\nD".encode("utf-16-le"))


class ServerNotepadIntegrationTests(unittest.TestCase):
    def test_server_context_menu_exposes_internal_editor(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        self.assertIn('"label": "Edit in WinUx Notepad"', source)
        self.assertIn('"shortcut": "F4"', source)
        self.assertIn('"action": "edit_server_file"', source)
        self.assertIn('"id": "server_notepad_edit"', source)
        self.assertIn('<= 8 * 1024 * 1024', source)

    def test_controller_opens_window_before_sequential_server_load(self):
        callbacks = CALLBACKS.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        view = VIEW.read_text(encoding="utf-8")
        self.assertIn('"edit_server_file"', callbacks)
        self.assertIn('"edit_server_file": controller.edit_server_file', callbacks)
        self.assertIn("def edit_server_file", controller)
        self.assertIn("def _load_server_notepad", controller)
        controller += (ROOT / "WinUx" / "controllers" / "server_notepad.py").read_text(encoding="utf-8")
        self.assertIn("self.view.show_server_notepad(", controller)
        self.assertIn("self.server.stream_text_snapshot(", controller)
        self.assertIn('"server-notepad-{}".format(operation)', controller)
        self.assertIn("current.queue_open(path)", view)
        self.assertIn("on_load=on_load", view)

    def test_failed_existing_tab_is_requeued_on_explicit_open(self):
        from WinUx.services import server_notepad_process as process_module

        class _Text:
            def configure(self, **_kwargs):
                return None

            def delete(self, *_args):
                return None

            def insert(self, *_args):
                return None

            def edit_modified(self, *_args):
                return None

            def focus_set(self):
                return None

        path = "/work/model.inp"
        doc = SimpleNamespace(
            path=path,
            loaded=False,
            loading=False,
            queued=False,
            busy=False,
            pending_operation="",
            session_restore=True,
            render_chunks=deque(["stale"]),
            stream_end_pending=True,
            stream_end_meta={"stale": True},
            status_message="Load failed",
            text=_Text(),
        )
        events = []
        fake = SimpleNamespace(
            _documents={path: doc},
            _load_queue=deque(),
            _current_load_path=None,
            _remember_recent_path=lambda value: events.append(("recent", value)),
            _select_doc=lambda value: events.append(("select", value.path)),
            deiconify=lambda: None,
            lift=lambda: None,
            _set_doc_status=lambda value, status: setattr(value, "status_message", status),
            _update_tab_title=lambda value: events.append(("title", value.path)),
            _start_next_load=lambda: events.append(("start", path)),
        )

        process_module.ServerNotepadWindow._queue_open_ui(fake, path)

        self.assertTrue(doc.queued)
        self.assertTrue(doc.busy)
        self.assertEqual(doc.pending_operation, "load")
        self.assertFalse(doc.session_restore)
        self.assertEqual(list(fake._load_queue), [path])
        self.assertEqual(list(doc.render_chunks), [])
        self.assertIn(("start", path), events)

    def test_reopen_fix_has_bounded_enoent_retry_and_restore_is_nonblocking(self):
        controller = (ROOT / "WinUx" / "controllers" / "server_notepad.py").read_text(encoding="utf-8")
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        state = STATE.read_text(encoding="utf-8")
        self.assertIn("def _is_missing", controller)
        self.assertIn("for attempt in range(2 if retry_missing else 1):", controller)
        self.assertIn("cancel.wait(0.15)", controller)
        self.assertIn("Remote path: {}", controller)
        self.assertIn("session_restore: bool = False", process)
        self.assertIn("self._queue_open_ui(path, session_restore=True)", state)
        loading = LOADING.read_text(encoding="utf-8")
        self.assertIn("if restored_only and doc is not None:", loading)
        self.assertIn("if not existing.queued:", process)

    def test_launch_commands_wait_for_child_ready_handshake(self):
        spec = importlib.util.spec_from_file_location(
            "winux_server_notepad_dialog_handshake", DIALOG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dialog = module.ServerNotepadDialog.__new__(module.ServerNotepadDialog)
        import threading
        dialog._closed = threading.Event()
        dialog._ready = threading.Event()
        dialog._pending_commands = []
        dialog._pending_commands_lock = threading.Lock()
        dialog._write_lock = threading.Lock()
        writes = []
        dialog._write_encoded_locked = lambda encoded: writes.append(
            module.json.loads(encoded.decode("utf-8"))) or True

        self.assertTrue(dialog._send("queue_open", path="/work/model.inp"))
        self.assertEqual(writes, [])
        self.assertEqual(dialog._pending_commands[0]["path"], "/work/model.inp")

        dialog._ready.set()
        dialog._flush_pending_commands()
        self.assertEqual(writes[0]["command"], "queue_open")
        self.assertEqual(writes[0]["path"], "/work/model.inp")
        self.assertEqual(dialog._pending_commands, [])

    def test_session_restore_waits_for_explicit_open_and_restores_lazily(self):
        from WinUx.services import server_notepad_process as process_module

        class _Flag:
            def get(self):
                return True

        calls = []
        scheduled = []
        fake = SimpleNamespace(
            _restore_session=_Flag(),
            _session_restore_started=False,
            _explicit_open_seen=False,
            _state={"open_paths": ["/work/stale.sta"]},
            _documents={},
            after=lambda delay, callback: scheduled.append((delay, callback)),
            _queue_open_ui=lambda path, session_restore=False: calls.append(
                (path, session_restore)),
        )
        fake._restore_session_tabs = lambda: (
            process_module.ServerNotepadWindow._restore_session_tabs(fake))
        process_module.ServerNotepadWindow._restore_session_tabs(fake)
        self.assertEqual(calls, [])
        self.assertTrue(scheduled)

        fake._explicit_open_seen = True
        process_module.ServerNotepadWindow._restore_session_tabs(fake)
        self.assertEqual(calls, [("/work/stale.sta", True)])
        self.assertTrue(fake._session_restore_started)

        source = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('"Restored tab - select to load"', source)
        self.assertIn("queued=not lazy_restore", source)
        self.assertIn("if not lazy_restore:", source)
        self.assertIn("self._load_queue.appendleft(path)", source)

    def test_editor_ignores_saved_absolute_position_and_force_shows_window(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        windowing = WINDOWING.read_text(encoding="utf-8")
        facade = DIALOG.read_text(encoding="utf-8")
        self.assertIn('WINUX_SERVER_NOTEPAD_OWNER_HWND', facade)
        self.assertIn('self.geometry("{}x{}".format(width, height))', process)
        self.assertNotIn('self.geometry(geometry)', process)
        self.assertIn("def _center_over_owner", windowing)
        self.assertIn("def _activate_native_window", windowing)
        self.assertIn("ShowWindow", windowing)
        self.assertIn("SetForegroundWindow", windowing)
        self.assertIn('"event": "window_shown"', process)


    def test_dialog_constructor_accepts_legacy_snapshot_contract(self):
        spec = importlib.util.spec_from_file_location(
            "winux_server_notepad_dialog_under_test", DIALOG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dialog_type = module.ServerNotepadDialog
        events = []
        snapshot = {
            "path": "/work/model.inp",
            "text": "alpha\nbeta\n",
            "encoding": "utf-8",
            "signature": {"sha256": "abc"},
        }

        with mock.patch.object(dialog_type, "_start_process", lambda self: None), \
                mock.patch.object(
                    dialog_type, "queue_open",
                    lambda self, path: events.append(("queue", str(path))) or True), \
                mock.patch.object(
                    dialog_type, "load_succeeded",
                    lambda self, value: events.append(
                        ("snapshot", dict(value))) or True):
            dialog = dialog_type(
                object(), snapshot,
                on_save=lambda *_args: None,
                on_reload=lambda *_args: None,
            )

        self.assertIsNone(dialog._on_load)
        self.assertEqual(events[0], ("queue", "/work/model.inp"))
        self.assertEqual(events[1][0], "snapshot")
        self.assertEqual(events[1][1]["text"], "alpha\nbeta\n")

    def test_dialog_constructor_accepts_current_path_contract(self):
        spec = importlib.util.spec_from_file_location(
            "winux_server_notepad_dialog_current_contract", DIALOG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dialog_type = module.ServerNotepadDialog
        events = []
        on_load = lambda *_args: None

        with mock.patch.object(dialog_type, "_start_process", lambda self: None), \
                mock.patch.object(
                    dialog_type, "queue_open",
                    lambda self, path: events.append(("queue", str(path))) or True):
            dialog = dialog_type(
                object(), "/work/model.inp",
                on_load=on_load,
                on_save=lambda *_args: None,
                on_reload=lambda *_args: None,
            )

        self.assertIs(dialog._on_load, on_load)
        self.assertEqual(events, [("queue", "/work/model.inp")])

    def test_server_notepad_modern_helpers_do_not_require_dearpygui(self):
        """Standalone editor bootstrap must not import the DPG native module."""
        import subprocess
        import sys

        probe = r"""
import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'dearpygui' or name.startswith('dearpygui.'):
        raise RuntimeError('Dear PyGui must not be imported by Server Notepad bootstrap')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import WinUx.dialogs.modern
from WinUx.dialogs import ServerNotepadDialog
print(ServerNotepadDialog.__name__)
"""
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ServerNotepadDialog", result.stdout)

    def test_editor_is_process_isolated_tk_window(self):
        facade = DIALOG.read_text(encoding="utf-8")
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn("class ServerNotepadDialog", facade)
        self.assertIn("subprocess.Popen(", facade)
        self.assertIn("server_notepad_process.py", facade)
        self.assertNotIn("import tkinter as tk", facade)
        self.assertNotIn("NativeDialogController", facade)
        self.assertIn("class ServerNotepadWindow(", process)
        self.assertIn("ServerNotepadWindowingMixin", process)
        self.assertIn("ServerNotepadStateMixin", process)
        self.assertIn("tk.Tk):", process)
        self.assertIn("window.mainloop()", process)
        self.assertIn("ttk.Notebook", process)
        self.assertIn("tk.Text(", process)
        self.assertIn("WinUx Server Notepad++", process)
        self.assertIn("Find...", process)
        self.assertIn("Replace...", process)
        self.assertIn("Go to Line...", process)
        self.assertIn("Line Numbers", process)
        self.assertIn("Encoding", process)
        self.assertIn("EOL Conversion", process)
        self.assertIn("Force Save", process)

    def test_editor_loads_tabs_sequentially_and_buffer_in_chunks(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        loading = LOADING.read_text(encoding="utf-8")
        self.assertIn("self._load_queue = deque()", process)
        self.assertIn("self._current_load_path = None", process)
        self.assertIn("def _start_next_load", loading)
        self.assertIn("self.owner.request_load(path)", loading)
        self.assertIn("def _insert_snapshot_chunk", loading)
        self.assertIn("256 * 1024", loading)
        self.assertIn("snapshot_begin", process)
        self.assertIn("snapshot_chunk", process)
        self.assertIn("snapshot_end", process)
        self.assertIn("[loading]", process)
        self.assertIn("first_visible", process)
        self.assertIn("last_visible", process)
        self.assertIn("doc.dirty", process + loading)
        facade = DIALOG.read_text(encoding="utf-8")
        self.assertIn("_SNAPSHOT_IPC_CHARS = 256 * 1024", facade)
        self.assertIn("zlib+base64", facade)
        self.assertIn("def stream_begin", facade)
        self.assertIn("def stream_chunk", facade)
        self.assertIn("source_bytes", facade)
        self.assertIn("_queue_snapshot_stream", facade)

    def test_editor_has_notepadpp_style_document_and_function_panels(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('"Document List"', process)
        self.assertIn('"Function List"', process)
        self.assertIn('label="Settings"', process)
        self.assertIn('label="Window"', process)
        self.assertIn("Ctrl+Tab", process)
        self.assertIn("Highlight Current Line", process)
        self.assertIn("length: 0   lines: 1", process)
        self.assertIn("def _editor_context_menu", process)

    def test_large_file_pipeline_is_backpressured_and_time_sliced(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        model = SERVER_MODEL.read_text(encoding="utf-8")
        server_text = SERVER_TEXT.read_text(encoding="utf-8")
        self.assertIn("def stream_text_snapshot", server_text)
        self.assertIn("prefetch(", server_text)
        self.assertIn("on_chunk(text, len(data))", server_text)
        self.assertIn("queue.Queue(maxsize=24)", process)
        self.assertIn("IPC_PUMP_BUDGET_MS = 6.0", process)
        self.assertIn("RENDER_BUDGET_MS = 7.0", process)
        self.assertIn("RENDER_SLICE_CHARS = 64 * 1024", process)
        self.assertIn("PERFORMANCE_MODE_BYTES = 2 * 1024 * 1024", process)
        loading = LOADING.read_text(encoding="utf-8")
        self.assertIn("undo=False, autoseparators=False", loading)
        self.assertIn("Performance mode: viewport lexer + background index", loading)
        self.assertIn("PROGRESS_UI_INTERVAL = 0.080", process)
        self.assertIn("TEXT_EDITOR_PROBE_SIZE = 64 * 1024", model)
        self.assertIn("TEXT_EDITOR_READ_CHUNK_SIZE = 1024 * 1024", model)

    def test_interface_has_notepadpp_style_close_tabs_bookmarks_and_progress(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn("def _tab_left_click", process)
        self.assertIn('class _EditorTabStrip', process)
        self.assertIn('text="x"', process)
        self.assertIn('activebackground="#e81123"', process)
        self.assertIn("Toggle Bookmark", process)
        self.assertIn("Ctrl+F2", process)
        self.assertIn("ttk.Progressbar(", process)
        self.assertIn("Document List", process)
        self.assertIn("Function List", process)

    def test_toolbar_has_real_icons_for_undo_redo_and_zoom_commands(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        resources = ROOT / "WinUx" / "Resources" / "EditorToolbar28"
        expected = (
            "Editor_Undo.png", "Editor_Redo.png",
            "Editor_ZoomOut.png", "Editor_ZoomReset.png", "Editor_ZoomIn.png",
        )
        for name in expected:
            path = resources / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn('"Editor_Undo"', process)
        self.assertIn('"Editor_Redo"', process)
        self.assertIn('"Editor_ZoomOut"', process)
        self.assertIn('"Editor_ZoomReset"', process)
        self.assertIn('"Editor_ZoomIn"', process)

    def test_toolbar_uses_generated_transparent_editor_icon_assets(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        for name in (
                "Editor_Save.png", "Editor_SaveAll.png", "Editor_Reload.png",
                "Editor_Find.png", "Editor_Replace.png", "Editor_Goto.png",
                "Editor_Bookmark.png", "Editor_OpenServer.png"):
            self.assertTrue((RESOURCES / name).is_file(), name)
        self.assertIn('"Editor_Save"', process)
        self.assertIn('"Editor_SaveAll"', process)
        self.assertIn('"Editor_Reload"', process)
        self.assertIn('"Editor_Find"', process)
        self.assertIn('"Editor_Replace"', process)
        self.assertIn('"Editor_Goto"', process)
        self.assertIn('"Editor_Bookmark"', process)
        self.assertIn("class _ToolTip", process)

    def test_search_results_find_all_is_time_sliced(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('text="Search Results"', process)
        self.assertIn("def _find_all_current", process)
        self.assertIn("def _find_all_step", process)
        self.assertIn("budget = 0.008", process)
        self.assertIn("batch < 80", process)
        self.assertIn("self.view.after(1, self._find_all_step)", process)

    def test_ipc_compression_is_expanded_off_tk_thread(self):
        facade = DIALOG.read_text(encoding="utf-8")
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn("_SNAPSHOT_COMPRESS_MIN_CHARS", facade)
        self.assertIn('codec="zlib+base64"', facade)
        self.assertIn('zlib.decompress(raw).decode("utf-8")', process)
        self.assertIn("on the reader", process)


    def test_v147_editor_uses_background_index_adaptive_render_and_async_save(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        background = BACKGROUND.read_text(encoding="utf-8")
        facade = DIALOG.read_text(encoding="utf-8")
        self.assertIn("RENDER_SLICE_MIN_CHARS", process)
        self.assertIn("RENDER_SLICE_MAX_CHARS", process)
        loading = LOADING.read_text(encoding="utf-8")
        save = SAVE.read_text(encoding="utf-8")
        self.assertIn("doc.render_slice_chars", loading)
        self.assertIn("def _start_background_index", background)
        self.assertIn("def _start_background_find_all", background)
        self.assertIn("bisect_right", background)
        self.assertIn("SAVE_EXPORT_SLICE_CHARS", process)
        self.assertIn("def _export_save_chunk", save)
        self.assertIn("winux-server-notepad-parent-writer", process)
        self.assertIn('get("event") or "") == "save_request"', process)
        self.assertIn('event == "save_request"', facade)
        self.assertIn('codec") or "") == "zlib+base64"', facade)

    def test_v147_interface_is_compact_and_persists_recent_files(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        state = STATE.read_text(encoding="utf-8")
        self.assertIn("Recent Server Files", process)
        self.assertIn("server_notepad_state.json", state)
        self.assertIn("def _save_local_state", state)
        self.assertIn("Close Other Tabs", process)
        self.assertIn("Close Tabs to the Right", process)
        self.assertIn("Duplicate Current Line", process)
        self.assertIn("Delete Current Line", process)
        self.assertIn("def _show_load_progress", process)
        self.assertIn("self._length_var", process)
        self.assertIn("self._lines_var", process)


    def test_v148_toolbar_buttons_are_fixed_square_and_statusbar_is_compact(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('button_size = 30', process)
        self.assertIn('icon_size = 28', process)
        self.assertIn('bar = tk.Frame(', process)
        self.assertIn('bar.pack_propagate(False)', process)
        self.assertIn('background=toolbar_bg', process)
        self.assertIn('height=22, background="#f2f2f2"', process)
        self.assertIn('view.statusbar.pack_propagate(False)', LAYOUT.read_text(encoding="utf-8"))

    def test_toolbar_loads_prebuilt_large_icons_without_runtime_pixel_scan(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('"EditorToolbar28"', process)
        self.assertNotIn('def visible_bbox(image):', process)
        self.assertNotIn('transparency_get(x, y)', process)
        self.assertNotIn('def scaled_visible_icon(source, target):', process)
        self.assertIn('image = tk.PhotoImage(master=view.root, file=prepared)', LAYOUT.read_text(encoding="utf-8"))
        self.assertIn('hover_border = "#7eb4dc"', process)
        self.assertIn('pressed_border = "#4f9bd3"', process)
        self.assertIn('widget.pack(fill="both", expand=True, padx=1, pady=1)', process)

    def test_v148_gutter_redraw_is_coalesced_for_fast_scroll(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('line_numbers_after: object = None', process)
        self.assertIn('def _schedule_line_numbers', process)
        self.assertIn('def _run_line_number_update', process)
        self.assertIn('self._schedule_line_numbers(doc)', process)


    def test_v149_uses_custom_notepadpp_tab_strip_and_session_restore(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        state = STATE.read_text(encoding="utf-8")
        self.assertIn("class _EditorTabStrip", process)
        self.assertIn("ServerNotepad.Content.TNotebook", process)
        self.assertIn('background="#2b78d6" if active else bg', process)
        self.assertIn("def _rebuild_tab_strip", process)
        self.assertIn("def _sync_tab_strip", process)
        self.assertIn("def _restore_session_tabs", state)
        self.assertIn('"open_paths": open_paths[:24]', state)
        self.assertIn('"active_path": active_path', state)
        self.assertIn("Restore previous server tabs on startup", process)
        self.assertIn("def _schedule_state_save", state)

    def test_v149_dock_headers_have_real_close_controls(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn("def _build_dock_header", process)
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn('view.document_panel, "Document List"', layout)
        self.assertIn('view.function_panel, "Function List"', layout)
        self.assertIn('activebackground="#e81123"', process)

    def test_v150_server_double_click_routes_to_internal_notepad(self):
        controller = CONTROLLER.read_text(encoding="utf-8")
        start = controller.index("    def double_click(self, panel, event):")
        end = controller.index("    def _open_remote_file", start)
        block = controller[start:end]
        self.assertIn('panel.panel_id == "server" and not item.is_dir', block)
        self.assertIn("self.edit_server_file(panel, [path])", block)
        self.assertNotIn("self._open_remote_file", block)

    def test_v150_legacy_external_open_remains_explicit_menu_command(self):
        panel = FILE_PANEL.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn('("Open", "command:open"', panel)
        self.assertIn("def _open_remote_file", controller)

    def test_v151_native_notebook_tabs_are_fully_hidden(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        self.assertIn('style.layout("ServerNotepad.Content.TNotebook.Tab", [])', process)
        self.assertIn('tabmargins=(0, 0, 0, 0)', process)
        self.assertIn('"ServerNotepad.Content.TNotebook.Tab",', process)
        self.assertIn('padding=0, borderwidth=0, width=0', process)

    def test_tk_window_preserves_direct_server_safety_contract(self):
        process = SERVER_NOTEPAD_RUNTIME_SOURCE
        save = SAVE.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("dict(doc.signature)", save)
        self.assertIn("Preparing save snapshot", save)
        self.assertIn("Conflict:", save)
        self.assertIn("Reload from Server", save)
        self.assertIn("Force Save", process)
        controller += (ROOT / "WinUx" / "controllers" / "server_notepad.py").read_text(encoding="utf-8")
        self.assertIn("self.server.write_text_snapshot(", controller)
        self.assertIn("RemoteTextConflictError", controller)
        self.assertIn("dialog.save_conflict, str(exc), str(path)", controller)

    def test_child_crash_isolated_and_diagnostic_log_is_reported(self):
        facade = DIALOG.read_text(encoding="utf-8")
        self.assertIn("server_notepad.log", facade)
        self.assertIn("closed unexpectedly", facade)
        self.assertIn("process.terminate()", facade)
        self.assertIn("CREATE_NO_WINDOW", facade)



if __name__ == "__main__":
    unittest.main()
