"""Windows Rich Edit fields for the regex workbench (no extra process/runtime).

The native child owns text, selection, IME, clipboard and undo. Formatting uses
TOM's suspended undo recording and preserves the native selection/scroll state.
DearUIQt retains layout/lifetime ownership through a QFrame placeholder.
"""
from __future__ import annotations

import ctypes
from bisect import bisect_left
from ctypes import wintypes as wt
import os
import uuid

from DearUIQt.core import Signal
from DearUIQt.widgets import QFrame


class _Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_long), ('end', ctypes.c_long)]


class _CharFormat(ctypes.Structure):
    _fields_ = [('size', wt.UINT), ('mask', wt.DWORD), ('effects', wt.DWORD),
        ('height', ctypes.c_long), ('offset', ctypes.c_long), ('foreground', wt.DWORD),
        ('charset', wt.BYTE), ('pitch', wt.BYTE), ('face', wt.WCHAR * 32),
        ('weight', wt.WORD), ('spacing', ctypes.c_short), ('background', wt.DWORD),
        ('locale', wt.DWORD), ('reserved', wt.DWORD), ('style', ctypes.c_short),
        ('kerning', wt.WORD), ('underline', wt.BYTE), ('animation', wt.BYTE),
        ('author', wt.BYTE), ('underline_color', wt.BYTE)]


def utf16_offsets(text):
    """Map Python character positions to Rich Edit UTF-16 positions (LF = CR)."""
    result = [0]
    for char in str(text):
        result.append(result[-1] + (2 if ord(char) > 0xffff else 1))
    return result


def _rgb(color):
    return int(color[0]) | (int(color[1]) << 8) | (int(color[2]) << 16)


def _com_method(pointer, index, result, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])


_PARENT_CLIP_LEASES = {}
_MSFTEDIT_HANDLE = 0


class RegexRichEdit(QFrame):
    """A genuine rich-text input, clipped inside its DearUIQt owner HWND."""

    def __init__(self, text='', *, parent, owner_handle, after=None, multiline=False,
                 readonly=False, width=-1, height=28, callback=None, scrollbars=True, wrap=False,
                 alignment='left'):
        if os.name != 'nt':
            raise RuntimeError('Inline regex coloring requires Windows Rich Edit')
        super().__init__(parent=parent, after=after, width=width, height=height,
                         frame_shape=QFrame.StyledPanel, no_scrollbar=True,
                         no_scroll_with_mouse=True)
        self.textChanged = Signal(self)
        self._text = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
        self._owner_handle = owner_handle
        self._multiline = bool(multiline)
        self._readonly = bool(readonly)
        self._scrollbars = bool(scrollbars)
        self._wrap = bool(wrap)
        if alignment not in ('left', 'center'):
            raise ValueError('Unsupported regex editor alignment: {}'.format(alignment))
        self._alignment = alignment
        self._callback = callback
        self.hwnd = 0
        self._owner = 0
        self._procedure = None
        self._old_procedure = 0
        self._document = ctypes.c_void_p()
        self._format_signature = None
        self._pending_focus = False
        self._native_focus_edge = False
        self._composing = False
        self._pending_key = None
        self._last_geometry = None
        self._last_clip = None
        self._visible_native = False
        self._user32 = ctypes.windll.user32
        self._prepare_api()

    def _prepare_api(self):
        user = self._user32
        user.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
        user.CreateWindowExW.restype = wt.HWND
        user.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t
        user.GetWindowTextLengthW.argtypes = [wt.HWND]
        user.GetWindowTextLengthW.restype = ctypes.c_int
        user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user.GetWindowTextW.restype = ctypes.c_int
        user.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
        user.GetFocus.restype = wt.HWND
        user.GetForegroundWindow.restype = wt.HWND
        user.SetFocus.argtypes = [wt.HWND]
        user.SetFocus.restype = wt.HWND
        user.DestroyWindow.argtypes = [wt.HWND]
        user.IsWindow.argtypes = [wt.HWND]
        user.IsWindow.restype = wt.BOOL
        user.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
        user.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
        user.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wt.UINT]
        user.SetWindowRgn.argtypes = [wt.HWND, wt.HANDLE, wt.BOOL]
        gdi = ctypes.windll.gdi32
        gdi.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi.CreateRectRgn.restype = wt.HANDLE
        gdi.DeleteObject.argtypes = [wt.HANDLE]
        self._get_long = user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.GetWindowLongW
        self._set_long = user.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.SetWindowLongW
        self._get_long.argtypes = [wt.HWND, ctypes.c_int]
        self._get_long.restype = ctypes.c_ssize_t
        self._set_long.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_long.restype = ctypes.c_ssize_t
        user.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user.CallWindowProcW.restype = ctypes.c_ssize_t

    def _send(self, message, wparam=0, lparam=0):
        if not isinstance(lparam, int):
            lparam = ctypes.cast(lparam, ctypes.c_void_p).value or 0
        return self._user32.SendMessageW(wt.HWND(self.hwnd), message, wparam, lparam)

    def _create(self, owner):
        global _MSFTEDIT_HANDLE
        kernel = ctypes.windll.kernel32
        kernel.LoadLibraryW.argtypes = [wt.LPCWSTR]
        kernel.LoadLibraryW.restype = wt.HMODULE
        if not _MSFTEDIT_HANDLE:
            _MSFTEDIT_HANDLE = kernel.LoadLibraryW('Msftedit.dll')
        if not _MSFTEDIT_HANDLE:
            raise RuntimeError('Windows Msftedit.dll is unavailable')
        # DearUIQt owns the flat outer border; avoid Rich Edit's legacy sunken
        # Win32 frame, which looks unlike the regex101 reference.
        style = 0x40000000 | 0x10000000 | 0x00010000 | 0x0080
        if self._alignment == 'center':
            style |= 0x0001  # ES_CENTER: center every paragraph in the line gutter.
        if self._multiline:
            style |= 0x0004 | 0x0040 | 0x1000
            if self._scrollbars:
                style |= 0x00200000
                if not self._wrap:
                    style |= 0x00100000
        if self._readonly:
            style |= 0x0800
        hwnd = self._user32.CreateWindowExW(0, 'RICHEDIT50W', '', style,
            0, 0, 1, 1, wt.HWND(owner), None, None, None)
        if not hwnd:
            raise RuntimeError('Could not create the inline regex editor')
        self.hwnd, self._owner = int(hwnd), int(owner)
        lease = _PARENT_CLIP_LEASES.get(owner)
        if lease is None:
            old = int(self._get_long(wt.HWND(owner), -16))
            lease = _PARENT_CLIP_LEASES[owner] = [0, not bool(old & 0x02000000), None]
            self._set_long(wt.HWND(owner), -16, old | 0x02000000)  # WS_CLIPCHILDREN
            try:
                lease[2] = self._host_focus_hook(owner)
            except Exception:
                self._set_long(wt.HWND(owner), -16, old)
                del _PARENT_CLIP_LEASES[owner]
                self._user32.DestroyWindow(wt.HWND(self.hwnd))
                self.hwnd = 0
                raise
        lease[0] += 1
        self._send(0x0435, 0, 0x7fffffff)  # EM_EXLIMITTEXT: do not silently truncate
        self._send(0x0443, 0, _rgb((255, 255, 255)))  # EM_SETBKGNDCOLOR
        if self._multiline:
            self._send(0x0448, 0, 0 if self._wrap else 1)  # EM_SETTARGETDEVICE
        self._user32.SetWindowTextW(wt.HWND(self.hwnd), self._text.replace('\n', '\r\n'))
        self._send(0x00B9, 0)  # EM_SETMODIFY
        self._install_procedure()
        self._get_document()
        if not self._document.value:
            self.close_native()
            raise RuntimeError('Windows Rich Edit did not provide its text formatting interface')
        self._format_signature = None
        self._visible_native = True

    def _host_focus_hook(self, owner):
        """A parent-client click must return keyboard focus from its child edit.

        Use the common-controls subclass API so other renderer/ownership hooks
        keep their own procedures and can be independently removed.
        """
        user = self._user32
        common = ctypes.windll.comctl32
        prototype = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT,
            wt.WPARAM, wt.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        common.SetWindowSubclass.argtypes = [wt.HWND, prototype, ctypes.c_size_t, ctypes.c_size_t]
        common.SetWindowSubclass.restype = wt.BOOL
        common.RemoveWindowSubclass.argtypes = [wt.HWND, prototype, ctypes.c_size_t]
        common.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        common.DefSubclassProc.restype = ctypes.c_ssize_t
        user.IsChild.argtypes = [wt.HWND, wt.HWND]
        user.IsChild.restype = wt.BOOL

        @prototype
        def callback(window, message, wparam, lparam, subclass_id, reference):
            if message in (0x0201, 0x0204):  # Client L/R press, not a child press.
                focused = user.GetFocus()
                if focused and user.IsChild(window, focused):
                    user.SetFocus(window)
            return common.DefSubclassProc(window, message, wparam, lparam)

        if not common.SetWindowSubclass(wt.HWND(owner), callback, 0x57585245, 0):
            raise RuntimeError('Could not attach regex editor focus routing')
        return callback

    def _install_procedure(self):
        self._old_procedure = int(self._get_long(wt.HWND(self.hwnd), -4))
        prototype = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        @prototype
        def procedure(window, message, wparam, lparam):
            if message == 0x0007:  # WM_SETFOCUS: synchronize retained focus on the UI turn.
                self._native_focus_edge = True
            if message == 0x0302:  # WM_PASTE: accept text, not embedded RTF/OLE.
                self._send(0x0440, 13, 0)  # EM_PASTESPECIAL / CF_UNICODETEXT
                return 0
            if message == 0x010D:  # WM_IME_STARTCOMPOSITION
                self._composing = True
            elif message == 0x010E:
                self._composing = False
            elif message == 0x0100:  # WM_KEYDOWN: preserve editor ownership
                if (wparam == ord('V') and self._user32.GetKeyState(0x11) & 0x8000
                        or wparam == 0x2D and self._user32.GetKeyState(0x10) & 0x8000):
                    self._send(0x0440, 13, 0)
                    return 0
                if wparam in (9, 27):
                    self._pending_key = ('tab', bool(self._user32.GetKeyState(0x10) & 0x8000)) if wparam == 9 else ('escape', False)
                    return 0
                if wparam == 13 and not self._multiline:
                    return 0
            elif message == 0x0102 and (wparam in (9, 27, 22) or wparam == 13 and not self._multiline):
                return 0  # WM_CHAR paired with the intercepted navigation key
            return self._user32.CallWindowProcW(ctypes.c_void_p(self._old_procedure),
                                                window, message, wparam, lparam)

        self._procedure = procedure
        self._set_long(wt.HWND(self.hwnd), -4, ctypes.cast(procedure, ctypes.c_void_p).value)

    def _get_document(self):
        ole = ctypes.c_void_p()
        if not self._send(0x043C, 0, ctypes.byref(ole)) or not ole.value:  # EM_GETOLEINTERFACE
            return
        iid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID('8cc497c0-a1df-11ce-8098-00aa0047be5d').bytes_le)
        try:
            _com_method(ole, 0, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(
                ole, ctypes.byref(iid), ctypes.byref(self._document))
        finally:
            _com_method(ole, 2, wt.ULONG)(ole)

    def text(self):
        if self.hwnd:
            length = self._user32.GetWindowTextLengthW(wt.HWND(self.hwnd))
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(wt.HWND(self.hwnd), buffer, length + 1)
            return buffer.value.replace('\r\n', '\n').replace('\r', '\n')
        return self._text

    toPlainText = text

    def setText(self, value):
        value = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
        if value == self.text():
            return
        self._text = value
        if self.hwnd:
            self._user32.SetWindowTextW(wt.HWND(self.hwnd), value.replace('\n', '\r\n'))
        self._format_signature = None

    setPlainText = setText

    def replace_prefix(self, end, prefix):
        """Replace only a flag prefix as one undoable native text edit."""
        text = self.text()
        if not self.hwnd:
            self.setText(prefix + text[end:])
            return
        selection = _Range()
        self._send(0x0434, 0, ctypes.byref(selection))
        scroll = self.scroll_position()
        native_selection, flags = ctypes.c_void_p(), ctypes.c_long()
        _com_method(self._document, 8, ctypes.c_long, ctypes.c_void_p)(
            self._document, ctypes.byref(native_selection))
        if native_selection.value:
            _com_method(native_selection, 58, ctypes.c_long, ctypes.c_void_p)(
                native_selection, ctypes.byref(flags))
        old_end = utf16_offsets(text)[end]
        new_end = utf16_offsets(prefix)[-1]
        self._send(0x0458)  # EM_STOPGROUPTYPING: separate checkbox edit from typing.
        target = _Range(0, old_end)
        self._send(0x0437, 0, ctypes.byref(target))
        buffer = ctypes.create_unicode_buffer(prefix)
        self._send(0x00C2, 1, ctypes.byref(buffer))  # EM_REPLACESEL, undo enabled.
        self._send(0x0458)
        def shifted(position):
            return position + new_end - old_end if position >= old_end else min(position, new_end)
        selection.start, selection.end = shifted(selection.start), shifted(selection.end)
        self._send(0x0437, 0, ctypes.byref(selection))
        if native_selection.value:
            _com_method(native_selection, 59, ctypes.c_long, ctypes.c_long)(native_selection, flags.value)
            _com_method(native_selection, 2, wt.ULONG)(native_selection)
        self.set_scroll_position(*scroll)
        self._text = self.text()
        self._format_signature = None

    def hasFocus(self):
        return bool(self.hwnd and int(self._user32.GetFocus() or 0) == self.hwnd)

    def caret_position(self):
        """Return the active selection end in Python (not UTF-16) offsets."""
        if not self.hwnd:
            return 0
        selection = _Range()
        self._send(0x0434, 0, ctypes.byref(selection))
        native, flags = ctypes.c_void_p(), ctypes.c_long()
        _com_method(self._document, 8, ctypes.c_long, ctypes.c_void_p)(
            self._document, ctypes.byref(native))
        if native.value:
            try:
                _com_method(native, 58, ctypes.c_long, ctypes.c_void_p)(native, ctypes.byref(flags))
            finally:
                _com_method(native, 2, wt.ULONG)(native)
        position = selection.start if flags.value & 1 else selection.end
        text = self.text()
        if getattr(self, '_caret_offset_text', None) != text:
            self._caret_offsets = utf16_offsets(text)
            self._caret_offset_text = text
        return bisect_left(self._caret_offsets, position)

    def scroll_position(self):
        point = wt.POINT()
        if self.hwnd:
            self._send(0x04DD, 0, ctypes.byref(point))
        return point.x, point.y

    def set_scroll_position(self, x, y):
        if self.hwnd and (int(x), int(y)) != self.scroll_position():
            point = wt.POINT(int(x), int(y))
            self._send(0x04DE, 0, ctypes.byref(point))

    def reveal_position(self, position):
        """Scroll a Python character offset into view without moving the caret.

        EM_POSFROMCHAR also handles the insertion position at end-of-text, so
        zero-width matches do not require fake characters or a selection.
        """
        text = self.text()
        if not self.hwnd or not self._visible_native or self._composing:
            return False
        if not 0 <= position <= len(text):
            return False
        point, rect = wt.POINT(), wt.RECT()
        self._send(0x00D6, ctypes.cast(ctypes.byref(point), ctypes.c_void_p).value,
                   utf16_offsets(text)[position])
        self._user32.GetClientRect(wt.HWND(self.hwnd), ctypes.byref(rect))
        x, y = self.scroll_position()
        # Reserve one line below the target rather than clipping its baseline.
        left, right = 4, max(4, rect.right - 20)
        top, bottom = 4, max(4, rect.bottom - 24)
        dx = point.x - min(right, max(left, point.x))
        dy = point.y - min(bottom, max(top, point.y))
        self.set_scroll_position(max(0, x + dx), max(0, y + dy))
        return True

    def setFocus(self):
        self._pending_focus = True
        self._apply_focus()
        return self

    def _apply_focus(self):
        if self._pending_focus and self.hwnd:
            self._pending_focus = False
            if self._visible_native and int(self._user32.GetForegroundWindow() or 0) == self._owner:
                self._user32.SetFocus(wt.HWND(self.hwnd))

    def sync_native(self, *, hidden=False):
        """UI-thread geometry/text synchronization; never activates a background HWND."""
        if self._deleted:
            return None
        rect = self.globalGeometry().adjusted(1, 1, -1, -1)
        clip = self.globalGeometry(clipped=True).intersected(rect)
        visible = not hidden and self.isVisible() and not clip.isEmpty()
        current = self.tag
        while visible and current:
            visible = bool(self.backend.is_item_shown(current))
            current = self.backend.get_item_parent(current)
        if not visible:
            if self.hwnd and self._visible_native:
                self._user32.ShowWindow(wt.HWND(self.hwnd), 0)
                self._visible_native = False
            return None
        owner = int(self._owner_handle() or 0)
        if not owner:
            return None
        if not self.hwnd:
            self._create(owner)
        point = wt.POINT(rect.left(), rect.top())
        self._user32.ScreenToClient(wt.HWND(owner), ctypes.byref(point))
        geometry = (point.x, point.y, rect.width(), rect.height())
        if geometry != self._last_geometry or not self._visible_native:
            self._user32.SetWindowPos(wt.HWND(self.hwnd), None, *geometry, 0x0014 | 0x0040)
            self._last_geometry = geometry
            self._visible_native = True
        clipped = (max(0, clip.left() - rect.left()), max(0, clip.top() - rect.top()),
                   min(rect.width(), clip.right() - rect.left() + 1),
                   min(rect.height(), clip.bottom() - rect.top() + 1))
        if clipped != self._last_clip:
            region = ctypes.windll.gdi32.CreateRectRgn(*clipped)
            if not self._user32.SetWindowRgn(wt.HWND(self.hwnd), region, True):
                ctypes.windll.gdi32.DeleteObject(region)
            self._last_clip = clipped
        self._apply_focus()
        if self._native_focus_edge and self.hasFocus():
            # Move ImGui navigation away from the last plain input as well.
            # Otherwise that input can keep a stale blue focus frame/active
            # editing buffer while Windows correctly focuses this child HWND.
            root = self.tag
            while self.backend.get_item_parent(root):
                root = self.backend.get_item_parent(root)
            self.backend.focus_item(root)
            from DearUIQt.core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.canFocusWidget(self):
                application._set_focus_widget(self)
            self._user32.SetFocus(wt.HWND(self.hwnd))
            self._native_focus_edge = False
        value = self.text()
        if value != self._text and not self._composing:
            self._text = value
            self._format_signature = None
            self.textChanged.emit(value)
            if self._callback is not None:
                self._callback()
        action, self._pending_key = self._pending_key, None
        return action

    def set_colors(self, spans, *, default_foreground=(35, 40, 46), default_background=(255, 255, 255)):
        """spans: (Python start, end, foreground RGB, background RGB)."""
        if not self.hwnd or self._composing or not self._document.value:
            return False
        text = self.text()
        spans = tuple((int(a), int(b), tuple(fg[:3]), tuple(bg[:3])) for a, b, fg, bg in spans)
        signature = (text, spans, tuple(default_foreground), tuple(default_background))
        if signature == self._format_signature:
            return True
        selection, scroll = _Range(), wt.POINT()
        self._send(0x0434, 0, ctypes.byref(selection))  # EM_EXGETSEL
        self._send(0x04DD, 0, ctypes.byref(scroll))  # EM_GETSCROLLPOS
        modified = self._send(0x00B8)
        offsets = utf16_offsets(text)
        native_selection = ctypes.c_void_p()
        selection_flags = ctypes.c_long()
        _com_method(self._document, 8, ctypes.c_long, ctypes.c_void_p)(
            self._document, ctypes.byref(native_selection))  # ITextDocument::GetSelection
        if native_selection.value:
            _com_method(native_selection, 58, ctypes.c_long, ctypes.c_void_p)(
                native_selection, ctypes.byref(selection_flags))  # ITextSelection::GetFlags
        undo = _com_method(self._document, 22, ctypes.c_long, ctypes.c_long, ctypes.c_void_p)
        # tomSuspend/tomResume preserve the existing queue. tomFalse/tomTrue
        # disable/re-enable undo and can discard the user's earlier edits.
        if undo(self._document, -9999995, None) < 0:
            if native_selection.value:
                _com_method(native_selection, 2, wt.ULONG)(native_selection)
            return False
        self._send(0x000B, 0)  # WM_SETREDRAW
        try:
            def paint(start, end, foreground, background, default=False):
                selected = _Range(start, end)
                self._send(0x0437, 0, ctypes.byref(selected))  # EM_EXSETSEL
                fmt = _CharFormat()
                fmt.size = ctypes.sizeof(fmt)
                fmt.mask = 0x40000000 | 0x04000000  # CFM_COLOR | CFM_BACKCOLOR
                fmt.foreground, fmt.background = _rgb(foreground), _rgb(background)
                if default:
                    fmt.mask |= 0x20000000 | 0x80000000  # CFM_FACE | CFM_SIZE
                    fmt.face, fmt.height = 'Consolas', 200
                self._send(0x0444, 1, ctypes.byref(fmt))  # EM_SETCHARFORMAT / SCF_SELECTION

            paint(0, -1, default_foreground, default_background, True)
            for start, end, foreground, background in spans:
                if 0 <= start < end <= len(text):
                    paint(offsets[start], offsets[end], foreground, background)
            self._format_signature = signature
        finally:
            self._send(0x0437, 0, ctypes.byref(selection))
            if native_selection.value:
                _com_method(native_selection, 59, ctypes.c_long, ctypes.c_long)(
                    native_selection, selection_flags.value)  # Preserve active selection end.
                _com_method(native_selection, 2, wt.ULONG)(native_selection)
            self._send(0x04DE, 0, ctypes.byref(scroll))  # EM_SETSCROLLPOS
            self._send(0x00B9, modified)
            undo(self._document, -9999994, None)
            self._send(0x000B, 1)
            self._user32.InvalidateRect(wt.HWND(self.hwnd), None, False)
        return True

    def close_native(self):
        if not self.hwnd:
            return
        if self._document.value:
            _com_method(self._document, 2, wt.ULONG)(self._document)
            self._document = ctypes.c_void_p()
        self._set_long(wt.HWND(self.hwnd), -4, self._old_procedure)
        self._user32.DestroyWindow(wt.HWND(self.hwnd))
        self.hwnd = 0
        self._procedure = None
        lease = _PARENT_CLIP_LEASES.get(self._owner)
        if lease is not None:
            lease[0] -= 1
            if lease[0] == 0:
                live = bool(self._user32.IsWindow(wt.HWND(self._owner)))
                if live and lease[2] is not None:
                    ctypes.windll.comctl32.RemoveWindowSubclass(wt.HWND(self._owner), lease[2], 0x57585245)
                if live and lease[1]:
                    style = int(self._get_long(wt.HWND(self._owner), -16))
                    self._set_long(wt.HWND(self._owner), -16, style & ~0x02000000)
                del _PARENT_CLIP_LEASES[self._owner]

    def delete(self):
        self.close_native()
        return super().delete()
