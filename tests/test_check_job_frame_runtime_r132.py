from datetime import datetime
from pathlib import PurePosixPath
import threading

from WinUx.services.remote_jobs import RemoteJobsMixin


def test_frame_time_is_delta_between_consecutive_frames_of_primary_stream():
    content = """
Abaqus/Explicit 2026 DATE 20-Oct-2026 TIME 02:09:28
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0000
0 0.000E+00 0.000E+00 00:00:02 1.000E-06 1 0 0 0
Output Field Frame Number 0, of 20, at step time 0.000E+00
Output Field Frame Number 0, of 6 requested time points, at increment zero
100 5.000E-02 5.000E-02 00:07:15 1.000E-06 1 0 0 0
Output Field Frame Number 1, of 20, at step time 5.000E-02
200 1.000E-01 1.000E-01 00:14:32 1.000E-06 1 0 0 0
Output Field Frame Number 2, of 20, at step time 1.000E-01
300 1.600E-01 1.600E-01 00:24:37 1.000E-06 1 0 0 0
Output Field Frame Number 1, of 6 time points, at step time 1.600E-01
400 1.500E-01 1.500E-01 00:22:42 1.000E-06 1 0 0 0
Output Field Frame Number 3, of 20, at step time 1.500E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status['frame'] == 3
    assert status['total_frames'] == 20
    assert status['frame_runtime'] == '00:08:10'
    assert status['steps'][0]['frame_runtime'] == '00:08:10'
    formatted = RemoteJobsMixin._format_abaqus_status(status)
    assert 'Frame: 3/20' in formatted
    assert 'Frame time: 00:08:10' in formatted
    assert 'Step runtime:' not in formatted


def test_frame_time_is_na_when_previous_frame_marker_is_unavailable():
    content = """
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
100 1.000E-01 1.000E-01 00:04:24 1.000E-06 10 0 0 0
Output Field Frame Number 3, of 65 time points, at step time 1.000E-01
"""
    status = RemoteJobsMixin._parse_abaqus_status(content)
    assert status['frame_runtime'] is None
    assert 'Frame time: N/A' in RemoteJobsMixin._format_abaqus_status(status)


def test_total_runtime_at_check_uses_job_start_timestamp_to_check_time():
    status = RemoteJobsMixin._parse_abaqus_status("""
Abaqus/Explicit 2026 DATE 20-Oct-2026 TIME 02:09:28
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
100 1.000E-01 1.000E-01 00:04:24 1.000E-06 10 0 0 0
Output Field Frame Number 3, of 65 time points, at step time 1.000E-01
""")
    RemoteJobsMixin._apply_check_time_runtime(
        status, datetime(2026, 10, 20, 2, 20, 0))
    assert status['total_runtime'] == '00:10:32'


class _LiveRuntimeProbe(RemoteJobsMixin):
    def __init__(self):
        self._connection_lock = threading.RLock()
        self.home = PurePosixPath('/home/huyhuynh')
        self.username = 'huyhuynh'

    def current_remote_identity(self):
        return 'huyhuynh', 'ohpcvn.simpsonmfg.com'

    def _find_job_temp_folder_by_id(self, *args, **kwargs):
        return '/home/huyhuynh/Temp/huyhuynh/31646.ohpcvn.simpsonmfg.com_case'

    def _find_latest_file(self, folder, pattern, exclude_suffix=None):
        return str(PurePosixPath(folder) / 'case.sta')

    def run_command(self, command):
        if command.startswith("cat '"):
            return """
Abaqus/Explicit 2026 DATE 20-Oct-2026 TIME 02:09:28
SOLUTION PROGRESS
STEP 1 ORIGIN 0.0
10 5.000E-02 5.000E-02 00:02:00 1.000E-06 10 0 0 0
Output Field Frame Number 1, of 10 time points, at step time 5.000E-02
20 1.000E-01 1.000E-01 00:04:30 1.000E-06 10 0 0 0
Output Field Frame Number 2, of 10 time points, at step time 1.000E-01
"""
        if command.startswith("date '"):
            return '20-Oct-2026 02:20:00'
        raise AssertionError(command)


def test_read_job_status_reports_frame_time_and_live_total_runtime():
    probe = _LiveRuntimeProbe()
    message = RemoteJobsMixin.read_job_status.__wrapped__(
        probe, '31646', 'case', 'huyhuynh')
    assert message == (
        'Status: Running\n'
        'Current step: 1\n'
        'Frame: 2/10\n'
        'Frame time: 00:02:30\n'
        'Total runtime: 00:10:32'
    )
