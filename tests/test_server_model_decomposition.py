"""Architecture guards for SSHServerModel service decomposition."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "WinUx" / "server_model.py"
TEXT = ROOT / "WinUx" / "services" / "server_text.py"
ODB = ROOT / "WinUx" / "services" / "remote_odb.py"
TRANSFER = ROOT / "WinUx" / "services" / "remote_transfer.py"
FILESYSTEM = ROOT / "WinUx" / "services" / "remote_filesystem.py"
JOBS = ROOT / "WinUx" / "services" / "remote_jobs.py"
SERIALIZATION = ROOT / "WinUx" / "services" / "ssh_serialization.py"


def _class_methods(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_server_text_service_has_single_owner_and_model_remains_facade():
    model_source = MODEL.read_text(encoding="utf-8")
    assert "RemoteFilesystemMixin" in model_source
    assert "RemoteJobsMixin" in model_source
    assert "RemoteODBMixin" in model_source
    assert "RemoteTransferMixin" in model_source
    assert "ServerTextMixin" in model_source
    model_methods = _class_methods(MODEL, "SSHServerModel")
    text_methods = _class_methods(TEXT, "ServerTextMixin")
    expected = {
        "read_text", "_decode_remote_text", "_encode_remote_text",
        "_remote_text_signature", "_read_text_payload_prefetched",
        "read_text_snapshot", "stream_text_snapshot", "write_text_snapshot",
    }
    assert expected <= text_methods
    assert not (expected & model_methods)


def test_server_text_preserves_serialized_shared_transport_and_atomic_publish():
    source = TEXT.read_text(encoding="utf-8")
    assert "with self._connection_lock:" in source
    assert "self._publish_uploaded_file(self.sftp, temporary, path)" in source
    assert "Server Notepad checksum verification failed" in source
    assert "RemoteTextConflictError" in source
    assert "DOWNLOAD_PREFETCH_REQUESTS" in source
    assert "on_chunk(text, len(data))" in source


def test_remote_odb_service_has_single_owner_and_model_remains_facade():
    model_methods = _class_methods(MODEL, "SSHServerModel")
    odb_methods = _class_methods(ODB, "RemoteODBMixin")
    expected = {
        "_resolve_abaqus_for_odb_on", "check_odb", "_run_odb_extract_mode",
        "stream_odb_history", "list_odb_history_outputs",
        "extract_odb_history_data", "_validate_remote_odb_impl",
    }
    assert expected <= odb_methods
    assert not ((expected - {"_validate_remote_odb_impl"}) & model_methods)
    # The serialized compatibility wrapper intentionally remains on the facade.
    assert "_validate_remote_odb" in model_methods


def test_remote_transfer_service_has_single_owner_and_keeps_dedicated_channels():
    model_methods = _class_methods(MODEL, "SSHServerModel")
    transfer_methods = _class_methods(TRANSFER, "RemoteTransferMixin")
    expected = {
        "upload", "download", "_upload_file_stream", "_download_file_stream",
        "_upload_directory_stream", "_download_directory_stream",
        "_publish_uploaded_file", "_download_file", "_cancelled",
    }
    assert expected <= transfer_methods
    assert not (expected & model_methods)
    source = TRANSFER.read_text(encoding="utf-8")
    assert "with self._auxiliary_session() as (transfer_client, transfer_sftp)" in source
    assert "TRANSFER_STALL_TIMEOUT_SECONDS" in source
    assert "STREAM_EXIT_TIMEOUT_SECONDS" in source


def test_remote_filesystem_service_has_single_owner_and_dedicated_delete_channel():
    model_methods = _class_methods(MODEL, "SSHServerModel")
    filesystem_methods = _class_methods(FILESYSTEM, "RemoteFilesystemMixin")
    expected = {
        "list_directory", "search_directories", "is_dir", "exists", "move",
        "transfer", "rename", "new_folder", "new_file", "delete",
        "unique_target", "_remote_size", "remove", "normalize",
    }
    assert expected <= filesystem_methods
    assert not (expected & model_methods)
    source = FILESYSTEM.read_text(encoding="utf-8")
    delete_block = source[source.index("    def delete("):source.index("    @_serialized_wire_call", source.index("    def delete("))]
    assert "with self._transfer_sftp() as delete_sftp" in delete_block
    assert "sftp_client=delete_sftp" in delete_block
    assert "@_serialized_wire_call\n    def delete" not in source


def test_remote_jobs_service_has_single_owner_and_shared_serialization_contract():
    model_methods = _class_methods(MODEL, "SSHServerModel")
    job_methods = _class_methods(JOBS, "RemoteJobsMixin")
    expected = {
        "list_jobs", "submit_abaqus_job", "schedule_abaqus_job",
        "read_job_status", "find_job_output_file", "hot_download",
        "job_details", "cancel_job", "_parse_qstat_jobs",
    }
    assert expected <= job_methods
    assert not (expected & model_methods)
    serialization = SERIALIZATION.read_text(encoding="utf-8")
    assert "with self._connection_lock:" in serialization
    assert 'kwargs.get("sftp_client") is not None' in serialization
    assert "from .services.ssh_serialization import _serialized_wire_call" in MODEL.read_text(encoding="utf-8")


def test_hot_download_releases_control_lock_during_long_raw_stream():
    source = JOBS.read_text(encoding="utf-8")
    hot_start = source.index("    def hot_download(")
    hot_end = source.index("    def _hot_download_stream(", hot_start)
    hot = source[hot_start:hot_end]
    stream_end = source.index("    @_serialized_wire_call\n    def _exec_remote", hot_end)
    stream = source[hot_end:stream_end]
    assert "@_serialized_wire_call\n    def hot_download" not in source
    assert "@_serialized_wire_call\n    def _hot_download_stream" not in source
    assert "with self._transfer_sftp() as hot_sftp" in hot
    assert "sftp_client=hot_sftp" in hot
    assert "self._hot_download_stream(" in hot
    assert "self._open_transport_session(" in stream
