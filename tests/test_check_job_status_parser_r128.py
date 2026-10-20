from pathlib import PurePosixPath

from WinUx.services.remote_jobs import RemoteJobsMixin


def test_parser_tracks_frame_increment_step_and_wall_time_for_explicit_2026():
    content = """
Abaqus/Explicit 2026
SOLUTION PROGRESS
 STEP 1  ORIGIN 0.0000
              STEP     TOTAL      WALL        STABLE    CRITICAL
INCREMENT     TIME      TIME      TIME     INCREMENT     ELEMENT
        0  0.000E+00 0.000E+00  00:00:02 1.90693E-06        4302
Output Field Frame Number      1, of     65 requested time points, at increment zero
    86677  1.650E-01 1.650E-01  00:14:16 1.89145E-06       15230
Output Field Frame Number    10, of     65 time points, at step time 1.650E-01
    89322  1.700E-01 1.700E-01  00:14:43 1.89000E-06       15189
Output Field Frame Number    11, of     65 time points, at step time 1.700E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["state"] == "running"
    assert status["frame"] == 11
    assert status["total_frames"] == 65
    assert status["step"] == 1
    assert status["increment"] == 89322
    assert status["step_time"] == "1.700E-01"
    assert status["total_time"] == "1.700E-01"
    assert status["wall_time"] == "00:14:43"
    assert status["step_count"] == 1
    assert status["steps"][0]["wall_elapsed"] == "00:14:43"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Running" in formatted
    assert "Current step: 1" in formatted
    assert "Frame: 11/65" in formatted
    assert "Frame time: 00:00:27" in formatted
    assert "Total runtime: 00:14:43" in formatted
    assert "Steps:" not in formatted


def test_parser_falls_back_to_increment_when_no_output_frame_exists_yet():
    content = """
SOLUTION PROGRESS
 STEP 2 ORIGIN 1.0000
     431  2.500D-03 1.0025D+00  00:00:09 1.000D-06  88  0.0 0.0 0.0
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["state"] == "running"
    assert status["frame"] is None
    assert status["increment"] == 431
    assert status["step"] == 2
    assert status["step_time"] == "2.500D-03"
    assert status["total_time"] == "1.0025D+00"
    assert status["wall_time"] == "00:00:09"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Running" in formatted
    assert "Current step: 2" in formatted
    assert "Frame: N/A" in formatted
    assert "Frame time: N/A" in formatted
    assert "Total runtime: 00:00:09" in formatted
    assert "Steps:" not in formatted


def test_parser_ignores_partially_written_or_impossible_trailing_frame():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
Output Field Frame Number 7, of 20 time points, at step time 7.000E-01
Output Field Frame Number 21, of 20 time points, at step time 8.000E-01
Output Field Frame Number 8, of
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["frame"] == 7
    assert status["total_frames"] == 20


def test_terminal_marker_after_progress_wins_but_old_error_before_new_progress_does_not():
    failed = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
Output Field Frame Number 4, of 10 time points, at step time 4.000E-01
THE ANALYSIS HAS TERMINATED DUE TO AN ERROR
"""
    status = RemoteJobsMixin._parse_abaqus_status(failed)
    assert status["state"] == "failed"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Terminated" in formatted
    assert "Current step: 1" in formatted
    assert "Frame: 4/10" in formatted

    restarted = """
***ERROR: stale text from an earlier attempt
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
 100 1.000E-02 1.000E-02 00:00:03 1.000E-06 42 0 0 0
Output Field Frame Number 2, of 10 time points, at step time 1.000E-02
"""
    status = RemoteJobsMixin._parse_abaqus_status(restarted)
    assert status["state"] == "running"
    assert status["frame"] == 2


def test_completion_marker_is_reported_as_completed():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
Output Field Frame Number 65, of 65 time points, at step time 1.000E+00
THE ANALYSIS HAS COMPLETED SUCCESSFULLY
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["state"] == "completed"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Completed" in formatted
    assert "Current step: 1" in formatted
    assert "Frame: 65/65" in formatted


def test_preprocessing_and_solution_starting_are_distinguished():
    preprocessing = RemoteJobsMixin._parse_abaqus_status(
        "Abaqus/Explicit 2026\nPREPROCESSOR WARNING MESSAGES\n")
    assert preprocessing["state"] == "preprocessing"
    assert RemoteJobsMixin._format_abaqus_status(preprocessing) == (
        "Status: Preprocessing\nCurrent step: N/A\nFrame: N/A\nFrame time: N/A\nTotal runtime: N/A")

    starting = RemoteJobsMixin._parse_abaqus_status(
        "Abaqus/Explicit 2026\nSOLUTION PROGRESS\nSTEP 1 ORIGIN 0.0000\n")
    assert starting["state"] == "starting"
    assert RemoteJobsMixin._format_abaqus_status(starting) == (
        "Status: Starting\nCurrent step: 1\nFrame: N/A\nFrame time: N/A\nTotal runtime: N/A")


class _StatusFileProbe(RemoteJobsMixin):
    def __init__(self):
        self.patterns = []

    def _find_latest_file(self, folder, pattern, exclude_suffix=None):
        self.patterns.append((str(folder), pattern))
        if pattern == "Case-7-1.sta":
            return "/tmp/31646.host_Case-7-1/Case-7-1.sta"
        return "/tmp/31646.host_Case-7-1/helper.sta"


def test_status_file_selection_prefers_exact_job_stem_before_wildcard():
    probe = _StatusFileProbe()
    result = probe._find_job_status_file(
        PurePosixPath("/tmp/31646.host_Case-7-1"), "Case-7-1")
    assert result.endswith("/Case-7-1.sta")
    assert probe.patterns == [
        ("/tmp/31646.host_Case-7-1", "Case-7-1.sta"),
    ]


class _StatusFileFallbackProbe(RemoteJobsMixin):
    def __init__(self):
        self.patterns = []

    def _find_latest_file(self, folder, pattern, exclude_suffix=None):
        self.patterns.append(pattern)
        return "" if pattern == "Case-7-1.sta" else "/tmp/job/retry.sta"


def test_status_file_selection_uses_wildcard_only_when_exact_file_is_missing():
    probe = _StatusFileFallbackProbe()
    result = probe._find_job_status_file("/tmp/job", "Case-7-1")
    assert result == "/tmp/job/retry.sta"
    assert probe.patterns == ["Case-7-1.sta", "*.sta"]
