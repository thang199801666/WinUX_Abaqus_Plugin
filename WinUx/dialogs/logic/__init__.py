"""UI-neutral dialog domain logic shared by all WinUx dialog front ends.

The migration layer used to inherit whole legacy Tk dialog classes only to
reuse parsing/state methods.  Keep business behavior here so the Dear PyGui,
floating-process and legacy/native wrappers can share one implementation
without importing one another's UI toolkit.
"""

from .job_schedule import JobEditScheduleLogic
from .job_manager import JobManagerLogic
from .transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow
from .formatting import format_size, format_time
from .odb import (format_check_number, format_extract_number, format_vector,
                  format_bytes, history_item_label)

__all__ = [
    "JobEditScheduleLogic",
    "JobManagerLogic",
    "TransferCenterLogic",
    "TransferTaskHandle",
    "TransferItemRow",
    "format_size",
    "format_time",
    "format_check_number",
    "format_extract_number",
    "format_vector",
    "format_bytes",
    "history_item_label",
]
