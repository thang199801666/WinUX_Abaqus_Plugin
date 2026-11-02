"""Windows Shell icon loading backed by Dear PyGui textures.

The public registry remains usable on non-Windows platforms: it creates
transparent fallback textures and does not call Win32 APIs there.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from typing import Optional

from DearUIQt.backends import dpg
from PIL import Image


ICON_SIZE = 16

SHGFI_ICON = 0x000000100
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_SYSICONINDEX = 0x000004000

SHGSI_ICON = 0x000000100
SHGSI_SMALLICON = 0x000000001
SHGSI_LARGEICON = 0x000000000

SHIL_SMALL = 0
SHIL_LARGE = 1
SHIL_EXTRALARGE = 2
SHIL_SYSSMALL = 3
SHIL_JUMBO = 4
ILD_NORMAL = 0x00000000

FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010

SIID_DOCNOASSOC = 0
SIID_FOLDER = 3

DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0
BI_RGB = 0


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


IID_IIMAGELIST = GUID(
    0x46EB5926, 0x582E, 0x4017,
    (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50),
)


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

        # SHGetImageList exposes the Explorer system image lists, including
        # 48 px and 256 px/Jumbo sources.  Some very old Windows builds do not
        # export it by name, so feature-detect instead of making startup depend
        # on the symbol.
        if hasattr(shell32, "SHGetImageList"):
            shell32.SHGetImageList.argtypes = [
                ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
            ]
            shell32.SHGetImageList.restype = ctypes.c_long

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
    def _add_texture(cls, image: Image.Image, tag: str, size: int = ICON_SIZE):
        """Upload one Shell icon at the requested device-pixel size.

        Historically every shell icon was silently collapsed to 16 px.  That
        works for Details/List but makes Tiles/Large/Extra-large views stretch
        the same tiny raster and become visibly blurry.  Keep the 16 px default
        for existing callers while allowing Explorer view modes to retain a
        native larger raster.
        """
        cls._ensure_texture_registry()
        size = max(1, int(size))
        image = image.convert("RGBA")
        if image.size != (size, size):
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image = image.resize((size, size), resampling)

        pixels = [channel / 255.0 for channel in image.tobytes()]
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

        return dpg.add_static_texture(
            width=size,
            height=size,
            default_value=pixels,
            tag=tag,
            parent=cls._texture_registry,
        )

    @classmethod
    def _add_native_texture(cls, image: Image.Image, tag: str):
        """Upload an RGBA image without silently forcing it to 16x16.

        Toolbar resources are already rasterized for their final device-pixel
        size and must be uploaded 1:1;
        resampling them back to 16px and stretching them again in Dear ImGui
        destroys edge contrast on Windows.
        """
        cls._ensure_texture_registry()
        image = image.convert("RGBA")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("Texture dimensions must be positive.")

        pixels = [channel / 255.0 for channel in image.tobytes()]
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

        return dpg.add_static_texture(
            width=width,
            height=height,
            default_value=pixels,
            tag=tag,
            parent=cls._texture_registry,
        )

    @classmethod
    def _fallback_texture(cls, is_dir: bool, size: int = ICON_SIZE):
        size = max(1, int(size))
        key = f"{'folder' if is_dir else 'file'}:fallback:{size}"
        cached = cls._textures.get(key)
        if cached is not None:
            try:
                if dpg.does_item_exist(cached):
                    return cached
            except Exception:
                pass
            cls._textures.pop(key, None)

        transparent = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tag = f"native_icon_{'folder' if is_dir else 'file'}_fallback_{size}"
        texture = cls._add_texture(transparent, tag, size=size)
        cls._textures[key] = texture
        return texture

    @classmethod
    def _ensure_fallbacks(cls) -> None:
        # Preserve the old helper contract for code/tests that only need the
        # default small-icon fallback.
        cls._fallback_texture(True, ICON_SIZE)
        cls._fallback_texture(False, ICON_SIZE)

    @classmethod
    def _stock_hicon(cls, stock_id: int, size: int = ICON_SIZE):
        cls._configure_win32_api()
        info = SHSTOCKICONINFO()
        info.cbSize = ctypes.sizeof(SHSTOCKICONINFO)
        flags = SHGSI_ICON | (SHGSI_SMALLICON if int(size) <= ICON_SIZE else SHGSI_LARGEICON)
        hr = ctypes.windll.shell32.SHGetStockIconInfo(
            stock_id, flags, ctypes.byref(info)
        )
        return info.hIcon if hr == 0 else None

    @classmethod
    def _file_type_hicon(cls, extension: str, size: int = ICON_SIZE):
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
        flags = SHGFI_ICON | SHGFI_USEFILEATTRIBUTES
        if int(size) <= ICON_SIZE:
            flags |= SHGFI_SMALLICON
        result = ctypes.windll.shell32.SHGetFileInfoW(
            dummy_path,
            FILE_ATTRIBUTE_NORMAL,
            ctypes.byref(info),
            ctypes.sizeof(info),
            flags,
        )
        return info.hIcon if result else None

    @staticmethod
    def _image_list_kind(size: int) -> tuple[int, int]:
        """Return (SHIL_*, source_pixels) for the smallest sharp source."""
        size = max(1, int(size))
        if size <= 16:
            return SHIL_SMALL, 16
        if size <= 32:
            return SHIL_LARGE, 32
        if size <= 48:
            return SHIL_EXTRALARGE, 48
        # Explorer uses the Jumbo list for 64+ icon modes.  Pull 256 px and
        # downsample once with PIL rather than repeatedly magnifying 16 px.
        return SHIL_JUMBO, 256

    @classmethod
    def _system_icon_index(cls, extension: str = "", is_dir: bool = False):
        cls._configure_win32_api()
        info = SHFILEINFOW()
        if is_dir:
            dummy_path = "dummy_folder"
            attrs = FILE_ATTRIBUTE_DIRECTORY
        else:
            extension = extension or ""
            if extension and not extension.startswith("."):
                extension = "." + extension
            dummy_path = f"dummy{extension}" if extension else "dummy_file"
            attrs = FILE_ATTRIBUTE_NORMAL
        result = ctypes.windll.shell32.SHGetFileInfoW(
            dummy_path, attrs, ctypes.byref(info), ctypes.sizeof(info),
            SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES,
        )
        return int(info.iIcon) if result else None

    @classmethod
    def _image_list_hicon(cls, image_index: int, requested_size: int):
        """Fetch an HICON from the same system image lists Explorer uses."""
        if image_index is None or os.name != "nt":
            return None, None
        cls._configure_win32_api()
        shell32 = ctypes.windll.shell32
        sh_get_image_list = getattr(shell32, "SHGetImageList", None)
        if sh_get_image_list is None:
            # XP exposed this API by ordinal; keeping the fallback also makes
            # embedded/stripped Shell32 builds less fragile.
            try:
                sh_get_image_list = shell32[727]
                sh_get_image_list.argtypes = [
                    ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
                ]
                sh_get_image_list.restype = ctypes.c_long
            except (AttributeError, OSError, TypeError):
                return None, None

        image_list_kind, source_size = cls._image_list_kind(requested_size)
        interface = ctypes.c_void_p()
        hr = sh_get_image_list(
            image_list_kind, ctypes.byref(IID_IIMAGELIST), ctypes.byref(interface)
        )
        if hr != 0 or not interface.value:
            return None, None

        # IImageList::GetIcon is vtable slot 10; Release is IUnknown slot 2.
        vtable = ctypes.cast(
            interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        get_icon = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
            ctypes.POINTER(wintypes.HICON),
        )(vtable[10])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        hicon = wintypes.HICON()
        try:
            hr = get_icon(interface, int(image_index), ILD_NORMAL, ctypes.byref(hicon))
            if hr != 0 or not hicon:
                return None, None
            return hicon, source_size
        finally:
            release(interface)

    @staticmethod
    def _center_visible_icon(image: Image.Image, canvas_size: int | None = None) -> Image.Image:
        """Center visible Shell glyph without changing its native scale."""
        image = image.convert("RGBA")
        canvas_size = max(1, int(canvas_size or image.size[0]))
        alpha = image.getchannel("A")
        mask = alpha.point(lambda value: 255 if value > 8 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return image
        glyph = image.crop(bbox)
        width, height = glyph.size
        if width > canvas_size or height > canvas_size:
            return image
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        x = (canvas_size - width) // 2
        y = (canvas_size - height) // 2
        canvas.alpha_composite(glyph, (x, y))
        return canvas

    @staticmethod
    def _pad_icon_image(image: Image.Image, padding: int) -> Image.Image:
        """Add transparent guard pixels without resampling the Shell glyph."""
        image = image.convert("RGBA")
        padding = max(0, int(padding))
        if padding <= 0:
            return image
        width, height = image.size
        canvas = Image.new(
            "RGBA", (width + 2 * padding, height + 2 * padding),
            (0, 0, 0, 0))
        canvas.alpha_composite(image, (padding, padding))
        return canvas

    @staticmethod
    def _normalize_rendered_icon(image: Image.Image, size: int) -> Image.Image:
        """Keep native small Shell padding; normalize only larger rasters.

        The 16 px system image list is already pixel-designed for Explorer.
        Re-cropping its alpha bounds can erase faint edge pixels and makes the
        lower/right contour look clipped.  Larger image-list sources can still
        be optically centered because they are later resized for grid modes.
        """
        image = image.convert("RGBA")
        size = max(1, int(size))
        if size <= ICON_SIZE:
            return image
        return WindowsIconRegistry._center_visible_icon(image, size)

    @classmethod
    def _hicon_to_image(cls, hicon, size: int = ICON_SIZE) -> Optional[Image.Image]:
        """Render an HICON into a 32-bit top-down DIB and return RGBA pixels."""
        if not hicon:
            return None

        size = max(1, int(size))
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
            bitmap_info.bmiHeader.biWidth = size
            bitmap_info.bmiHeader.biHeight = -size
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
            ctypes.memset(pixel_ptr.value, 0, size * size * 4)

            if not user32.DrawIconEx(
                memory_dc,
                0,
                0,
                hicon,
                size,
                size,
                0,
                None,
                DI_NORMAL,
            ):
                return None

            raw = ctypes.string_at(pixel_ptr.value, size * size * 4)
            image = Image.frombytes(
                "RGBA",
                (size, size),
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

            return cls._normalize_rendered_icon(image, size)
        finally:
            if old_bitmap:
                gdi32.SelectObject(memory_dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)

    @classmethod
    def get_icon(cls, extension: str = "", is_dir: bool = False, size: int = ICON_SIZE, padding: int = 0):
        """Return a cached Explorer-quality Shell icon texture.

        ``size`` is the visible Shell raster size. ``padding`` adds transparent
        guard pixels around that raster without scaling it.  The guard is used
        by compact Explorer table cells because Dear ImGui can clip the final
        device-pixel row of an image item at a table boundary on Windows.

        Larger view modes use Windows' 32/48/Jumbo image lists and are cached
        independently by size.
        """
        size = max(1, int(size))
        padding = max(0, int(padding))
        normalized_extension = (extension or "").lower()
        cache_key = (
            f"folder:{size}:pad{padding}"
            if is_dir
            else f"file:{normalized_extension or '<generic>'}:{size}:pad{padding}"
        )

        cached = cls._textures.get(cache_key)
        if cached is not None:
            try:
                if dpg.does_item_exist(cached):
                    return cached
            except Exception:
                pass
            cls._textures.pop(cache_key, None)

        fallback = cls._fallback_texture(is_dir, size)
        if os.name != "nt":
            return fallback

        hicon = None
        try:
            source_size = None
            # SHIL_SMALL's extracted HICON can lose its bottom scanline on
            # Windows/DPI combinations, before any UI clipping occurs. The
            # direct SHGFI_SMALLICON / SHGSI_SMALLICON handles preserve the
            # complete pixel-designed 16 px raster. Keep image lists for the
            # larger sizes, where their higher-resolution sources are needed.
            if size > ICON_SIZE:
                image_index = cls._system_icon_index(normalized_extension, is_dir=is_dir)
                hicon, source_size = cls._image_list_hicon(image_index, size)
            if not hicon:
                hicon = (
                    cls._stock_hicon(SIID_FOLDER, size=size)
                    if is_dir
                    else cls._file_type_hicon(normalized_extension, size=size)
                )
                source_size = 16 if size <= 16 else 32
            if not hicon and not is_dir:
                hicon = cls._stock_hicon(SIID_DOCNOASSOC, size=size)
                source_size = 16 if size <= 16 else 32

            image = cls._hicon_to_image(hicon, source_size or size)
            if image is None:
                return fallback
            if image.size != (size, size):
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                image = image.resize((size, size), resampling)

            safe_suffix = (
                "folder" if is_dir else (normalized_extension.lstrip(".") or "generic")
            )
            safe_suffix = "".join(ch if ch.isalnum() else "_" for ch in safe_suffix)
            if padding:
                canvas = cls._pad_icon_image(image, padding)
                texture = cls._add_native_texture(
                    canvas, f"native_icon_{safe_suffix}_{size}_pad{padding}"
                )
            else:
                texture = cls._add_texture(
                    image, f"native_icon_{safe_suffix}_{size}", size=size
                )
            cls._textures[cache_key] = texture
            return texture
        except (OSError, ValueError, TypeError, ctypes.ArgumentError, AttributeError):
            return fallback
        finally:
            if hicon:
                ctypes.windll.user32.DestroyIcon(hicon)

    @classmethod
    def get_stock_icon(cls, stock_id: int, size: int = ICON_SIZE):
        """Upload a cached Shell stock icon at an explicit pixel size."""
        size = max(1, int(size))
        key = "stock:{}:{}".format(int(stock_id), size)
        cached = cls._textures.get(key)
        if cached is not None and dpg.does_item_exist(cached):
            return cached
        fallback = cls._fallback_texture(True, size)
        if os.name != "nt":
            return fallback
        hicon = None
        try:
            hicon = cls._stock_hicon(int(stock_id), size=size)
            source_size = 16 if size <= 16 else 32
            image = cls._hicon_to_image(hicon, source_size)
            if image is not None:
                if image.size != (size, size):
                    resampling = getattr(Image, "Resampling", Image).LANCZOS
                    image = image.resize((size, size), resampling)
                texture = cls._add_texture(
                    image, "native_icon_stock_{}_{}".format(int(stock_id), size), size=size
                )
                cls._textures[key] = texture
                return texture
        except (OSError, ValueError, TypeError, ctypes.ArgumentError):
            pass
        finally:
            if hicon:
                ctypes.windll.user32.DestroyIcon(hicon)
        return fallback

    @classmethod
    def read_path_info(cls, path):
        """Read a real Shell icon/name off-thread, without touching DPG."""
        if os.name != "nt":
            return None, ""
        cls._configure_win32_api()
        info = SHFILEINFOW()
        try:
            result = ctypes.windll.shell32.SHGetFileInfoW(
                str(path), 0, ctypes.byref(info), ctypes.sizeof(info),
                SHGFI_ICON | SHGFI_SMALLICON | 0x000000200,  # SHGFI_DISPLAYNAME
            )
            image = cls._hicon_to_image(info.hIcon) if result and info.hIcon else None
            return image, str(info.szDisplayName) if result else ""
        except (OSError, ValueError, TypeError, ctypes.ArgumentError):
            return None, ""
        finally:
            if info.hIcon:
                ctypes.windll.user32.DestroyIcon(info.hIcon)

    @classmethod
    def read_path_image(cls, path):
        return cls.read_path_info(path)[0]

    @classmethod
    def get_path_icon(cls, path, image=None):
        """Use a worker-prepared image, or a cached/native folder fallback."""
        cls._ensure_fallbacks()
        key = "path:" + os.path.normcase(os.path.abspath(str(path)))
        cached = cls._textures.get(key)
        if cached is not None and dpg.does_item_exist(cached):
            return cached
        if image is not None:
            suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            texture = cls._add_texture(image, "native_icon_path_" + suffix)
            cls._textures[key] = texture
            return texture
        return cls.get_icon(is_dir=True)


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
