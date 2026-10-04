"""Cached Windows cursor-file loading and drag-copy cursor composition."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os

class WindowsCursorFile:
    """Load and cache native Windows ``.cur``/``.ani`` files.

    The requested dimensions default to the current Windows cursor metrics, so
    a custom cursor has the same visual size as the active system cursor.
    Passing an explicit size is still supported for callers that need it.
    """

    IMAGE_CURSOR = 2
    LR_LOADFROMFILE = 0x0010
    SM_CXCURSOR = 13
    SM_CYCURSOR = 14
    _cache = {}

    @classmethod
    def system_size(cls):
        if os.name != "nt":
            return 0, 0
        user32 = ctypes.windll.user32
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        width = max(1, int(user32.GetSystemMetrics(cls.SM_CXCURSOR)))
        height = max(1, int(user32.GetSystemMetrics(cls.SM_CYCURSOR)))
        return width, height

    @classmethod
    def load(cls, path, width=None, height=None):
        if os.name != "nt":
            return None

        normalized = os.path.normcase(os.path.abspath(os.path.expandvars(path)))
        if not os.path.exists(normalized):
            return None

        system_width, system_height = cls.system_size()
        width = max(1, int(width or system_width))
        height = max(1, int(height or system_height))
        cache_key = (normalized, width, height)

        cached = cls._cache.get(cache_key)
        if cached:
            return cached

        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE

        # Supplying the current SM_CXCURSOR/SM_CYCURSOR values prevents the
        # cursor file's authored dimensions from appearing larger or smaller
        # than the cursor currently configured in Windows. LoadImageW keeps an
        # ANI cursor animated while it is used through SetCursor.
        handle = user32.LoadImageW(
            None, normalized, cls.IMAGE_CURSOR, width, height, cls.LR_LOADFROMFILE
        )
        if handle:
            cls._cache[cache_key] = handle
        return handle or None

    @classmethod
    def create_copy_cursor(cls, base_cursor=None):
        """Create an Explorer/OLE-like copy cursor from the system arrow.

        Windows does not expose a public ``IDC_COPY`` cursor. Native OLE drag
        and drop composes the effect badge internally. This method performs
        the same visual composition: current system arrow + a small ``+``
        badge, using the current ``SM_CXCURSOR``/``SM_CYCURSOR`` dimensions.
        """
        if os.name != "nt":
            return None

        width, height = cls.system_size()
        cache_key = ("__drag_drop_copy__", width, height, int(base_cursor or 0))
        cached = cls._cache.get(cache_key)
        if cached:
            return cached

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        IMAGE_CURSOR = 2
        LR_DEFAULTSIZE = 0x0040
        DI_NORMAL = 0x0003
        IDC_ARROW = 32512
        DIB_RGB_COLORS = 0
        BI_RGB = 0

        HCURSOR = wintypes.HANDLE
        HBITMAP = wintypes.HANDLE
        HDC = wintypes.HANDLE
        HGDIOBJ = wintypes.HANDLE

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", HBITMAP),
                ("hbmColor", HBITMAP),
            ]

        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        user32.LoadCursorW.restype = HCURSOR
        user32.DrawIconEx.argtypes = [HDC, ctypes.c_int, ctypes.c_int, HCURSOR, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
        user32.DrawIconEx.restype = wintypes.BOOL
        user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
        user32.CreateIconIndirect.restype = HCURSOR

        gdi32.CreateCompatibleDC.argtypes = [HDC]
        gdi32.CreateCompatibleDC.restype = HDC
        gdi32.CreateDIBSection.argtypes = [HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        gdi32.CreateDIBSection.restype = HBITMAP
        gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        gdi32.CreateBitmap.restype = HBITMAP
        gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
        gdi32.SelectObject.restype = HGDIOBJ
        gdi32.DeleteObject.argtypes = [HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        cursor = base_cursor or user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        if not cursor:
            return None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        dc = gdi32.CreateCompatibleDC(None)
        color_bitmap = gdi32.CreateDIBSection(None, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        mask_bitmap = gdi32.CreateBitmap(width, height, 1, 1, None)
        if not dc or not color_bitmap or not mask_bitmap or not bits.value:
            if color_bitmap:
                gdi32.DeleteObject(color_bitmap)
            if mask_bitmap:
                gdi32.DeleteObject(mask_bitmap)
            if dc:
                gdi32.DeleteDC(dc)
            return None

        old = gdi32.SelectObject(dc, color_bitmap)
        ctypes.memset(bits, 0, width * height * 4)
        user32.DrawIconEx(dc, 0, 0, cursor, width, height, 0, None, DI_NORMAL)

        # Draw a compact copy badge in the bottom-right area. Pixel values are
        # BGRA because the DIB section uses little-endian 32-bit pixels.
        pixels = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
        badge = max(9, min(width, height) // 3)
        cx = width - badge // 2 - 1
        cy = height - badge // 2 - 1
        radius = badge // 2
        for py in range(max(0, cy - radius), min(height, cy + radius + 1)):
            for px in range(max(0, cx - radius), min(width, cx + radius + 1)):
                dx, dy = px - cx, py - cy
                if dx * dx + dy * dy <= radius * radius:
                    i = (py * width + px) * 4
                    border = dx * dx + dy * dy >= max(0, radius - 1) ** 2
                    if border:
                        b, g, r = 45, 105, 45
                    else:
                        b, g, r = 80, 170, 55
                    pixels[i:i+4] = (b, g, r, 255)

        arm = max(1, badge // 7)
        span = max(2, badge // 3)
        for py in range(max(0, cy - arm), min(height, cy + arm + 1)):
            for px in range(max(0, cx - span), min(width, cx + span + 1)):
                i = (py * width + px) * 4
                pixels[i:i+4] = (255, 255, 255, 255)
        for py in range(max(0, cy - span), min(height, cy + span + 1)):
            for px in range(max(0, cx - arm), min(width, cx + arm + 1)):
                i = (py * width + px) * 4
                pixels[i:i+4] = (255, 255, 255, 255)

        gdi32.SelectObject(dc, old)
        icon_info = ICONINFO(False, 0, 0, mask_bitmap, color_bitmap)
        result = user32.CreateIconIndirect(ctypes.byref(icon_info))

        gdi32.DeleteObject(color_bitmap)
        gdi32.DeleteObject(mask_bitmap)
        gdi32.DeleteDC(dc)

        if result:
            cls._cache[cache_key] = result
        return result or None


