import winux_update_ui


def test_dialog_class_names_are_unique_across_repeated_launches():
    names = [winux_update_ui._next_dialog_class_name("WinUxUpdateAvailableDialog") for _ in range(100)]
    assert len(names) == len(set(names))


def test_real_progress_dialog_has_independent_ui_thread_on_windows():
    import os
    import time
    import pytest

    if os.name != "nt":
        pytest.skip("native Win32 progress dialog smoke test")

    dialog = winux_update_ui.create_progress_dialog("1.3.1", "1.3.2")
    try:
        assert dialog._hwnd
        assert dialog._thread is not None
        assert dialog._thread.is_alive()
        dialog.update(25, "Copying update files...")
        time.sleep(0.10)
        dialog.update(75, "Validating SHA-256 checksums...")
        time.sleep(0.10)
        dialog.update(100, "Update complete.")
    finally:
        dialog.close()
    assert dialog._closed is True


def test_embedded_python_missing_hcursor_uses_handle_fallback():
    """Abaqus Python may omit HCURSOR from ctypes.wintypes."""
    import ctypes

    class ReducedWinTypes(object):
        HANDLE = ctypes.c_void_p
        HWND = ctypes.c_void_p
        HINSTANCE = ctypes.c_void_p
        HICON = ctypes.c_void_p
        HBRUSH = ctypes.c_void_p
        # Intentionally no HCURSOR.

    assert winux_update_ui._win32_type(
        ReducedWinTypes, "HCURSOR", ReducedWinTypes.HANDLE
    ) is ReducedWinTypes.HANDLE


def test_embedded_python_missing_other_handle_aliases_use_fallback():
    import ctypes

    class MinimalWinTypes(object):
        HANDLE = ctypes.c_void_p

    for name in ("HWND", "HINSTANCE", "HICON", "HCURSOR", "HBRUSH"):
        assert winux_update_ui._win32_type(
            MinimalWinTypes, name, MinimalWinTypes.HANDLE
        ) is MinimalWinTypes.HANDLE


def test_win32_prototypes_keep_createwindow_handles_pointer_sized():
    """Regression for Abaqus x64: CreateWindowExW arg 11 must not be C int."""
    import ctypes
    from ctypes import wintypes

    class FakeFunction(object):
        def __init__(self):
            self.argtypes = None
            self.restype = None

    class FakeDll(object):
        def __init__(self):
            self._items = {}

        def __getattr__(self, name):
            value = self._items.get(name)
            if value is None:
                value = FakeFunction()
                self._items[name] = value
            return value

    HANDLE = ctypes.c_void_p
    aliases = {
        "HANDLE": HANDLE,
        "HWND": HANDLE,
        "HINSTANCE": HANDLE,
        "HICON": HANDLE,
        "HCURSOR": HANDLE,
        "HBRUSH": HANDLE,
        "HMENU": HANDLE,
        "UINT": ctypes.c_uint,
        "DWORD": ctypes.c_ulong,
        "BOOL": ctypes.c_int,
        "WPARAM": ctypes.c_size_t,
        "LPARAM": ctypes.c_ssize_t,
        "LPCWSTR": ctypes.c_wchar_p,
        "LPWSTR": ctypes.c_wchar_p,
        "LPVOID": ctypes.c_void_p,
        "LRESULT": ctypes.c_ssize_t,
    }

    class FakeWndClass(ctypes.Structure):
        _fields_ = [("dummy", ctypes.c_int)]

    user32 = FakeDll()
    kernel32 = FakeDll()
    gdi32 = FakeDll()
    winux_update_ui._configure_win32_prototypes(
        ctypes, wintypes, user32, kernel32, gdi32, FakeWndClass, aliases
    )

    create_args = user32.CreateWindowExW.argtypes
    assert len(create_args) == 12
    # hWndParent, hMenu, hInstance are arguments 9, 10 and 11.  All must be
    # pointer-sized handles; implicit c_int conversion caused the real Abaqus
    # OverflowError seen when creating the progress window.
    assert create_args[8] is HANDLE
    assert create_args[9] is HANDLE
    assert create_args[10] is HANDLE
    assert ctypes.sizeof(create_args[10]) == ctypes.sizeof(ctypes.c_void_p)
    assert user32.SendMessageW.argtypes[2] is ctypes.c_size_t
    assert user32.SendMessageW.argtypes[3] is ctypes.c_ssize_t
