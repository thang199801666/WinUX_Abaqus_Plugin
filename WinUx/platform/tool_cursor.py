"""Native tool cursors, including generated magnifying-glass zoom cursors."""
import ctypes
from ctypes import wintypes
import os


class ToolCursorHandles:
    SYSTEM_IDS = {'arrow': 32512, 'pick': 32515, 'color_pick': 32515, 'pan': 32649,
                  'pan_drag': 32646, 'move': 32646, 'point': 32649, 'delete': 32648}

    def __init__(self):
        self._handles = {}
        self._owned = []

    def get(self, mode):
        if os.name != 'nt' or mode is None:
            return None
        requested_mode = mode
        # ``pencil`` remains a compatibility alias for integrations that used
        # the legacy color-sampling cursor name. Share the native handle so
        # requesting both names cannot allocate two identical owned cursors.
        mode = 'color_pick' if mode == 'pencil' else mode
        if mode not in self._handles:
            user32 = ctypes.windll.user32
            user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            user32.LoadCursorW.restype = wintypes.HANDLE
            if mode == 'blank':
                handle = self._blank_cursor()
            elif mode == 'color_pick':
                handle = self._color_picker_cursor()
            else:
                handle = self._zoom_cursor(mode == 'zoom_in') if mode in ('zoom_in', 'zoom_out') else None
            self._handles[mode] = handle or user32.LoadCursorW(
                None, ctypes.c_void_p(self.SYSTEM_IDS.get(mode, 32512)))
        self._handles[requested_mode] = self._handles[mode]
        return self._handles[mode]

    def _blank_cursor(self):
        """A transparent cursor handle, without changing global ShowCursor counts."""
        user32 = ctypes.windll.user32
        width = max(32, user32.GetSystemMetrics(13))
        height = max(32, user32.GetSystemMetrics(14))
        size = ((width + 15) // 16) * 2 * height
        and_bits = (ctypes.c_ubyte * size)(*([255] * size))
        xor_bits = (ctypes.c_ubyte * size)()
        user32.CreateCursor.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        user32.CreateCursor.restype = wintypes.HANDLE
        cursor = user32.CreateCursor(None, 0, 0, width, height, and_bits, xor_bits)
        if cursor:
            self._owned.append(cursor)
        return cursor

    def _zoom_cursor(self, zoom_in):
        from PIL import Image, ImageDraw
        user32 = ctypes.windll.user32
        width = max(32, user32.GetSystemMetrics(13))
        height = max(32, user32.GetSystemMetrics(14))
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        scale = min(width, height) / 32
        thick = max(1, round(scale))
        box = tuple(round(value * scale) for value in (3, 3, 21, 21))
        handle = [tuple(round(value * scale) for value in point) for point in ((19, 19), (28, 28))]
        draw.line(handle, fill='white', width=5 * thick)
        draw.line(handle, fill='black', width=3 * thick)
        draw.ellipse(box, outline='white', width=4 * thick)
        draw.ellipse(box, outline='black', width=2 * thick)
        draw.line([(round(7*scale), round(12*scale)), (round(17*scale), round(12*scale))],
                  fill='black', width=2 * thick)
        if zoom_in:
            draw.line([(round(12*scale), round(7*scale)), (round(12*scale), round(17*scale))],
                       fill='black', width=2 * thick)
        return self._image_cursor(image, (round(12 * scale), round(12 * scale)))

    @staticmethod
    def color_picker_artwork(width=32, height=32):
        """Load the bundled Plot Digitizer pencil artwork for Pick Color.

        The resource is the coloured pencil approved for Plot Digitizer.  It is
        scaled to the current Windows cursor metrics and the graphite tip is
        used as the exact sampling hotspot.  Only the hotspot pixel itself is
        made transparent so the sampled source pixel remains visible.

        A small generated monochrome pencil is retained as a last-resort
        fallback for incomplete/legacy deployments where the PNG resource is
        missing.
        """
        from PIL import Image

        width, height = max(16, int(width)), max(16, int(height))
        try:
            from .resources import resource_path
            path = resource_path('PlotDigitizer_PickColorCursor.png', required=True)
            source = Image.open(path).convert('RGBA')
            bbox = source.getchannel('A').getbbox()
            if not bbox:
                raise ValueError('Pick Color cursor artwork is empty')
            source = source.crop(bbox)

            # Keep the approved pencil proportions and leave a one-pixel
            # transparent margin so antialiasing does not clip at high DPI.
            # Plot Digitizer uses a slightly smaller Pick Color cursor so the
            # sampled chart area stays more visible around the graphite tip.
            pad = max(1, round(min(width, height) / 32.0))
            usable_w = max(1, width - 2 * pad)
            usable_h = max(1, height - 2 * pad)
            shrink = 0.80
            ratio = min((usable_w * shrink) / source.width,
                        (usable_h * shrink) / source.height)
            target = (max(1, round(source.width * ratio)),
                      max(1, round(source.height * ratio)))
            source = source.resize(target, Image.Resampling.LANCZOS)
            image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            x0 = pad + max(0, (usable_w - target[0]) // 2)
            y0 = pad + max(0, (usable_h - target[1]) // 2)
            image.alpha_composite(source, (x0, y0))

            # Locate the lower-left graphite extremity.  Restrict the search to
            # opaque dark pixels so the red eraser can never become the hotspot.
            px = image.load()
            candidates = []
            for y in range(height):
                for x in range(width):
                    red, green, blue, alpha = px[x, y]
                    if alpha >= 96 and max(red, green, blue) <= 105:
                        candidates.append((y - x, y, -x, x, y))
            if not candidates:
                raise ValueError('Pick Color cursor graphite tip was not found')
            _score, _y, _nx, hx, hy = max(candidates)
            hotspot = (hx, hy)

            # Do not cover the exact source pixel being sampled.  Clearing one
            # antialiased tip pixel is visually imperceptible at cursor scale.
            image.putpixel(hotspot, (0, 0, 0, 0))
            return image, hotspot
        except Exception:
            return ToolCursorHandles._fallback_color_picker_artwork(width, height)

    @staticmethod
    def _fallback_color_picker_artwork(width=32, height=32):
        """Legacy generated pencil used only if the bundled PNG is unavailable."""
        from PIL import Image, ImageDraw

        width, height = max(16, int(width)), max(16, int(height))
        scale = min(width, height) / 32.0
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        def point(x, y):
            return round(x * scale), round(y * scale)

        def poly(points, *, fill):
            draw.polygon([point(x, y) for x, y in points], fill=fill)

        def line(points, *, fill, width_px):
            draw.line([point(x, y) for x, y in points], fill=fill,
                      width=max(1, round(width_px * scale)), joint='curve')

        hotspot = point(5.0, 27.0)
        outer = ((4.8, 26.2), (8.0, 18.8), (22.0, 4.8),
                 (27.2, 10.0), (13.2, 24.0), (5.8, 27.2))
        poly(outer, fill='white')
        body = ((8.3, 20.0), (21.9, 6.4), (25.6, 10.1), (12.0, 23.7))
        poly(body, fill='black')
        wood = ((4.8, 26.2), (8.3, 20.0), (12.0, 23.7), (5.8, 27.2))
        poly(wood, fill='white')
        graphite = ((4.8, 26.2), (7.1, 23.2), (8.3, 24.4), (5.8, 27.2))
        poly(graphite, fill='black')
        ferrule = ((21.9, 6.4), (23.8, 4.5), (29.0, 9.7), (27.1, 11.6))
        poly(ferrule, fill='white')
        eraser = ((23.8, 4.5), (25.4, 2.9), (30.6, 8.1), (29.0, 9.7))
        poly(eraser, fill='black')
        line(((22.4, 7.2), (27.9, 12.7)), fill='white', width_px=1.5)
        line(((24.4, 5.2), (29.8, 10.6)), fill='black', width_px=1.0)
        line(((10.1, 19.7), (22.1, 7.7)), fill='white', width_px=1.2)
        image.putpixel(hotspot, (0, 0, 0, 0))
        return image, hotspot

    def _color_picker_cursor(self):
        """Full-colour pencil cursor with the graphite tip as the hotspot."""
        user32 = ctypes.windll.user32
        width = max(32, user32.GetSystemMetrics(13))
        height = max(32, user32.GetSystemMetrics(14))
        image, hotspot = self.color_picker_artwork(width, height)
        return self._rgba_cursor(image, hotspot) or self._image_cursor(image, hotspot)

    def _pencil_cursor(self):
        """Compatibility alias for integrations that still request ``pencil``."""
        return self._color_picker_cursor()

    def _rgba_cursor(self, image, hotspot):
        """Create a 32-bit Windows colour cursor preserving PNG alpha/RGB.

        ``CreateCursor`` only supports monochrome XOR/AND masks.  Pick Color
        uses ``CreateIconIndirect`` with a 32-bit DIB so the approved yellow,
        silver and red pencil artwork is shown exactly instead of collapsing to
        black/white.
        """
        if os.name != 'nt':
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD),
            ]

        class RGBQUAD(ctypes.Structure):
            _fields_ = [('rgbBlue', ctypes.c_ubyte), ('rgbGreen', ctypes.c_ubyte),
                        ('rgbRed', ctypes.c_ubyte), ('rgbReserved', ctypes.c_ubyte)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', RGBQUAD * 1)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD),
                        ('yHotspot', wintypes.DWORD), ('hbmMask', wintypes.HBITMAP),
                        ('hbmColor', wintypes.HBITMAP)]

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        width, height = image.size
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down, matching Pillow coordinates
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        info.bmiHeader.biSizeImage = width * height * 4

        bits = ctypes.c_void_p()
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO),
                                           wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                           wintypes.HANDLE, wintypes.DWORD]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                                      wintypes.UINT, ctypes.c_void_p]
        gdi32.CreateBitmap.restype = wintypes.HBITMAP
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
        user32.CreateIconIndirect.restype = wintypes.HANDLE

        hdc = user32.GetDC(None)
        color_bitmap = gdi32.CreateDIBSection(hdc, ctypes.byref(info), 0,
                                              ctypes.byref(bits), None, 0)
        user32.ReleaseDC(None, hdc)
        if not color_bitmap or not bits.value:
            if color_bitmap:
                gdi32.DeleteObject(color_bitmap)
            return None

        # Windows ARGB cursors expect premultiplied BGRA pixels.
        rgba = image.convert('RGBA').tobytes()
        bgra = bytearray(len(rgba))
        for offset in range(0, len(rgba), 4):
            red, green, blue, alpha = rgba[offset:offset + 4]
            bgra[offset] = (blue * alpha + 127) // 255
            bgra[offset + 1] = (green * alpha + 127) // 255
            bgra[offset + 2] = (red * alpha + 127) // 255
            bgra[offset + 3] = alpha
        ctypes.memmove(bits.value, bytes(bgra), len(bgra))

        # Monochrome mask is retained for compatibility; alpha remains the
        # authoritative transparency source on supported Windows versions.
        stride = ((width + 15) // 16) * 2
        mask = bytearray(stride * height)
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y][3] < 128:
                    mask[y * stride + x // 8] |= 0x80 >> (x % 8)
        mask_buffer = (ctypes.c_ubyte * len(mask)).from_buffer_copy(mask)
        mask_bitmap = gdi32.CreateBitmap(width, height, 1, 1, mask_buffer)
        if not mask_bitmap:
            gdi32.DeleteObject(color_bitmap)
            return None

        native = None
        try:
            icon_info = ICONINFO(False, int(hotspot[0]), int(hotspot[1]),
                                 mask_bitmap, color_bitmap)
            native = user32.CreateIconIndirect(ctypes.byref(icon_info))
        finally:
            gdi32.DeleteObject(mask_bitmap)
            gdi32.DeleteObject(color_bitmap)

        if native:
            self._owned.append(native)
        return native

    def _image_cursor(self, image, hotspot):
        user32 = ctypes.windll.user32
        width, height = image.size
        stride = ((width + 15) // 16) * 2
        and_bits = bytearray([255] * (stride * height))
        xor_bits = bytearray(stride * height)
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                red, _green, _blue, alpha = pixels[x, y]
                if alpha:
                    index, bit = y * stride + x // 8, 0x80 >> (x % 8)
                    and_bits[index] &= ~bit
                    if red > 127:
                        xor_bits[index] |= bit
        and_buffer = (ctypes.c_ubyte * len(and_bits)).from_buffer_copy(and_bits)
        xor_buffer = (ctypes.c_ubyte * len(xor_bits)).from_buffer_copy(xor_bits)
        user32.CreateCursor.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        user32.CreateCursor.restype = wintypes.HANDLE
        cursor = user32.CreateCursor(None, *hotspot, width, height,
                                     and_buffer, xor_buffer)
        if cursor:
            self._owned.append(cursor)
        return cursor

    def close(self):
        if os.name == 'nt' and self._owned:
            user32 = ctypes.windll.user32
            user32.SetCursor.argtypes = [wintypes.HANDLE]
            user32.SetCursor(self.get('arrow'))
            user32.DestroyCursor.argtypes = [wintypes.HANDLE]
            for handle in self._owned:
                user32.DestroyCursor(handle)
        self._owned.clear()
        self._handles.clear()
