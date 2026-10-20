from __future__ import annotations

from ..job_schedule_form import JobScheduleDialog as JobScheduleForm
from .common import RetainedTool


class JobScheduleDialog(RetainedTool, JobScheduleForm):
    def __init__(self, view, schedule_provider, schedule_command):
        JobScheduleForm.__init__(self, view, schedule_provider, schedule_command)
        self._init_inprocess_lifetime(view)
