"""Windows known-folder paths, including OneDrive and redirected profiles."""
import ctypes
import os
from pathlib import Path
import uuid


KNOWN_PLACES = (
    ("Home", "5E6C858F-0E22-4760-9AFE-EA3317B67173", ""),
    ("Desktop", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Desktop"),
    ("Documents", "FDD39AD0-238F-46AF-ADB4-6C85480369C7", "Documents"),
    ("Downloads", "374DE290-123F-4565-9164-39C4925E467B", "Downloads"),
    ("Pictures", "33E28130-4E1E-4676-835A-98395C3BC3BB", "Pictures"),
)


def known_folder_path(identifier, fallback):
    if os.name != "nt":
        return str(fallback)
    shell = ctypes.windll.shell32.SHGetKnownFolderPath
    shell.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_void_p)]
    shell.restype = ctypes.c_long
    free = ctypes.windll.ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(identifier).bytes_le)
    result = ctypes.c_void_p()
    try:
        # DONT_VERIFY reads the configured location without probing a share.
        if shell(ctypes.byref(guid), 0x4000, None, ctypes.byref(result)) == 0 and result.value:
            return ctypes.wstring_at(result.value)
    except (OSError, ValueError, ctypes.ArgumentError):
        pass
    finally:
        if result.value:
            free(result)
    return str(fallback)


def quick_access_places():
    home = Path.home()
    return [(label, known_folder_path(identifier, home / suffix))
            for label, identifier, suffix in KNOWN_PLACES]



def drive_display_name(path, *, query_volume=True):
    """Return an Explorer-style drive caption without probing file contents.

    Examples: ``System (C:)`` or ``Local Disk (C:)``.  Network/removable
    volumes are allowed to fail quickly and fall back to the bare drive root.
    """
    text = str(path or "")
    if os.name != "nt":
        return text
    root = text[:3] if len(text) >= 3 and text[1:3] == ":\\" else text
    drive = root[:2] if len(root) >= 2 and root[1] == ":" else root.rstrip("\\/")
    try:
        kernel32 = ctypes.windll.kernel32
        get_volume = kernel32.GetVolumeInformationW
        get_volume.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32,
        ]
        get_volume.restype = ctypes.c_int
        if query_volume:
            volume = ctypes.create_unicode_buffer(261)
            fsname = ctypes.create_unicode_buffer(261)
            serial = ctypes.c_uint32()
            max_component = ctypes.c_uint32()
            flags = ctypes.c_uint32()
            ok = get_volume(
                root, volume, len(volume), ctypes.byref(serial),
                ctypes.byref(max_component), ctypes.byref(flags), fsname, len(fsname),
            )
            label = volume.value.strip() if ok else ""
            if label:
                return "%s (%s)" % (label, drive)
        get_type = kernel32.GetDriveTypeW
        get_type.argtypes = [ctypes.c_wchar_p]
        get_type.restype = ctypes.c_uint
        drive_type = int(get_type(root))
        fallback = {2: "Removable Disk", 3: "Local Disk", 4: "Network Drive",
                    5: "CD Drive", 6: "RAM Disk"}.get(drive_type, "")
        return "%s (%s)" % (fallback, drive) if fallback else text
    except (OSError, ValueError, TypeError, ctypes.ArgumentError, AttributeError):
        return text

def drive_stock_id(path):
    if os.name != "nt":
        return 8
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    get_type.argtypes = [ctypes.c_wchar_p]
    get_type.restype = ctypes.c_uint
    # Shell's documented SHSTOCKICONID values, not resource-index guesses.
    return {2: 7, 3: 8, 4: 9, 5: 11, 6: 12}.get(get_type(str(path)), 58)
