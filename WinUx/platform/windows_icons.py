"""Windows Shell icon loading backed by Dear PyGui textures.

The public registry remains usable on non-Windows platforms: it creates
transparent fallback textures and does not call Win32 APIs there.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Optional

import dearpygui.dearpygui as dpg
from PIL import Image


ICON_SIZE = 16

SHGFI_ICON = 0x000000100
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010

SHGSI_ICON = 0x000000100
SHGSI_SMALLICON = 0x000000001

FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010

SIID_DOCNOASSOC = 0
SIID_FOLDER = 3

DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0
BI_RGB = 0


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


class SHSTOCKICONINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hIcon", wintypes.HICON),
        ("iSysImageIndex", ctypes.c_int),
        ("iIcon", ctypes.c_int),
        ("szPath", ctypes.c_wchar * 260),
    ]


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
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class WindowsIconRegistry:
    """Windows Shell icon cache backed by Dear PyGui static textures."""

    _textures: dict[str, int | str] = {}
    _texture_registry: Optional[int | str] = None
    _api_ready = False

    @classmethod
    def reset(cls) -> None:
        """Release Dear PyGui texture state before its context is destroyed."""
        texture_registry = cls._texture_registry
        cls._textures.clear()
        cls._texture_registry = None

        if texture_registry is None:
            return
        try:
            if dpg.does_item_exist(texture_registry):
                dpg.delete_item(texture_registry)
        except Exception:
            # Cleanup must remain safe after Dear PyGui has already torn down
            # its context. Clearing the Python-side tags is sufficient for the
            # next context to build a fresh registry.
            pass

    @classmethod
    def _configure_win32_api(cls) -> None:
        if cls._api_ready or os.name != "nt":
            return

        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        shell32.SHGetFileInfoW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(SHFILEINFOW),
            wintypes.UINT,
            wintypes.UINT,
        ]
        shell32.SHGetFileInfoW.restype = ctypes.c_size_t

        shell32.SHGetStockIconInfo.argtypes = [
            ctypes.c_int,
            wintypes.UINT,
            ctypes.POINTER(SHSTOCKICONINFO),
        ]
        shell32.SHGetStockIconInfo.restype = ctypes.c_long

        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.DrawIconEx.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HICON,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.HBRUSH,
            wintypes.UINT,
        ]
        user32.DrawIconEx.restype = wintypes.BOOL
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL

        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL

        cls._api_ready = True

    @classmethod
    def _ensure_texture_registry(cls) -> None:
        if (
            cls._texture_registry is None
            or not dpg.does_item_exist(cls._texture_registry)
        ):
            cls._texture_registry = dpg.add_texture_registry(show=False)

    @classmethod
    def _add_texture(cls, image: Image.Image, tag: str):
        cls._ensure_texture_registry()
        image = image.convert("RGBA")
        if image.size != (ICON_SIZE, ICON_SIZE):
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image = image.resize((ICON_SIZE, ICON_SIZE), resampling)

        pixels = [channel / 255.0 for channel in image.tobytes()]
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

        return dpg.add_static_texture(
            width=ICON_SIZE,
            height=ICON_SIZE,
            default_value=pixels,
            tag=tag,
            parent=cls._texture_registry,
        )

    @classmethod
    def _ensure_fallbacks(cls) -> None:
        fallback_tags = (
            cls._textures.get("folder:fallback"),
            cls._textures.get("file:fallback"),
        )
        if all(fallback_tags):
            try:
                if all(dpg.does_item_exist(tag) for tag in fallback_tags):
                    return
            except Exception:
                pass

        # A Dear PyGui tag is valid only in the context that created it. If a
        # fallback is stale, every cached extension icon belongs to that same
        # destroyed context and must be discarded together.
        cls._textures.clear()

        transparent = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        cls._textures["folder:fallback"] = cls._add_texture(
            transparent, "native_icon_folder_fallback"
        )
        cls._textures["file:fallback"] = cls._add_texture(
            transparent, "native_icon_file_fallback"
        )

    @classmethod
    def _stock_hicon(cls, stock_id: int):
        cls._configure_win32_api()
        info = SHSTOCKICONINFO()
        info.cbSize = ctypes.sizeof(SHSTOCKICONINFO)
        hr = ctypes.windll.shell32.SHGetStockIconInfo(
            stock_id,
            SHGSI_ICON | SHGSI_SMALLICON,
            ctypes.byref(info),
        )
        return info.hIcon if hr == 0 else None

    @classmethod
    def _file_type_hicon(cls, extension: str):
        cls._configure_win32_api()
        info = SHFILEINFOW()
        extension = (
            extension
            if extension.startswith(".")
            else f".{extension}"
            if extension
            else ""
        )
        dummy_path = f"dummy{extension}" if extension else "dummy_file"
        result = ctypes.windll.shell32.SHGetFileInfoW(
            dummy_path,
            FILE_ATTRIBUTE_NORMAL,
            ctypes.byref(info),
            ctypes.sizeof(info),
            SHGFI_ICON | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES,
        )
        return info.hIcon if result else None

    @classmethod
    def _hicon_to_image(cls, hicon) -> Optional[Image.Image]:
        """Render an HICON into a 32-bit top-down DIB and return RGBA pixels."""
        if not hicon:
            return None

        cls._configure_win32_api()
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        screen_dc = user32.GetDC(None)
        if not screen_dc:
            return None

        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = None
        old_bitmap = None

        try:
            if not memory_dc:
                return None

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = ICON_SIZE
            bitmap_info.bmiHeader.biHeight = -ICON_SIZE
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB

            pixel_ptr = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(
                screen_dc,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
                ctypes.byref(pixel_ptr),
                None,
                0,
            )
            if not bitmap or not pixel_ptr.value:
                return None

            old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
            ctypes.memset(pixel_ptr.value, 0, ICON_SIZE * ICON_SIZE * 4)

            if not user32.DrawIconEx(
                memory_dc,
                0,
                0,
                hicon,
                ICON_SIZE,
                ICON_SIZE,
                0,
                None,
                DI_NORMAL,
            ):
                return None

            raw = ctypes.string_at(pixel_ptr.value, ICON_SIZE * ICON_SIZE * 4)
            image = Image.frombytes(
                "RGBA",
                (ICON_SIZE, ICON_SIZE),
                raw,
                "raw",
                "BGRA",
            )

            # Some legacy icons are rendered with zero alpha despite valid RGB.
            alpha = image.getchannel("A")
            if (
                alpha.getbbox() is None
                and image.convert("RGB").getbbox() is not None
            ):
                r, g, b, _ = image.split()
                alpha = Image.eval(
                    Image.merge("RGB", (r, g, b)).convert("L"),
                    lambda p: 255 if p else 0,
                )
                image.putalpha(alpha)

            return image
        finally:
            if old_bitmap:
                gdi32.SelectObject(memory_dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)

    @classmethod
    def get_icon(cls, extension: str = "", is_dir: bool = False):
        """Return a Dear PyGui texture tag for a folder or file extension."""
        cls._ensure_fallbacks()
        normalized_extension = (extension or "").lower()
        cache_key = (
            "folder"
            if is_dir
            else f"file:{normalized_extension or '<generic>'}"
        )

        cached = cls._textures.get(cache_key)
        if cached is not None:
            try:
                if dpg.does_item_exist(cached):
                    return cached
            except Exception:
                pass
            cls._textures.pop(cache_key, None)

        fallback_key = "folder:fallback" if is_dir else "file:fallback"
        if os.name != "nt":
            return cls._textures[fallback_key]

        hicon = None
        try:
            hicon = (
                cls._stock_hicon(SIID_FOLDER)
                if is_dir
                else cls._file_type_hicon(normalized_extension)
            )
            if not hicon and not is_dir:
                hicon = cls._stock_hicon(SIID_DOCNOASSOC)

            image = cls._hicon_to_image(hicon)
            if image is None:
                return cls._textures[fallback_key]

            safe_suffix = (
                "folder"
                if is_dir
                else (normalized_extension.lstrip(".") or "generic")
            )
            safe_suffix = "".join(
                ch if ch.isalnum() else "_" for ch in safe_suffix
            )
            texture = cls._add_texture(image, f"native_icon_{safe_suffix}")
            cls._textures[cache_key] = texture
            return texture
        except (OSError, ValueError, TypeError, ctypes.ArgumentError):
            return cls._textures[fallback_key]
        finally:
            if hicon:
                ctypes.windll.user32.DestroyIcon(hicon)


def reset_windows_icon_registry() -> None:
    """Clear cached icon textures across Dear PyGui context lifecycles."""
    WindowsIconRegistry.reset()


__all__ = [
    "BI_RGB",
    "BITMAPINFO",
    "BITMAPINFOHEADER",
    "DIB_RGB_COLORS",
    "DI_NORMAL",
    "FILE_ATTRIBUTE_DIRECTORY",
    "FILE_ATTRIBUTE_NORMAL",
    "ICON_SIZE",
    "SHFILEINFOW",
    "SHGFI_ICON",
    "SHGFI_SMALLICON",
    "SHGFI_USEFILEATTRIBUTES",
    "SHSTOCKICONINFO",
    "SHGSI_ICON",
    "SHGSI_SMALLICON",
    "SIID_DOCNOASSOC",
    "SIID_FOLDER",
    "WindowsIconRegistry",
    "reset_windows_icon_registry",
]
