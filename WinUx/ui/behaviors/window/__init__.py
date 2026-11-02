"""Native main-window behaviors separated from UI composition."""
from .application_menu import ApplicationMenuMixin
from .compact_job_monitor import CompactJobMonitorMixin
from .dialog_facade import DialogFacadeMixin
from .lifecycle import ViewLifecycleMixin
from .startup_docking import StartupDockingMixin

__all__ = [
    "ApplicationMenuMixin", "CompactJobMonitorMixin", "DialogFacadeMixin",
    "StartupDockingMixin", "ViewLifecycleMixin",
]
