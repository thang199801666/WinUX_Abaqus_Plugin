"""Native tool cursors, including generated magnifying-glass zoom cursors."""
import ctypes
from ctypes import wintypes
import os


class ToolCursorHandles:
    SYSTEM_IDS = {'arrow': 32512, 'pick': 32515, 'pan': 32649,
                  'pan_drag': 32646, 'move': 32646, 'point': 32649, 'delete': 32648}

    def __init__(self):
        self._handles = {}
        self._owned = []

    def get(self, mode):
        if os.name != 'nt' or mode is None:
            return None
        if mode not in self._handles:
            user32 = ctypes.windll.user32
            user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            user32.LoadCursorW.restype = wintypes.HANDLE
            if mode == 'blank':
                handle = self._blank_cursor()
            else:
                handle = self._zoom_cursor(mode == 'zoom_in') if mode in ('zoom_in', 'zoom_out') else None
            self._handles[mode] = handle or user32.LoadCursorW(
                None, ctypes.c_void_p(self.SYSTEM_IDS.get(mode, 32512)))
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
        cursor = user32.CreateCursor(None, round(12*scale), round(12*scale), width, height,
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
