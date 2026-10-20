from WinUx.services.remote_jobs import RemoteJobsMixin


def test_parse_abaqus_explicit_2026_requested_time_points_and_latest_frame():
    content = """
Abaqus/Explicit 2026
SOLUTION PROGRESS
Output Field Frame Number      1, of     65 requested time points, at increment zero
    13111  2.500E-02 2.500E-02  00:02:11 1.90692E-06 12599 8.037E-08 1.698E-10 1.260E+03
Output Field Frame Number     2, of     65 time points, at step time 2.500E-02
    89322  1.700E-01 1.700E-01  00:14:43 1.89000E-06 15189 1.101E-04 -9.887E-06 1.260E+03
Output Field Frame Number    11, of     65 time points, at step time 1.700E-01
"""
    assert RemoteJobsMixin._parse_abaqus_progress(content) == (11, 65)


def test_parse_abaqus_progress_keeps_legacy_comma_format_compatible():
    content = """
Output Field Frame Number 3, of 40,
Output Field Frame Number 12, of 40,
"""
    assert RemoteJobsMixin._parse_abaqus_progress(content) == (12, 40)


def test_parse_abaqus_progress_returns_none_when_status_has_no_frame_marker():
    content = "Abaqus/Explicit 2026\nSOLUTION PROGRESS\nSTEP 1 ORIGIN 0.0000\n"
    assert RemoteJobsMixin._parse_abaqus_progress(content) is None
