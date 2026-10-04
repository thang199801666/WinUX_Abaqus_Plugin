"""Architecture/behavior guards for Server Notepad decomposition."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "WinUx" / "services" / "server_notepad_process.py"
WINDOWING = ROOT / "WinUx" / "services" / "server_notepad_windowing.py"
STATE = ROOT / "WinUx" / "services" / "server_notepad_state.py"
BACKGROUND = ROOT / "WinUx" / "services" / "server_notepad_background.py"
LOADING = ROOT / "WinUx" / "services" / "server_notepad_loading.py"
SAVE = ROOT / "WinUx" / "services" / "server_notepad_save.py"
EDITOR = ROOT / "WinUx" / "services" / "server_notepad_editor.py"
TYPES = ROOT / "WinUx" / "services" / "server_notepad_types.py"
COMMANDS = ROOT / "WinUx" / "services" / "server_notepad_commands.py"
IPC = ROOT / "WinUx" / "services" / "server_notepad_ipc.py"


def _class_methods(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_server_notepad_window_remains_facade_over_single_owner_mixins():
    source = PROCESS.read_text(encoding="utf-8")
    assert "ServerNotepadWindowingMixin" in source
    assert "ServerNotepadStateMixin" in source
    assert "ServerNotepadBackgroundMixin" in source
    assert "ServerNotepadLoadingMixin" in source
    assert "ServerNotepadSaveMixin" in source
    assert "ServerNotepadEditorMixin" in source
    assert "ServerNotepadCommandMixin" in source
    process_methods = _class_methods(PROCESS, "ServerNotepadWindow")
    moved = {
        "_center_over_owner", "_activate_native_window", "_save_local_state",
        "_restore_session_tabs", "_start_background_index",
        "_start_background_find_all", "_pump_background_events",
        "_snapshot_begin_ui", "_render_pending_chunks", "_save_doc",
        "_reload_doc",
    }
    assert not (process_methods & moved)


def test_windowing_and_state_keep_native_and_atomic_safety_contracts():
    windowing = WINDOWING.read_text(encoding="utf-8")
    state = STATE.read_text(encoding="utf-8")
    assert "SetForegroundWindow" in windowing
    assert "MonitorFromWindow" in windowing
    assert "server_notepad_state.json" in state
    assert "os.replace(str(temporary), str(path))" in state
    assert "session_restore=True" in state


def test_background_function_index_behavior_is_preserved():
    spec = importlib.util.spec_from_file_location("server_notepad_background_under_test", BACKGROUND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extract = module.ServerNotepadBackgroundMixin._extract_function_entries_from_text
    assert extract("Python", "class A:\n    def run(self):\n        pass\n") == [
        (1, "class A"), (2, "def run")
    ]
    assert extract("Abaqus INP", "** comment\n*Part, name=P\n*Node\n*Step\n") == [
        (2, "*Part, name=P"), (4, "*Step")
    ]


def test_loading_and_save_lifecycles_have_single_owners():
    process_methods = _class_methods(PROCESS, "ServerNotepadWindow")
    loading_methods = _class_methods(LOADING, "ServerNotepadLoadingMixin")
    save_methods = _class_methods(SAVE, "ServerNotepadSaveMixin")
    expected_loading = {
        "_start_next_load", "_snapshot_begin_ui", "_snapshot_chunk_ui",
        "_snapshot_end_ui", "_render_pending_chunks",
        "_complete_stream_snapshot", "_begin_snapshot_insert",
        "_insert_snapshot_chunk", "_load_failed_ui",
    }
    expected_save = {
        "_save_doc", "_export_save_chunk", "_finish_save_export",
        "_save_succeeded_ui", "_save_conflict_ui", "_reload_doc",
        "_operation_failed_ui", "_handle_save_background_event",
    }
    assert expected_loading <= loading_methods
    assert expected_save <= save_methods
    assert not (expected_loading & process_methods)
    assert not (expected_save & process_methods)
    assert not (loading_methods & save_methods)


def test_save_background_pump_delegates_without_reowning_save_logic():
    background = BACKGROUND.read_text(encoding="utf-8")
    save = SAVE.read_text(encoding="utf-8")
    assert 'kind in {"save_failed", "save_ready"}' in background
    assert "self._handle_save_background_event(event)" in background
    assert "owner.request_save" not in background
    assert "self.owner.request_save(" in save


def test_editor_tab_lifecycle_and_document_types_have_single_owners():
    process_methods = _class_methods(PROCESS, "ServerNotepadWindow")
    editor_methods = _class_methods(EDITOR, "ServerNotepadEditorMixin")
    expected = {
        "_create_editor_tab", "_active_doc", "_select_doc",
        "_rebuild_tab_strip", "_close_doc", "_editor_context_menu",
        "_apply_word_wrap_to_doc", "_refresh_document_list",
        "_schedule_line_numbers", "_update_stats", "_switch_tab",
    }
    assert expected <= editor_methods
    assert not (expected & process_methods)
    types = TYPES.read_text(encoding="utf-8")
    assert "class _Document" in types
    assert "session_restore: bool = False" in types
    assert "line_numbers_after: object = None" in types


def test_command_and_ipc_lifecycles_have_single_owners():
    process_methods = _class_methods(PROCESS, "ServerNotepadWindow")
    command_methods = _class_methods(COMMANDS, "ServerNotepadCommandMixin")
    expected_commands = {
        "_shortcut_open", "_shortcut_save", "_shortcut_save_all",
        "_shortcut_find", "_shortcut_replace", "_shortcut_goto",
        "_shortcut_reload", "_shortcut_close_tab", "_shortcut_find_next",
        "_shortcut_find_previous", "_shortcut_zoom_in", "_shortcut_zoom_out",
        "_shortcut_zoom_reset", "_shortcut_next_tab",
        "_shortcut_previous_tab", "handle_command",
    }
    assert expected_commands <= command_methods
    assert not (expected_commands & process_methods)
    ipc = IPC.read_text(encoding="utf-8")
    assert "class ServerNotepadProcessBridge" in ipc
    assert "queue.Queue(maxsize=24)" in ipc
    assert "winux-server-notepad-parent-writer" in ipc
    assert 'codec"] = "zlib+base64"' in ipc
    process = PROCESS.read_text(encoding="utf-8")
    assert "class _ProcessBridge" not in process
    assert "ServerNotepadProcessBridge as _ProcessBridge" in process
