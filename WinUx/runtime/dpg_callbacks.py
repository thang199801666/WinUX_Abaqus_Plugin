"""Robust Dear PyGui manual callback dispatch.

Dear PyGui 2.3.x's public ``run_callbacks`` helper counts every positional
parameter reported by ``inspect.signature`` and then indexes the native callback
job for that many values.  A perfectly valid callback such as::

    lambda sender, app_data, user_data, path=folder: open_folder(path)

therefore makes the helper read ``job[4]`` even though DPG callback jobs carry
only the three standard payload values (sender, app_data, user_data).  The
result is ``IndexError: tuple index out of range``.

WinUx owns callback dispatch because it enables ``manual_callback_management``.
Dispatch only the arguments that actually exist in the native job and let Python
apply default values for any remaining optional callback parameters.
"""
from __future__ import annotations

import inspect
import sys


def _callback_args(callback, available):
    """Return the safe positional argument slice for one DPG callback job."""
    available = tuple(available or ())
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        # Python/C callables without an inspectable signature are rare in the
        # WinUx UI. DPG itself supplies at most sender/app_data/user_data.
        return available[:3]

    positional = []
    has_varargs = False
    for parameter in signature.parameters.values():
        if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD):
            positional.append(parameter)
        elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            has_varargs = True

    if has_varargs:
        return available
    # Crucial: never pad to len(positional). Missing optional parameters must be
    # left missing so their Python default values remain in effect.
    return available[:len(positional)]


def invoke_callback_job(job):
    """Invoke one native DPG callback job without over-indexing its tuple.

    Returns ``True`` when a callable was invoked and ``False`` for an empty or
    disabled job. Exceptions raised *inside* the callback are deliberately not
    swallowed; callers decide whether a dialog should fail or an app callback
    should be logged and continued.
    """
    if not isinstance(job, (tuple, list)) or not job:
        return False
    callback = job[0]
    if callback is None or not callable(callback):
        return False
    callback(*_callback_args(callback, job[1:]))
    return True


def run_callback_jobs(jobs, on_error=None):
    """Dispatch an iterable of DPG callback jobs safely.

    If ``on_error`` is supplied it receives ``(callback, sys.exc_info())`` and
    dispatch continues. Otherwise the original exception is re-raised.
    """
    for job in jobs or ():
        callback = job[0] if isinstance(job, (tuple, list)) and job else None
        try:
            invoke_callback_job(job)
        except Exception:
            if on_error is None:
                raise
            on_error(callback, sys.exc_info())
