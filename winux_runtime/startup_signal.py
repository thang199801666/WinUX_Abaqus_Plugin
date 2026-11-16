"""Compatibility no-op for the removed WinUx startup splash hand-off."""
from __future__ import print_function

STARTUP_SIGNAL_ENV = "WINUX_STARTUP_SIGNAL_FILE"
STARTUP_SPLASH_TOKEN_ENV = "WINUX_STARTUP_SPLASH_TOKEN"


def publish_startup_state(state, message="", environ=None):
    del state, message, environ
    return False


def read_startup_state(path):
    del path
    return None


def is_terminal_startup_state(state):
    del state
    return False


def dismiss_startup_splash(environ=None):
    del environ
    return False


__all__ = [
    "STARTUP_SIGNAL_ENV",
    "STARTUP_SPLASH_TOKEN_ENV",
    "publish_startup_state",
    "read_startup_state",
    "is_terminal_startup_state",
    "dismiss_startup_splash",
]
