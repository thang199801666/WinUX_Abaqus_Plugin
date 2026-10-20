from WinUx.services.remote_jobs import RemoteJobsMixin


def test_total_runtime_includes_preprocessing_before_solution_progress():
    content = """
Abaqus/Explicit 2026                             DATE 20-Oct-2026  TIME 02:09:28
PREPROCESSOR WARNING MESSAGES
Abaqus/Explicit 2026                             DATE 20-Oct-2026  TIME 02:09:39
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
100 1.000E-01 1.000E-01 00:04:24 1.000E-06 10 0 0 0
Output Field Frame Number 3, of 65 time points, at step time 1.000E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)

    assert status["step_runtime"] == "00:04:24"
    assert status["startup_runtime"] == "00:00:11"
    assert status["total_runtime"] == "00:04:35"
    assert RemoteJobsMixin._format_abaqus_status(status) == (
        "Status: Running\n"
        "Current step: 1\n"
        "Frame: 3/65\n"
        "Frame time: N/A\n"
        "Total runtime: 00:04:35"
    )


def test_total_runtime_falls_back_to_wall_time_when_absolute_headers_are_missing():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
100 1.000E-01 1.000E-01 00:04:24 1.000E-06 10 0 0 0
Output Field Frame Number 3, of 65 time points, at step time 1.000E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)

    assert status["step_runtime"] == "00:04:24"
    assert status["total_runtime"] == "00:04:24"
    assert "startup_runtime" not in status


def test_solution_anchor_uses_header_before_first_solution_progress_not_later_page_header():
    content = """
Abaqus/Explicit 2026                             DATE 20-Oct-2026  TIME 02:09:28
Abaqus/Explicit 2026                             DATE 20-Oct-2026  TIME 02:09:39
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
50 5.000E-02 5.000E-02 00:02:00 1.000E-06 10 0 0 0
Abaqus/Explicit 2026                             DATE 20-Oct-2026  TIME 02:30:00
100 1.000E-01 1.000E-01 00:04:24 1.000E-06 10 0 0 0
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)

    # Later page headers must not be added on top of cumulative WALL TIME.
    assert status["startup_runtime"] == "00:00:11"
    assert status["step_runtime"] == "00:04:24"
    assert status["total_runtime"] == "00:04:35"
