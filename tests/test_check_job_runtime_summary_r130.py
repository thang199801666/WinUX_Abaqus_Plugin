from WinUx.services.remote_jobs import RemoteJobsMixin


def test_primary_step_frame_ignores_smaller_auxiliary_frame_stream():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
0 0.000E+00 0.000E+00 00:00:02 1.000E-06 1 0 0 0
Output Field Frame Number 0, of 20, at step time 0.000E+00
Output Field Frame Number 0, of 6 requested time points, at increment zero
100 2.000E-01 2.000E-01 00:20:00 1.000E-06 1 0 0 0
Output Field Frame Number 4, of 20, at step time 2.000E-01
Output Field Frame Number 6, of 6 time points, at step time 2.200E-01
200 2.500E-01 2.500E-01 00:25:00 1.000E-06 1 0 0 0
Output Field Frame Number 5, of 20, at step time 2.500E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["frame"] == 5
    assert status["total_frames"] == 20
    assert status["step_runtime"] == "00:25:00"
    assert status["total_runtime"] == "00:25:00"
    assert RemoteJobsMixin._format_abaqus_status(status) == (
        "Status: Running\n"
        "Current step: 1\n"
        "Frame: 5/20\n"
        "Frame time: 00:05:00\n"
        "Total runtime: 00:25:00"
    )


def test_current_step_runtime_is_difference_between_nearest_steps():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
10 1.000E+00 1.000E+00 00:05:00 1.000E-06 10 0 0 0
Output Field Frame Number 10, of 10 time points, at step time 1.000E+00
STEP 2 ORIGIN 1.0
20 2.500E-01 1.250E+00 00:07:30 1.000E-06 20 0 0 0
Output Field Frame Number 3, of 12 time points, at step time 2.500E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status["step_runtime"] == "00:02:30"
    assert status["total_runtime"] == "00:07:30"
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert "Current step: 2" in formatted
    assert "Frame: 3/12" in formatted
    assert "Frame time: N/A" in formatted
    assert "Total runtime: 00:07:30" in formatted
    assert formatted.isascii()
