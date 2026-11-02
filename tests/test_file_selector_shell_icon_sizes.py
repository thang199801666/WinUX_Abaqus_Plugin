from __future__ import annotations

import unittest

from PIL import Image
from unittest.mock import patch

from WinUx.dialogs.folder_browser_style import folder_item_texture
from WinUx.platform.windows_icons import (
    SHIL_EXTRALARGE,
    SHIL_JUMBO,
    SHIL_LARGE,
    SHIL_SMALL,
    WindowsIconRegistry,
)


class FileSelectorShellIconSizeTests(unittest.TestCase):
    def test_explorer_source_bucket_avoids_upscaling_small_raster(self):
        self.assertEqual(WindowsIconRegistry._image_list_kind(16), (SHIL_SMALL, 16))
        self.assertEqual(WindowsIconRegistry._image_list_kind(24), (SHIL_LARGE, 32))
        self.assertEqual(WindowsIconRegistry._image_list_kind(48), (SHIL_EXTRALARGE, 48))
        self.assertEqual(WindowsIconRegistry._image_list_kind(56), (SHIL_JUMBO, 256))
        self.assertEqual(WindowsIconRegistry._image_list_kind(112), (SHIL_JUMBO, 256))

    def test_folder_texture_forwards_requested_view_size(self):
        with patch.object(WindowsIconRegistry, "get_icon", return_value="texture") as get_icon:
            self.assertEqual(folder_item_texture(48), "texture")
            get_icon.assert_called_once_with(is_dir=True, size=48, padding=0)

    def test_small_shell_raster_keeps_native_edge_pixels(self):
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        image.putpixel((8, 15), (255, 255, 255, 16))
        normalized = WindowsIconRegistry._normalize_rendered_icon(image, 16)
        self.assertEqual(normalized.getpixel((8, 15)), (255, 255, 255, 16))


    def test_guard_padding_preserves_last_shell_pixel_without_scaling(self):
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        edge = (17, 85, 204, 231)
        image.putpixel((8, 15), edge)
        padded = WindowsIconRegistry._pad_icon_image(image, 1)
        self.assertEqual(padded.size, (18, 18))
        self.assertEqual(padded.getpixel((9, 16)), edge)
        self.assertEqual(padded.getpixel((9, 17)), (0, 0, 0, 0))
        self.assertEqual(padded.crop((1, 1, 17, 17)).tobytes(), image.tobytes())

    def test_folder_texture_forwards_guard_padding(self):
        with patch.object(WindowsIconRegistry, "get_icon", return_value="texture") as get_icon:
            self.assertEqual(folder_item_texture(16, padding=1), "texture")
            get_icon.assert_called_once_with(is_dir=True, size=16, padding=1)

    def test_view_sizes_get_independent_cache_keys(self):
        # Regression guard for the previous single 16px cache contract.
        folder_16 = f"folder:{16}:pad0"
        folder_48 = f"folder:{48}:pad0"
        file_16 = f"file:.png:{16}:pad0"
        file_112 = f"file:.png:{112}:pad0"
        self.assertNotEqual(folder_16, folder_48)
        self.assertNotEqual(file_16, file_112)


if __name__ == "__main__":
    unittest.main(verbosity=2)
