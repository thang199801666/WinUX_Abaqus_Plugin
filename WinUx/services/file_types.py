"""Explorer-compatible file type labels from the current Windows Shell.

No GUI/icon dependency and no access to the supplied path: remote filenames use
the same local Windows associations as Explorer's Type column.
"""
import ctypes
from ctypes import wintypes
from functools import lru_cache
import ntpath
import os
import time


_SHGFI_TYPENAME = 0x00000400
_SHGFI_USEFILEATTRIBUTES = 0x00000010
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_CACHE_SECONDS = 60


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ('hIcon', wintypes.HICON),
        ('iIcon', ctypes.c_int),
        ('dwAttributes', wintypes.DWORD),
        ('szDisplayName', ctypes.c_wchar * 260),
        ('szTypeName', ctypes.c_wchar * 80),
    ]


@lru_cache(maxsize=1)
def _shell_type_query():
    # Own the ctypes function wrapper: windows_icons configures the same export
    # with its own structure class. Mutating windll's shared argtypes would
    # make subsequent icon calls reject that otherwise identical structure.
    query = ctypes.WinDLL('shell32').SHGetFileInfoW
    query.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                      ctypes.POINTER(_SHFILEINFOW), wintypes.UINT, wintypes.UINT]
    query.restype = ctypes.c_size_t
    return query


def _read_shell_type(extension, is_dir):
    if os.name != 'nt':
        return ''
    try:
        query = _shell_type_query()
        info = _SHFILEINFOW()
        # USEFILEATTRIBUTES avoids probing local, network or SSH paths. Do not
        # request an icon: this lookup allocates no HICON or renderer texture.
        attributes = _FILE_ATTRIBUTE_DIRECTORY if is_dir else _FILE_ATTRIBUTE_NORMAL
        probe = 'folder' if is_dir else 'file' + extension
        result = query(probe, attributes, ctypes.byref(info), ctypes.sizeof(info),
                       _SHGFI_TYPENAME | _SHGFI_USEFILEATTRIBUTES)
        return str(info.szTypeName).strip() if result else ''
    except (AttributeError, OSError, ValueError, TypeError, ctypes.ArgumentError):
        return ''


@lru_cache(maxsize=512)
def _cached_type(extension, is_dir, time_bucket):
    return _read_shell_type(extension, is_dir)


def file_type_name(name, is_dir=False):
    """Return the localized Shell type, with an extension-based safe fallback.

    Cache by extension/directory, never per path. Association changes are picked
    up by subsequent row refreshes after at most one 60-second cache window.
    Explicit row labels (jobs, parent-folder entries) remain the caller's policy.
    """
    extension = '' if is_dir else ntpath.splitext(ntpath.basename(str(name or '')))[1].casefold()
    if extension == '.':
        extension = ''
    label = _cached_type(extension, bool(is_dir), int(time.monotonic() // _CACHE_SECONDS))
    if label:
        return label
    return 'File folder' if is_dir else (extension[1:].upper() + ' File' if extension else 'File')


def clear_file_type_cache():
    """Invalidate Shell metadata for the next directory/row refresh."""
    _cached_type.cache_clear()


__all__ = ['file_type_name', 'clear_file_type_cache']
