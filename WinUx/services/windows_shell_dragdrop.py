"""Native Windows Shell drag source support for local files.

The Dear PyGui list view owns an internal drag gesture for WinUx Local/Server
transfers.  When a Local drag leaves the WinUx top-level window, that gesture
is handed to the Windows Shell through :func:`SHDoDragDrop` so File Explorer
receives a real ``IDataObject`` containing the selected filesystem items.

No third-party COM package is required.  The Shell creates the drag source for
us (``pdsrc == NULL`` on Vista+), while an ``IShellItemArray`` is bound to the
standard ``BHID_DataObject`` handler.
"""

from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Iterable, Sequence


DROPEFFECT_NONE = 0x0
DROPEFFECT_COPY = 0x1
DROPEFFECT_MOVE = 0x2
DROPEFFECT_LINK = 0x4
_ALLOWED_EFFECTS = DROPEFFECT_COPY | DROPEFFECT_MOVE | DROPEFFECT_LINK

S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106 as signed HRESULT


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "GUID":
        raw = uuid.UUID(str(value)).bytes_le
        obj = cls()
        ctypes.memmove(ctypes.byref(obj), raw, 16)
        return obj


IID_IDataObject = GUID.from_string("0000010e-0000-0000-C000-000000000046")
# ShlGuid.h: use this handler to get IDataObject from IShellItemArray.
BHID_DataObject = GUID.from_string("B8C0BD9F-ED24-455C-83E6-D5390C4FE8C4")


def is_supported() -> bool:
    return os.name == "nt"


def _failed(hr: int) -> bool:
    return int(hr) < 0


def _release_com(pointer) -> None:
    """Release an IUnknown-compatible COM interface pointer."""
    if not pointer or os.name != "nt":
        return
    try:
        winfunctype = ctypes.WINFUNCTYPE
        vtable = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        release = winfunctype(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(pointer)
    except Exception:
        pass


def _bind_data_object(item_array):
    """Call IShellItemArray::BindToHandler(BHID_DataObject)."""
    winfunctype = ctypes.WINFUNCTYPE
    vtable = ctypes.cast(
        item_array, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    # IUnknown methods occupy slots 0..2; BindToHandler is slot 3.
    prototype = winfunctype(
        ctypes.c_long,
        ctypes.c_void_p,                 # this
        ctypes.c_void_p,                 # IBindCtx *
        ctypes.POINTER(GUID),            # REFGUID bhid
        ctypes.POINTER(GUID),            # REFIID riid
        ctypes.POINTER(ctypes.c_void_p), # void **ppvOut
    )
    bind = prototype(vtable[3])
    data_object = ctypes.c_void_p()
    hr = int(bind(
        item_array,
        None,
        ctypes.byref(BHID_DataObject),
        ctypes.byref(IID_IDataObject),
        ctypes.byref(data_object),
    ))
    if _failed(hr) or not data_object.value:
        raise OSError("Windows Shell could not create drag data (HRESULT 0x{:08X})".format(
            hr & 0xFFFFFFFF))
    return data_object


def _normalise_paths(paths: Iterable[os.PathLike | str]) -> list[Path]:
    result: list[Path] = []
    seen = set()
    for value in paths or ():
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError, TypeError):
            continue
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def drag_files(paths: Sequence[os.PathLike | str], owner_hwnd=None) -> int:
    """Run a native Explorer-compatible drag for *paths*.

    The function is synchronous for the duration of the user's drag, exactly
    like Win32 ``DoDragDrop``.  The returned value is one of the DROPEFFECT
    constants (or ``DROPEFFECT_NONE`` when cancelled/not supported).  Explorer
    itself performs any copy/move; WinUx must only refresh its Local pane after
    this function returns.
    """
    if os.name != "nt":
        return DROPEFFECT_NONE

    items = _normalise_paths(paths)
    if not items:
        return DROPEFFECT_NONE

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    shell32.SHParseDisplayName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    shell32.SHParseDisplayName.restype = ctypes.c_long
    shell32.SHCreateShellItemArrayFromIDLists.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHCreateShellItemArrayFromIDLists.restype = ctypes.c_long
    shell32.SHDoDragDrop.argtypes = [
        wintypes.HWND,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    shell32.SHDoDragDrop.restype = ctypes.c_long
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.OleInitialize.restype = ctypes.c_long
    ole32.OleUninitialize.argtypes = []
    ole32.OleUninitialize.restype = None
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    init_hr = int(ole32.OleInitialize(None))
    should_uninitialize = init_hr in (S_OK, S_FALSE)
    # A host such as Abaqus may have initialized this thread as MTA already.
    # Shell helpers are still usable; simply do not balance an initialization
    # that did not belong to us.
    if _failed(init_hr) and init_hr != RPC_E_CHANGED_MODE:
        raise OSError("OLE initialization failed (HRESULT 0x{:08X})".format(
            init_hr & 0xFFFFFFFF))

    pidls: list[ctypes.c_void_p] = []
    item_array = ctypes.c_void_p()
    data_object = ctypes.c_void_p()
    try:
        for path in items:
            pidl = ctypes.c_void_p()
            attributes = wintypes.DWORD(0)
            hr = int(shell32.SHParseDisplayName(
                str(path), None, ctypes.byref(pidl), 0,
                ctypes.byref(attributes)))
            if _failed(hr) or not pidl.value:
                raise OSError(
                    "Windows Shell could not resolve '{}': HRESULT 0x{:08X}".format(
                        path, hr & 0xFFFFFFFF))
            pidls.append(pidl)

        array_type = ctypes.c_void_p * len(pidls)
        pidl_array = array_type(*(pidl.value for pidl in pidls))
        hr = int(shell32.SHCreateShellItemArrayFromIDLists(
            len(pidls), pidl_array, ctypes.byref(item_array)))
        if _failed(hr) or not item_array.value:
            raise OSError(
                "Windows Shell could not create item array (HRESULT 0x{:08X})".format(
                    hr & 0xFFFFFFFF))

        data_object = _bind_data_object(item_array)
        effect = wintypes.DWORD(DROPEFFECT_NONE)
        hr = int(shell32.SHDoDragDrop(
            wintypes.HWND(int(owner_hwnd or 0)),
            data_object,
            None,  # Vista+ Shell creates IDropSource on demand.
            _ALLOWED_EFFECTS,
            ctypes.byref(effect),
        ))
        # DRAGDROP_S_CANCEL / DRAGDROP_S_DROP are success status codes.  The
        # effect is authoritative; only negative HRESULTs are failures.
        if _failed(hr):
            raise OSError(
                "Windows Shell drag failed (HRESULT 0x{:08X})".format(
                    hr & 0xFFFFFFFF))
        return int(effect.value)
    finally:
        _release_com(data_object)
        _release_com(item_array)
        for pidl in pidls:
            try:
                ole32.CoTaskMemFree(pidl)
            except Exception:
                pass
        if should_uninitialize:
            try:
                ole32.OleUninitialize()
            except Exception:
                pass


__all__ = [
    "DROPEFFECT_NONE", "DROPEFFECT_COPY", "DROPEFFECT_MOVE", "DROPEFFECT_LINK",
    "is_supported", "drag_files",
]
