from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.services.odb import extract as odb_extract


def _payload(error=None):
    return {
        "schemaVersion": 1,
        "mode": "extract",
        "odb": "job.odb",
        "path": "job.odb",
        "series": [],
        "error": error,
    }


def _encoded_payload(error=None):
    import json
    return "{}\n{}\n{}".format(
        odb_extract.JSON_BEGIN,
        json.dumps(_payload(error), separators=(",", ":")),
        odb_extract.JSON_END,
    )


def test_local_extract_waits_for_busy_odb_then_retries_same_launcher(tmp_path):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"odb")
    first = SimpleNamespace(returncode=0, stdout=_encoded_payload("database is being updated"), stderr="")
    second = SimpleNamespace(returncode=0, stdout=_encoded_payload(None), stderr="")
    with patch.object(odb_extract.subprocess, "run", side_effect=[first, second]) as run, \
         patch.object(odb_extract, "_local_odb_processing_hint", return_value=True), \
         patch.object(odb_extract, "_wait_for_local_odb_ready", return_value=True) as wait:
        result = odb_extract.extract_local_odb_history_data(
            odb, [], abaqus_commands=["abq2026"], abaqus_command="abq2026", timeout=10)
    assert run.call_count == 2
    wait.assert_called_once()
    assert result["abaqusCommand"] == "abq2026"
    assert result["waitedForOdbUpdate"] is True


def test_local_extract_does_not_wait_for_nonbusy_error(tmp_path):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"odb")
    failed = SimpleNamespace(returncode=0, stdout=_encoded_payload("ODB was created by a newer release"), stderr="")
    with patch.object(odb_extract.subprocess, "run", return_value=failed) as run, \
         patch.object(odb_extract, "_local_odb_processing_hint", return_value=False), \
         patch.object(odb_extract, "_wait_for_local_odb_ready") as wait:
        try:
            odb_extract.extract_local_odb_history_data(
                odb, [], abaqus_commands=["abq2026"], abaqus_command="abq2026", timeout=10)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")
    assert run.call_count == 1
    wait.assert_not_called()


def test_parse_odb_extract_output_can_return_error_payload_for_retry_logic():
    payload = odb_extract.parse_odb_extract_output(
        _encoded_payload("temporarily unavailable"), allow_error=True)
    assert payload["error"] == "temporarily unavailable"


def test_local_extract_does_not_wait_for_version_error_even_with_processing_hint(tmp_path):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"odb")
    failed = SimpleNamespace(returncode=0, stdout=_encoded_payload("ODB was created by a newer release"), stderr="")
    with patch.object(odb_extract.subprocess, "run", return_value=failed) as run, \
         patch.object(odb_extract, "_local_odb_processing_hint", return_value=True), \
         patch.object(odb_extract, "_wait_for_local_odb_ready") as wait:
        try:
            odb_extract.extract_local_odb_history_data(
                odb, [], abaqus_commands=["abq2026"], abaqus_command="abq2026", timeout=10)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")
    assert run.call_count == 1
    wait.assert_not_called()


def test_busy_error_classifier_is_conservative():
    assert odb_extract.odb_error_indicates_busy("database is being updated")
    assert odb_extract.odb_error_indicates_busy("sharing violation")
    assert not odb_extract.odb_error_indicates_busy("ODB was created by a newer release")
    assert not odb_extract.odb_error_indicates_busy("No module named odbAccess")


def test_classifier_version_mismatch_beats_processing_hint_and_known_launcher():
    kind = odb_extract.classify_odb_open_failure(
        "The database is from a more recent release of Abaqus; upgrade is required",
        known_compatible=True, processing_hint=True)
    assert kind == odb_extract.ODB_FAILURE_VERSION


def test_classifier_known_compatible_generic_failure_plus_activity_is_busy():
    kind = odb_extract.classify_odb_open_failure(
        "Unable to open database", known_compatible=True, processing_hint=True)
    assert kind == odb_extract.ODB_FAILURE_BUSY


def test_classifier_unknown_launcher_generic_failure_is_not_busy():
    kind = odb_extract.classify_odb_open_failure(
        "Unable to open database", known_compatible=False, processing_hint=True)
    assert kind == odb_extract.ODB_FAILURE_UNKNOWN


def test_local_exact_path_compatibility_cache_distinguishes_busy_from_version(tmp_path):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"odb")
    path_key = odb_extract.os.path.normcase(odb_extract.os.path.abspath(str(odb)))
    previous = dict(odb_extract._LOCAL_ODB_COMPAT_COMMANDS)
    try:
        odb_extract._LOCAL_ODB_COMPAT_COMMANDS.clear()
        odb_extract._LOCAL_ODB_COMPAT_COMMANDS[path_key] = "abq2025"
        first = SimpleNamespace(returncode=0, stdout=_encoded_payload("Unable to open database"), stderr="")
        second = SimpleNamespace(returncode=0, stdout=_encoded_payload(None), stderr="")
        with patch.object(odb_extract.subprocess, "run", side_effect=[first, second]) as run, \
             patch.object(odb_extract, "_local_odb_processing_hint", return_value=True), \
             patch.object(odb_extract, "_wait_for_local_odb_ready", return_value=True) as wait:
            result = odb_extract.extract_local_odb_history_data(
                odb, [], abaqus_commands=["abq2026", "abq2025"], timeout=10)
        assert run.call_count == 2
        assert "abq2025" in str(run.call_args_list[0])
        wait.assert_called_once()
        assert result["abaqusCommand"] == "abq2025"
        assert result["waitedForOdbUpdate"] is True
    finally:
        odb_extract._LOCAL_ODB_COMPAT_COMMANDS.clear()
        odb_extract._LOCAL_ODB_COMPAT_COMMANDS.update(previous)
