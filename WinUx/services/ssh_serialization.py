from __future__ import annotations

import functools


def serialized_wire_call(method):
    """Serialize control-channel SSH/SFTP operations across worker threads.

    WinUx owns one authenticated SSH transport. Control-path operations share
    the browser SFTP/client and therefore take ``_connection_lock`` for their
    complete logical operation. Callers that explicitly provide an SFTP
    client own a dedicated channel and bypass the browser lock.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if kwargs.get("sftp_client") is not None:
            return method(self, *args, **kwargs)
        with self._connection_lock:
            return method(self, *args, **kwargs)
    return wrapper


# Compatibility name used throughout the pre-decomposition implementation.
_serialized_wire_call = serialized_wire_call
