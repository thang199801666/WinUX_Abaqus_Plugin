"""Compatibility no-op for releases that previously exposed a startup splash.

The startup loading/splash UI was removed.  These symbols remain only so a
stale import cannot break WinUx startup while deployments transition.
"""
from __future__ import print_function


class StartupLoadingDialog(object):
    """Inert compatibility placeholder. No window is created."""

    token = None

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def update(self, message):
        del message

    def close(self):
        return None

    def wait_until_visible(self, timeout=0.0):
        del timeout
        return False

    def visible_latency(self):
        return None


def create_startup_loading_dialog(message="Preparing WinUx...", token=None):
    del message, token
    return None


def prewarm_startup_ui():
    return None


__all__ = [
    "StartupLoadingDialog",
    "create_startup_loading_dialog",
    "prewarm_startup_ui",
]
