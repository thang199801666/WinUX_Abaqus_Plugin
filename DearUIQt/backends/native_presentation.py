"""Present native surfaces only after their first hidden layout has settled.

The custom renderer allocates HWNDs during a render, not at widget creation.
A thread-local pre-show hook cloaks those platform windows before USER32 can
expose their provisional frame. DWM still renders a cloaked window normally;
uncloaking after a stable render presents its completed contents atomically.
No desktop-wide hooks, sleeps, nested renders or opacity animation are used.
"""
from __future__ import annotations

import ctypes
import os
from collections import OrderedDict
from ctypes import wintypes
from dataclasses import dataclass

from .native_windows import NativeWindowBackend

_presentations = {}


class _Message(ctypes.Structure):
    _fields_ = [("lParam", wintypes.LPARAM), ("wParam", wintypes.WPARAM),
                ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]


class _WindowPos(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("insert_after", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]


@dataclass
class _PendingShow:
    prepare: object
    presented: object = None
    geometry: object = None
    frames: int = 0
    reuse_geometry: bool = False


class NativePresentation:
    def __init__(self, backend):
        self.backend = backend
        self.native = NativeWindowBackend(backend)
        self.pending = {}
        self.cloaked = set()
        self.popup_geometry = {}
        self._popup_procs = {}
        self._retired_procs = []
        self._hook = None
        self._hook_callback = None
        self._after_hidden = []
        self._retiring_windows = set()
        self._settled_geometry = OrderedDict()
        self._urgent_frames = 8

    def needs_frame(self):
        """Pending show/hide transactions must not wait for idle frame pacing."""
        return bool(self._urgent_frames > 0 and
                    (self.pending or self._after_hidden or self._retiring_windows))

    def retiring_windows(self):
        """Closing dialogs/popups not yet removed by the native renderer."""
        user32 = ctypes.windll.user32
        self._retiring_windows = {hwnd for hwnd in self._retiring_windows
                                 if user32.IsWindowVisible(wintypes.HWND(hwnd))}
        return tuple(self._retiring_windows)

    def after_windows_hidden(self, handles, callback):
        """Continue presentation after closing native HWNDs leave the screen.

        configure_item(show=False) is only a renderer request. Delivering a
        command immediately can create any kind of dialog before the old menu
        is destroyed, losing the owner's foreground slot in that transaction.
        """
        self._after_hidden.append((tuple(handles), callback))
        self._urgent_frames = 8

    def _deliver_after_hidden(self):
        user32 = ctypes.windll.user32
        waiting, self._after_hidden = self._after_hidden, []
        for handles, callback in waiting:
            if any(user32.IsWindowVisible(wintypes.HWND(hwnd)) for hwnd in handles):
                self._after_hidden.append((handles, callback))
            else:
                try:
                    callback()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Deferred native presentation failed')

    def _cloak(self, hwnd, enabled):
        if not hwnd:
            return False
        # The primary application viewport is never a presentation target.
        # Guard here as well as in the hook so future callers cannot
        # accidentally hide WinUx while presenting a secondary dialog.
        if enabled:
            try:
                if int(hwnd) == int(self.native.primaryWinId() or 0):
                    return False
            except Exception:
                pass
        value = wintypes.BOOL(bool(enabled))
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), 13, ctypes.byref(value), ctypes.sizeof(value))
        if result == 0:
            if enabled:
                self.cloaked.add(int(hwnd))
            else:
                self.cloaked.discard(int(hwnd))
            return True
        if not enabled and not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
            self.cloaked.discard(int(hwnd))
            return True
        return False

    def prepare(self, item, callback, *, presented=None, reuse_geometry=False):
        tag = self.backend.get_alias_id(item) if isinstance(item, str) else int(item)
        self.pending[tag] = _PendingShow(callback, presented, reuse_geometry=bool(reuse_geometry))
        self._urgent_frames = 8
        # A retained popup may already have an HWND from its previous opening.
        hwnd = self.native._rawWinId(tag)
        if hwnd:
            self._cloak(hwnd, True)

    def cancel(self, item):
        self._urgent_frames = 8
        tag = self.backend.get_alias_id(item) if isinstance(item, str) else int(item)
        self.pending.pop(tag, None)
        geometry = self.popup_geometry.pop(tag, None)
        if geometry is not None:
            self._retiring_windows.add(geometry[0])
        elif not self.native.isPrimaryItem(tag):
            try:
                hwnd = self.native._rawWinId(tag)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                hwnd = 0
            if hwnd:
                self._retiring_windows.add(hwnd)
        # Cloaks are released after the next renderer hide/destroy transaction,
        # never before it (which would flash the old native contents).

    def before_frame(self):
        if not self.pending or self._hook is not None:
            return
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE

        @callback_type
        def before_show(code, wparam, lparam):
            try:
                if code >= 0:
                    message = ctypes.cast(lparam, ctypes.POINTER(_Message)).contents
                    if message.message == 0x0018 and message.wParam:  # WM_SHOWWINDOW
                        # First-presentation cloaking belongs only to secondary
                        # native viewport HWNDs.  Never cloak the registered
                        # primary GLFW/WinUx window: on a cold first dialog the
                        # platform backend may emit WM_SHOWWINDOW for the owner
                        # in the same transaction, which previously made the
                        # application disappear until the modal was dismissed.
                        primary = int(self.native.primaryWinId() or 0)
                        candidate = int(message.hwnd or 0)
                        if candidate and candidate != primary:
                            name = ctypes.create_unicode_buffer(80)
                            user32.GetClassNameW(
                                wintypes.HWND(message.hwnd), name, len(name))
                            if name.value == "ImGui Platform":
                                self._cloak(message.hwnd, True)
            except (AttributeError, OSError, ValueError):
                pass
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._hook_callback = before_show
        self._hook = user32.SetWindowsHookExW(
            4, before_show, None, ctypes.windll.kernel32.GetCurrentThreadId())

    def _unhook(self):
        if self._hook:
            user32 = ctypes.windll.user32
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            user32.UnhookWindowsHookEx(wintypes.HANDLE(self._hook))
        self._hook = None
        self._hook_callback = None

    @staticmethod
    def _geometry(hwnd):
        user32 = ctypes.windll.user32
        outer, client = wintypes.RECT(), wintypes.RECT()
        if (user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(outer))
                and user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client))):
            return (outer.left, outer.top, outer.right, outer.bottom,
                    client.right, client.bottom)
        return None

    def pin_popup(self, item, hwnd, position, size):
        tag = self.backend.get_alias_id(item) if isinstance(item, str) else int(item)
        self.popup_geometry[tag] = (int(hwnd), tuple(map(int, (*position, *size))))
        if int(hwnd) in self._popup_procs:
            return
        user32 = ctypes.windll.user32
        getter = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
        setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        old_proc = getter(wintypes.HWND(hwnd), -4)
        proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        @proc_type
        def popup_proc(window, message, wparam, lparam):
            result = user32.CallWindowProcW(
                ctypes.c_void_p(old_proc), window, message, wparam, lparam)
            if message == 0x0046 and lparam:  # WM_WINDOWPOSCHANGING
                policy = self.popup_geometry.get(tag)
                if policy is not None and policy[0] == int(window):
                    pos = ctypes.cast(lparam, ctypes.POINTER(_WindowPos)).contents
                    x, y, width, height = policy[1]
                    if not pos.flags & 0x0002:
                        pos.x, pos.y = x, y
                    if not pos.flags & 0x0001:
                        pos.cx, pos.cy = width, height
            elif message == 0x0082:  # WM_NCDESTROY
                entry = self._popup_procs.pop(int(window), None)
                if entry is not None:
                    self._retired_procs.append(entry)
            return result

        self._popup_procs[int(hwnd)] = (old_proc, popup_proc)
        setter(wintypes.HWND(hwnd), -4, ctypes.cast(popup_proc, ctypes.c_void_p).value)

    def after_frame(self):
        try:
            self._settle_frame()
        finally:
            self._unhook()
            self._retired_procs.clear()
        self._deliver_after_hidden()
        self.retiring_windows()
        if self.pending or self._after_hidden or self._retiring_windows:
            self._urgent_frames = max(0, self._urgent_frames - 1)
        else:
            self._urgent_frames = 8

    def _settle_frame(self):
        held = set()
        for tag, ticket in tuple(self.pending.items()):
            if (not self.backend.does_item_exist(tag)
                    or not self.backend.is_item_shown(tag)):
                self.pending.pop(tag, None)
                continue
            hwnd = self.native._rawWinId(tag)
            if not hwnd:
                ticket.frames += 1
                if ticket.frames > 8:
                    self.pending.pop(tag, None)
                continue
            held.add(hwnd)
            if hwnd not in self.cloaked:
                self._cloak(hwnd, True)
            before = self._geometry(hwnd)
            try:
                ready = ticket.prepare()
            except Exception:
                # Never strand an invisible modal/input grab if an optional
                # platform preparation fails; reveal via the normal fallback.
                ready = True
                ticket.frames = 8
                import logging
                logging.getLogger(__name__).exception('Native first-presentation preparation failed')
            after = self._geometry(hwnd)
            ticket.frames += 1
            reference = ticket.geometry
            if reference is None and ticket.reuse_geometry:
                reference = self._settled_geometry.get(tag)
            stable = ready is not False and after is not None and before == after == reference
            ticket.geometry = after
            if stable or ticket.frames > 8:
                if ticket.reuse_geometry and stable:
                    self._settled_geometry[tag] = after
                    self._settled_geometry.move_to_end(tag)
                    while len(self._settled_geometry) > 64:
                        self._settled_geometry.popitem(last=False)
                self._cloak(hwnd, False)
                held.discard(hwnd)
                self.pending.pop(tag, None)
                if ticket.presented is not None:
                    ticket.presented()
        # Unrelated native surfaces on the same UI thread are not participants:
        # restore them in this very frame, before returning to the event loop.
        for hwnd in self.cloaked - held:
            self._cloak(hwnd, False)
        for tag in tuple(self.popup_geometry):
            if not self.backend.does_item_exist(tag) or not self.backend.is_item_shown(tag):
                self.popup_geometry.pop(tag, None)

    def close(self):
        self._unhook()
        self.pending.clear()
        self._after_hidden.clear()
        self._retiring_windows.clear()
        self.popup_geometry.clear()
        self._settled_geometry.clear()
        user32 = ctypes.windll.user32
        setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        for hwnd, (old_proc, _callback) in tuple(self._popup_procs.items()):
            if user32.IsWindow(wintypes.HWND(hwnd)):
                setter(wintypes.HWND(hwnd), -4, old_proc)
        self._popup_procs.clear()
        self._retired_procs.clear()
        for hwnd in tuple(self.cloaked):
            self._cloak(hwnd, False)
        self.cloaked.clear()


def presentation_for(backend, *, create=False):
    from . import _BackendProxy, get_backend
    if isinstance(backend, _BackendProxy):
        backend = get_backend()
    existing = _presentations.get(id(backend))
    if existing is not None or not create or os.name != "nt":
        return existing
    native = NativeWindowBackend(backend)
    if not native.isEnabled():
        return None
    enabled = wintypes.BOOL()
    try:
        if (ctypes.windll.dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled)) != 0
                or not enabled.value):
            return None
    except (AttributeError, OSError):
        return None
    existing = NativePresentation(backend)
    _presentations[id(backend)] = existing
    return existing


def release_presentation(backend):
    from . import _BackendProxy, get_backend
    if isinstance(backend, _BackendProxy):
        backend = get_backend()
    presentation = _presentations.pop(id(backend), None)
    if presentation is not None:
        presentation.close()
