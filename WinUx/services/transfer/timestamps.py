"""Set modification times on validated scratch files, before publication."""
import math
import os


def checked_mtime(value, *, sftp=False):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Source modification time is unavailable.')
    if not math.isfinite(result) or (sftp and not 0 <= result <= 0xFFFFFFFF):
        raise ValueError('Source modification time cannot be represented by the destination.')
    return int(result) if sftp else result


def preserve_remote_mtime(sftp, temporary, modified, attributes):
    modified = checked_mtime(modified, sftp=True)
    atime = getattr(attributes, 'st_atime', modified)
    try:
        atime = checked_mtime(atime, sftp=True)
    except ValueError:
        atime = modified
    try:
        sftp.utime(str(temporary), (atime, modified))
    except (AttributeError, OSError) as exc:
        raise RuntimeError('Could not preserve modification time; destination was not published: {}'.format(exc)) from exc


def preserve_local_mtime(temporary, modified):
    modified = checked_mtime(modified)
    try:
        info = os.stat(temporary, follow_symlinks=False)
        os.utime(temporary, ns=(info.st_atime_ns, round(modified * 1_000_000_000)))
    except (OSError, OverflowError, ValueError) as exc:
        raise RuntimeError('Could not preserve modification time; destination was not published: {}'.format(exc)) from exc


def timestamp_options(view):
    """Read already-loaded UI preferences once, never settings I/O per chunk."""
    enabled = getattr(view, '_preserve_file_timestamps', None)
    return {'preserve_timestamps': enabled} if type(enabled) is bool else {}
