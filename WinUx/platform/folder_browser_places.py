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


def drive_stock_id(path):
    if os.name != "nt":
        return 8
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    get_type.argtypes = [ctypes.c_wchar_p]
    get_type.restype = ctypes.c_uint
    # Shell's documented SHSTOCKICONID values, not resource-index guesses.
    return {2: 7, 3: 8, 4: 9, 5: 11, 6: 12}.get(get_type(str(path)), 58)
