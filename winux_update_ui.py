"""Small native Windows UI used before WinUx itself is started.

This module intentionally depends only on the Python standard library so it can
run inside Abaqus/CAE before WinUx configures its bundled vendor packages.
Keep the implementation compatible with both Python 2 and Python 3.
"""

from __future__ import print_function

import os
import itertools
import threading
import time

try:
    import Queue as queue  # Python 2
except ImportError:
    import queue


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


# Win32 constants used by the lightweight dialogs.
_WS_OVERLAPPED = 0x00000000
_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_VISIBLE = 0x10000000
_WS_CHILD = 0x40000000
_WS_TABSTOP = 0x00010000
_WS_BORDER = 0x00800000
_WS_EX_DLGMODALFRAME = 0x00000001
_WS_EX_TOPMOST = 0x00000008
_BS_DEFPUSHBUTTON = 0x00000001
_ES_AUTOHSCROLL = 0x00000080
_SS_LEFT = 0x00000000
_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_WM_COMMAND = 0x0111
_WM_SETFONT = 0x0030
_WM_USER = 0x0400
_WM_APP = 0x8000
_WM_PROGRESS_UPDATE = _WM_APP + 101
_WM_PROGRESS_CLOSE = _WM_APP + 102
_PBM_SETPOS = _WM_USER + 2
_PBM_SETRANGE32 = _WM_USER + 6
_PM_REMOVE = 0x0001
_SW_SHOW = 5
_DEFAULT_GUI_FONT = 17
_COLOR_BTNFACE = 15
_IDC_ARROW = 32512

# Dialog window classes live inside the long-running Abaqus/CAE process.
# Python may reuse object ids after a dialog closes, so id(state) is not a
# reliable class-name suffix across repeated plug-in launches.  A monotonic
# counter guarantees a fresh Win32 class name every time.
_DIALOG_CLASS_COUNTER = itertools.count(1)


def _next_dialog_class_name(prefix):
    return "{0}_{1}_{2}".format(prefix, os.getpid(), next(_DIALOG_CLASS_COUNTER))


def _unregister_class(api, class_name):
    """Best-effort cleanup of a dialog class after its window is destroyed."""
    try:
        api["user32"].UnregisterClassW(
            _text(class_name),
            api["kernel32"].GetModuleHandleW(None),
        )
    except Exception:
        pass


def _win32_type(wintypes_module, name, fallback):
    """Return a Win32 ctypes alias with a safe fallback.

    Abaqus ships its own Python runtime and some releases expose a reduced
    ``ctypes.wintypes`` module (for example, no ``HCURSOR``).  Native update
    dialogs must therefore treat the wintypes aliases as optional instead of
    assuming desktop CPython's exact surface area.
    """
    return getattr(wintypes_module, name, fallback)


def _configure_win32_prototypes(
    ctypes, wintypes, user32, kernel32, gdi32, WNDCLASSW, aliases
):
    """Declare Win32 call signatures using pointer-sized handle types.

    Without ``argtypes`` ctypes assumes undeclared arguments are C ``int``.
    That is unsafe in a 64-bit embedded runtime such as Abaqus/CAE because
    HWND/HINSTANCE/HMENU and message parameters are pointer-sized.  In
    particular the 11th argument of CreateWindowExW is HINSTANCE; passing the
    64-bit module handle through the implicit ``int`` conversion raises
    ``OverflowError: int too long to convert``.
    """
    HANDLE = aliases["HANDLE"]
    HWND = aliases["HWND"]
    HINSTANCE = aliases["HINSTANCE"]
    HCURSOR = aliases["HCURSOR"]
    HMENU = aliases["HMENU"]
    UINT = aliases["UINT"]
    DWORD = aliases["DWORD"]
    BOOL = aliases["BOOL"]
    WPARAM = aliases["WPARAM"]
    LPARAM = aliases["LPARAM"]
    LPCWSTR = aliases["LPCWSTR"]
    LPWSTR = aliases["LPWSTR"]
    LPVOID = aliases["LPVOID"]
    LRESULT = aliases["LRESULT"]

    LPMSG = ctypes.POINTER(wintypes.MSG)
    LPWNDCLASSW = ctypes.POINTER(WNDCLASSW)

    # kernel32
    kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
    kernel32.GetModuleHandleW.restype = HINSTANCE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = DWORD

    # user32 class/window creation and destruction.
    user32.RegisterClassW.argtypes = [LPWNDCLASSW]
    user32.RegisterClassW.restype = ctypes.c_ushort
    user32.UnregisterClassW.argtypes = [LPCWSTR, HINSTANCE]
    user32.UnregisterClassW.restype = BOOL
    user32.CreateWindowExW.argtypes = [
        DWORD, LPCWSTR, LPCWSTR, DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        HWND, HMENU, HINSTANCE, LPVOID,
    ]
    user32.CreateWindowExW.restype = HWND
    user32.DestroyWindow.argtypes = [HWND]
    user32.DestroyWindow.restype = BOOL
    user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    # Cursor/resource and basic window interaction.  LoadCursorW accepts a
    # MAKEINTRESOURCE value, therefore the resource argument is LPVOID rather
    # than a strict LPCWSTR.
    user32.LoadCursorW.argtypes = [HINSTANCE, LPVOID]
    user32.LoadCursorW.restype = HCURSOR
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.ShowWindow.restype = BOOL
    user32.SetForegroundWindow.argtypes = [HWND]
    user32.SetForegroundWindow.restype = BOOL
    user32.BringWindowToTop.argtypes = [HWND]
    user32.BringWindowToTop.restype = BOOL
    user32.SetFocus.argtypes = [HWND]
    user32.SetFocus.restype = HWND
    user32.UpdateWindow.argtypes = [HWND]
    user32.UpdateWindow.restype = BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    # Text/message APIs also carry HWND/WPARAM/LPARAM values and therefore
    # need explicit x64-safe signatures.
    user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
    user32.PostMessageW.restype = BOOL
    user32.MessageBoxW.argtypes = [HWND, LPCWSTR, LPCWSTR, UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [HWND, LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.SetWindowTextW.argtypes = [HWND, LPCWSTR]
    user32.SetWindowTextW.restype = BOOL

    # Message-loop functions.
    user32.PeekMessageW.argtypes = [LPMSG, HWND, UINT, UINT, UINT]
    user32.PeekMessageW.restype = BOOL
    user32.GetMessageW.argtypes = [LPMSG, HWND, UINT, UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [LPMSG]
    user32.TranslateMessage.restype = BOOL
    user32.DispatchMessageW.argtypes = [LPMSG]
    user32.DispatchMessageW.restype = LRESULT
    user32.WaitMessage.argtypes = []
    user32.WaitMessage.restype = BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    # GDI stock objects are opaque pointer-sized handles.
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.GetStockObject.restype = HANDLE


def _win32():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32
    comctl32 = ctypes.windll.comctl32

    # ``ctypes.wintypes`` is not identical across embedded Python runtimes.
    # Abaqus/CAE can omit several aliases.  H* types are opaque pointer-sized
    # handles, so HANDLE/c_void_p is ABI-safe for missing definitions.
    HANDLE = _win32_type(wintypes, "HANDLE", ctypes.c_void_p)
    HWND = _win32_type(wintypes, "HWND", HANDLE)
    HINSTANCE = _win32_type(wintypes, "HINSTANCE", HANDLE)
    HICON = _win32_type(wintypes, "HICON", HANDLE)
    HCURSOR = _win32_type(wintypes, "HCURSOR", HANDLE)
    HBRUSH = _win32_type(wintypes, "HBRUSH", HANDLE)
    HMENU = _win32_type(wintypes, "HMENU", HANDLE)
    UINT = _win32_type(wintypes, "UINT", ctypes.c_uint)
    DWORD = _win32_type(wintypes, "DWORD", ctypes.c_uint32)
    BOOL = _win32_type(wintypes, "BOOL", ctypes.c_int)
    WPARAM = _win32_type(wintypes, "WPARAM", ctypes.c_size_t)
    LPARAM = _win32_type(wintypes, "LPARAM", ctypes.c_ssize_t)
    LPCWSTR = _win32_type(wintypes, "LPCWSTR", ctypes.c_wchar_p)
    LPWSTR = _win32_type(wintypes, "LPWSTR", ctypes.c_wchar_p)
    LPVOID = ctypes.c_void_p
    # LRESULT is LONG_PTR, not C long.  c_ssize_t tracks pointer width on both
    # 32-bit and 64-bit Python and avoids truncation in Abaqus x64.
    LRESULT = ctypes.c_ssize_t

    aliases = {
        "HANDLE": HANDLE,
        "HWND": HWND,
        "HINSTANCE": HINSTANCE,
        "HICON": HICON,
        "HCURSOR": HCURSOR,
        "HBRUSH": HBRUSH,
        "HMENU": HMENU,
        "UINT": UINT,
        "DWORD": DWORD,
        "BOOL": BOOL,
        "WPARAM": WPARAM,
        "LPARAM": LPARAM,
        "LPCWSTR": LPCWSTR,
        "LPWSTR": LPWSTR,
        "LPVOID": LPVOID,
        "LRESULT": LRESULT,
    }

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", LPCWSTR),
            ("lpszClassName", LPCWSTR),
        ]

    _configure_win32_prototypes(
        ctypes, wintypes, user32, kernel32, gdi32, WNDCLASSW, aliases
    )

    try:
        comctl32.InitCommonControls()
    except Exception:
        pass

    return {
        "ctypes": ctypes,
        "wintypes": wintypes,
        "user32": user32,
        "kernel32": kernel32,
        "gdi32": gdi32,
        "WNDPROC": WNDPROC,
        "WNDCLASSW": WNDCLASSW,
        "aliases": aliases,
    }


def _loword(value):
    return int(value) & 0xFFFF


def _centered_position(api, width, height):
    user32 = api["user32"]
    screen_w = int(user32.GetSystemMetrics(0))
    screen_h = int(user32.GetSystemMetrics(1))
    return max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)


def _register_class(api, class_name, wndproc):
    ctypes = api["ctypes"]
    user32 = api["user32"]
    kernel32 = api["kernel32"]
    wc = api["WNDCLASSW"]()
    wc.style = 0
    wc.lpfnWndProc = wndproc
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hIcon = None
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(_IDC_ARROW))
    wc.hbrBackground = ctypes.c_void_p(_COLOR_BTNFACE + 1)
    wc.lpszMenuName = None
    wc.lpszClassName = _text(class_name)
    atom = user32.RegisterClassW(ctypes.byref(wc))
    # ERROR_CLASS_ALREADY_EXISTS == 1410; class reuse is harmless.
    if not atom:
        error = int(kernel32.GetLastError())
        if error != 1410:
            raise OSError(error, "RegisterClassW failed")
    return wc


def _apply_font(api, *handles):
    font = api["gdi32"].GetStockObject(_DEFAULT_GUI_FONT)
    for handle in handles:
        if handle:
            api["user32"].SendMessageW(handle, _WM_SETFONT, font, 1)


def _pump_messages(api):
    ctypes = api["ctypes"]
    wintypes = api["wintypes"]
    user32 = api["user32"]
    msg = wintypes.MSG()
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _run_modal_loop(api, state):
    while not state.get("done"):
        _pump_messages(api)
        if not state.get("done"):
            api["user32"].WaitMessage()


def _create_control(api, parent, class_name, text, style, x, y, width, height, control_id=0):
    ctypes = api["ctypes"]
    return api["user32"].CreateWindowExW(
        0,
        _text(class_name),
        _text(text),
        style,
        x,
        y,
        width,
        height,
        parent,
        ctypes.c_void_p(control_id),
        api["kernel32"].GetModuleHandleW(None),
        None,
    )


def confirm_update(local_version, server_version, server_dir):
    """Return True only when the user clicks **Update Now**."""
    api = _win32()
    if api is None:
        return False

    ctypes = api["ctypes"]
    user32 = api["user32"]
    state = {"done": False, "result": False}
    class_name = _next_dialog_class_name("WinUxUpdateAvailableDialog")
    controls = {}

    def window_proc(hwnd, message, wparam, lparam):
        if message == _WM_COMMAND:
            command_id = _loword(wparam)
            if command_id == 1001:
                state["result"] = True
                state["done"] = True
                user32.DestroyWindow(hwnd)
                return 0
            if command_id == 1002:
                state["result"] = False
                state["done"] = True
                user32.DestroyWindow(hwnd)
                return 0
        elif message == _WM_CLOSE:
            state["result"] = False
            state["done"] = True
            user32.DestroyWindow(hwnd)
            return 0
        elif message == _WM_DESTROY:
            state["done"] = True
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    wndproc = api["WNDPROC"](window_proc)
    wc = _register_class(api, class_name, wndproc)
    width, height = 560, 300
    x, y = _centered_position(api, width, height)
    hwnd = user32.CreateWindowExW(
        _WS_EX_DLGMODALFRAME,
        _text(class_name),
        _text("WinUx Update"),
        _WS_OVERLAPPED | _WS_CAPTION | _WS_SYSMENU | _WS_VISIBLE,
        x, y, width, height,
        None, None,
        api["kernel32"].GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        return False

    body = (
        "A new WinUx version is available.\r\n\r\n"
        "Current version: {0}\r\n"
        "New version: {1}\r\n\r\n"
        "Update source:\r\n{2}\r\n\r\n"
        "Choose Update Now to install it before WinUx starts, or Cancel to "
        "continue with the current local version."
    ).format(local_version or "unknown", server_version or "unknown", server_dir)
    controls["label"] = _create_control(
        api, hwnd, "STATIC", body,
        _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
        24, 20, 510, 174,
    )
    controls["update"] = _create_control(
        api, hwnd, "BUTTON", "Update Now",
        _WS_CHILD | _WS_VISIBLE | _WS_TABSTOP | _BS_DEFPUSHBUTTON,
        330, 215, 100, 32, 1001,
    )
    controls["cancel"] = _create_control(
        api, hwnd, "BUTTON", "Cancel",
        _WS_CHILD | _WS_VISIBLE | _WS_TABSTOP,
        440, 215, 90, 32, 1002,
    )
    _apply_font(api, hwnd, controls["label"], controls["update"], controls["cancel"])
    user32.ShowWindow(hwnd, _SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(controls["update"])
    _run_modal_loop(api, state)
    # Keep callback/class structure alive until after the modal loop, then
    # unregister it so subsequent plug-in launches cannot reuse a stale proc.
    _unregister_class(api, class_name)
    del wc, wndproc, ctypes
    return bool(state["result"])


def prompt_update_source(current_path):
    """Show a textbox for a replacement shared WinUx deployment path.

    Returns the entered path or None when the user chooses **Use Local**/closes
    the dialog.
    """
    api = _win32()
    if api is None:
        return None

    ctypes = api["ctypes"]
    user32 = api["user32"]
    state = {"done": False, "result": None}
    class_name = _next_dialog_class_name("WinUxUpdateSourceDialog")
    controls = {}

    def read_edit_text():
        edit = controls.get("edit")
        if not edit:
            return ""
        length = int(user32.GetWindowTextLengthW(edit))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(edit, buffer, length + 1)
        return buffer.value.strip().strip('"')

    def window_proc(hwnd, message, wparam, lparam):
        if message == _WM_COMMAND:
            command_id = _loword(wparam)
            if command_id == 1101:
                value = read_edit_text()
                if not value:
                    user32.MessageBoxW(
                        hwnd,
                        _text("Enter the folder that contains the shared WinUx deployment."),
                        _text("WinUx Update Source"),
                        0x00000030,
                    )
                    return 0
                state["result"] = value
                state["done"] = True
                user32.DestroyWindow(hwnd)
                return 0
            if command_id == 1102:
                state["result"] = None
                state["done"] = True
                user32.DestroyWindow(hwnd)
                return 0
        elif message == _WM_CLOSE:
            state["result"] = None
            state["done"] = True
            user32.DestroyWindow(hwnd)
            return 0
        elif message == _WM_DESTROY:
            state["done"] = True
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    wndproc = api["WNDPROC"](window_proc)
    wc = _register_class(api, class_name, wndproc)
    width, height = 650, 245
    x, y = _centered_position(api, width, height)
    hwnd = user32.CreateWindowExW(
        _WS_EX_DLGMODALFRAME,
        _text(class_name),
        _text("WinUx Update Source"),
        _WS_OVERLAPPED | _WS_CAPTION | _WS_SYSMENU | _WS_VISIBLE,
        x, y, width, height,
        None, None,
        api["kernel32"].GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        return None

    body = (
        "The configured WinUx update folder could not be found or is incomplete.\r\n"
        "Enter the full path to the shared WinUx deployment. The path will be "
        "saved and reused on future launches."
    )
    controls["label"] = _create_control(
        api, hwnd, "STATIC", body,
        _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
        22, 18, 600, 54,
    )
    controls["edit"] = _create_control(
        api, hwnd, "EDIT", current_path or "",
        _WS_CHILD | _WS_VISIBLE | _WS_TABSTOP | _WS_BORDER | _ES_AUTOHSCROLL,
        22, 84, 600, 28, 1201,
    )
    controls["save"] = _create_control(
        api, hwnd, "BUTTON", "Save Path",
        _WS_CHILD | _WS_VISIBLE | _WS_TABSTOP | _BS_DEFPUSHBUTTON,
        410, 145, 100, 32, 1101,
    )
    controls["local"] = _create_control(
        api, hwnd, "BUTTON", "Use Local",
        _WS_CHILD | _WS_VISIBLE | _WS_TABSTOP,
        520, 145, 100, 32, 1102,
    )
    _apply_font(
        api, hwnd, controls["label"], controls["edit"], controls["save"], controls["local"]
    )
    user32.ShowWindow(hwnd, _SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(controls["edit"])
    user32.SendMessageW(controls["edit"], 0x00B1, 0, -1)  # EM_SETSEL: select all
    _run_modal_loop(api, state)
    _unregister_class(api, class_name)
    del wc, wndproc
    return state["result"]


def show_invalid_update_source(path):
    api = _win32()
    if api is None:
        return
    api["user32"].MessageBoxW(
        None,
        _text(
            "The selected folder is not a complete WinUx deployment:\n\n{0}\n\n"
            "Choose a folder containing VERSION, WinUx_plugin.py, run_winux.py, "
            "and the WinUx application folder.".format(path)
        ),
        _text("WinUx Update Source"),
        0x00000030 | 0x00010000 | 0x00002000,
    )


class UpdateProgressDialog(object):
    """Responsive native progress dialog owned by a dedicated UI thread.

    The update installer performs potentially long blocking filesystem work.  A
    Win32 window created on that same thread can fail to paint or appear frozen
    until the next progress callback.  This dialog therefore owns a dedicated
    message-pump thread; the installer thread only posts progress updates.
    """

    _MIN_VISIBLE_SECONDS = 0.85

    def __init__(self, local_version, server_version):
        self._api = _win32()
        self._hwnd = None
        self._bar = None
        self._status = None
        self._percent = None
        self._closed = False
        self._wndproc = None
        self._wc = None
        self._class_name = None
        self._ready = threading.Event()
        self._finished = threading.Event()
        self._state_lock = threading.Lock()
        self._pending_percent = 0
        self._pending_message = "Preparing update..."
        self._created_at = None
        self._thread = None
        self._startup_error = None
        if self._api is None:
            return

        self._thread = threading.Thread(
            target=self._ui_thread_main,
            args=(local_version, server_version),
            name="WinUxUpdateProgressUI",
        )
        self._thread.daemon = True
        self._thread.start()

        # Do not begin copy/install until the native window and controls exist.
        # This guarantees that Update Now visibly transitions to the progress UI.
        self._ready.wait(5.0)
        if self._startup_error is not None:
            raise RuntimeError(
                "WinUx update progress dialog could not start: {}".format(
                    self._startup_error
                )
            )
        if not self._hwnd:
            raise RuntimeError("WinUx update progress dialog window was not created.")

    def _apply_pending_update(self):
        if not self._hwnd or self._closed:
            return
        with self._state_lock:
            value = max(0, min(100, int(self._pending_percent)))
            message = self._pending_message
        user32 = self._api["user32"]
        if self._bar:
            user32.SendMessageW(self._bar, _PBM_SETPOS, value, 0)
        if self._percent:
            user32.SetWindowTextW(self._percent, _text("{0}%".format(value)))
        if self._status and message:
            user32.SetWindowTextW(self._status, _text(message))
        user32.UpdateWindow(self._hwnd)

    def _ui_thread_main(self, local_version, server_version):
        api = self._api
        user32 = api["user32"]
        class_name = _next_dialog_class_name("WinUxUpdateProgressDialog")
        self._class_name = class_name

        try:
            def window_proc(hwnd, message, wparam, lparam):
                if message == _WM_PROGRESS_UPDATE:
                    self._apply_pending_update()
                    return 0
                if message == _WM_PROGRESS_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                # The updater controls lifetime. Ignore the title-bar X while
                # files are being validated/replaced so installation cannot be
                # interrupted halfway through a transaction.
                if message == _WM_CLOSE:
                    return 0
                if message == _WM_DESTROY:
                    self._closed = True
                    try:
                        user32.PostQuitMessage(0)
                    except Exception:
                        pass
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            self._wndproc = api["WNDPROC"](window_proc)
            self._wc = _register_class(api, class_name, self._wndproc)
            width, height = 590, 230
            x, y = _centered_position(api, width, height)
            self._hwnd = user32.CreateWindowExW(
                _WS_EX_DLGMODALFRAME | _WS_EX_TOPMOST,
                _text(class_name),
                _text("Updating WinUx"),
                _WS_OVERLAPPED | _WS_CAPTION | _WS_SYSMENU | _WS_VISIBLE,
                x, y, width, height,
                None, None,
                api["kernel32"].GetModuleHandleW(None),
                None,
            )
            if not self._hwnd:
                raise RuntimeError("CreateWindowExW returned NULL.")

            title = "Updating WinUx {0}  ->  {1}".format(
                local_version or "unknown", server_version or "unknown"
            )
            header = _create_control(
                api, self._hwnd, "STATIC", title,
                _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
                24, 22, 535, 24,
            )
            self._status = _create_control(
                api, self._hwnd, "STATIC", "Preparing update...",
                _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
                24, 58, 535, 26,
            )
            self._bar = _create_control(
                api, self._hwnd, "msctls_progress32", "",
                _WS_CHILD | _WS_VISIBLE,
                24, 100, 475, 26,
            )
            self._percent = _create_control(
                api, self._hwnd, "STATIC", "0%",
                _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
                512, 103, 48, 24,
            )
            hint = _create_control(
                api, self._hwnd, "STATIC",
                "WinUx is updating locally. Abaqus/CAE remains available.",
                _WS_CHILD | _WS_VISIBLE | _SS_LEFT,
                24, 143, 535, 24,
            )
            _apply_font(api, self._hwnd, header, self._status, self._percent, hint)
            if self._bar:
                user32.SendMessageW(self._bar, _PBM_SETRANGE32, 0, 100)
                user32.SendMessageW(self._bar, _PBM_SETPOS, 0, 0)

            self._created_at = time.time()
            user32.ShowWindow(self._hwnd, _SW_SHOW)
            try:
                user32.BringWindowToTop(self._hwnd)
            except Exception:
                pass
            user32.SetForegroundWindow(self._hwnd)
            user32.UpdateWindow(self._hwnd)
            self._ready.set()

            # A blocking message loop is correct here because this is a
            # dedicated progress UI thread, never the Abaqus/CAE thread and
            # never the installer thread.
            msg = api["wintypes"].MSG()
            ctypes = api["ctypes"]
            while True:
                result = int(user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            self._closed = True
            self._finished.set()
            if self._class_name:
                _unregister_class(api, self._class_name)

    def update(self, percent, message=None):
        if self._api is None or self._closed:
            return
        with self._state_lock:
            self._pending_percent = max(0, min(100, int(percent)))
            if message:
                self._pending_message = _text(message)
        hwnd = self._hwnd
        if hwnd:
            # Asynchronous post: long file copies never wait on the UI thread.
            self._api["user32"].PostMessageW(hwnd, _WM_PROGRESS_UPDATE, 0, 0)

    def close(self):
        if self._api is None or self._closed:
            return
        # Very small updates can finish in a fraction of a second. Keep the
        # dialog visible long enough that users can actually see the transition
        # and the final state instead of perceiving that no progress UI existed.
        if self._created_at is not None:
            remaining = self._MIN_VISIBLE_SECONDS - (time.time() - self._created_at)
            if remaining > 0:
                time.sleep(remaining)
        hwnd = self._hwnd
        if hwnd:
            self._api["user32"].PostMessageW(hwnd, _WM_PROGRESS_CLOSE, 0, 0)
        self._finished.wait(3.0)
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(0.2)
            except Exception:
                pass

def create_progress_dialog(local_version, server_version):
    return UpdateProgressDialog(local_version, server_version)


__all__ = [
    "UpdateProgressDialog",
    "confirm_update",
    "create_progress_dialog",
    "prompt_update_source",
    "show_invalid_update_source",
]
