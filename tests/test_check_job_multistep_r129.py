from WinUx.services.remote_jobs import RemoteJobsMixin


def test_parser_tracks_multiple_steps_and_per_step_wall_time():
    content = """
Abaqus/Explicit 2026
SOLUTION PROGRESS
 STEP 1 ORIGIN 0.0000
     0 0.000E+00 0.000E+00 00:00:02 1.000E-06 10 0 0 0
 10000 1.000E+00 1.000E+00 00:05:00 1.000E-06 10 0 0 0
Output Field Frame Number 10, of 10 time points, at step time 1.000E+00
 STEP 2 ORIGIN 1.0000
     0 0.000E+00 1.000E+00 00:05:03 1.000E-06 20 0 0 0
  2500 2.500E-01 1.250E+00 00:07:30 1.000E-06 20 0 0 0
Output Field Frame Number 3, of 12 time points, at step time 2.500E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)

    assert status["state"] == "running"
    assert status["step"] == 2
    assert status["step_count"] == 2
    assert status["total_time"] == "1.250E+00"
    assert status["total_wall_time"] == "00:07:30"

    first, second = status["steps"]
    assert first == {
        "number": 1,
        "origin": "0.0000",
        "state": "completed",
        "frame": 10,
        "total_frames": 10,
        "increment": 10000,
        "step_time": "1.000E+00",
        "total_time": "1.000E+00",
        "wall_time": "00:05:00",
        "wall_elapsed": "00:05:00",
    }
    assert second == {
        "number": 2,
        "origin": "1.0000",
        "state": "running",
        "frame": 3,
        "total_frames": 12,
        "increment": 2500,
        "step_time": "2.500E-01",
        "total_time": "1.250E+00",
        "wall_time": "00:07:30",
        "wall_elapsed": "00:02:30",
    }


def test_multistep_status_format_shows_current_step_frame_and_runtimes_only():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
10 1.000E+00 1.000E+00 00:04:00 1.000E-06 10 0 0 0
Output Field Frame Number 5, of 5 time points, at step time 1.000E+00
STEP 2 ORIGIN 1.0
20 5.000E-01 1.500E+00 00:06:30 1.000E-06 20 0 0 0
Output Field Frame Number 2, of 8 time points, at step time 5.000E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    message = RemoteJobsMixin._format_abaqus_status(status)

    assert status["step_runtime"] == "00:02:30"
    assert status["total_runtime"] == "00:06:30"
    assert message == (
        "Status: Running\n"
        "Current step: 2\n"
        "Frame: 2/8\n"
        "Frame time: N/A\n"
        "Total runtime: 00:06:30"
    )
    assert message.isascii()


def test_completed_multistep_marks_all_steps_completed():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
10 1.000E+00 1.000E+00 00:01:00 1.000E-06 10 0 0 0
STEP 2 ORIGIN 1.0
20 2.000E+00 3.000E+00 00:03:30 1.000E-06 20 0 0 0
THE ANALYSIS HAS COMPLETED SUCCESSFULLY
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["state"] == "completed"
    assert [step["state"] for step in status["steps"]] == ["completed", "completed"]
    assert status["steps"][1]["wall_elapsed"] == "00:02:30"
    message = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Completed" in message
    assert "Current step: 2" in message


def test_failed_multistep_marks_only_current_step_failed():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
10 1.000E+00 1.000E+00 00:01:00 1.000E-06 10 0 0 0
STEP 2 ORIGIN 1.0
20 2.500E-01 1.250E+00 00:01:30 1.000E-06 20 0 0 0
THE ANALYSIS HAS TERMINATED DUE TO AN ERROR
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["state"] == "failed"
    assert status["steps"][0]["state"] == "completed"
    assert status["steps"][1]["state"] == "failed"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Status: Terminated" in formatted
    assert "Current step: 2" in formatted


def test_single_step_still_exposes_legacy_top_level_progress_fields():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
42 1.250E-01 1.250E-01 00:00:15 1.000E-06 20 0 0 0
Output Field Frame Number 4, of 20 time points, at step time 1.250E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["frame"] == 4
    assert status["total_frames"] == 20
    assert status["step"] == 1
    assert status["increment"] == 42
    assert status["wall_time"] == "00:00:15"
    assert RemoteJobsMixin._parse_abaqus_progress(content) == (4, 20)
