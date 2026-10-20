"""Preview magnification is relative to canvas zoom, without edge stretching."""
import unittest

from WinUx.plotdigitizer.ui.preview import preview_geometry


class PreviewZoomTests(unittest.TestCase):
    def assert_scale(self, geometry, image_size, expected):
        width, height = image_size
        source_width = (geometry.uv_max[0] - geometry.uv_min[0]) * width
        source_height = (geometry.uv_max[1] - geometry.uv_min[1]) * height
        self.assertAlmostEqual((geometry.image_max[0] - geometry.image_min[0]) / source_width, expected)
        self.assertAlmostEqual((geometry.image_max[1] - geometry.image_min[1]) / source_height, expected)

    def test_preview_is_five_times_canvas_scale(self):
        for scale in (.05, .5, 1, 2, 40):
            with self.subTest(scale=scale):
                geometry = preview_geometry((1000, 800), (500, 400), scale)
                self.assert_scale(geometry, (1000, 800), scale * 5)

    def test_zooming_canvas_halves_the_sampled_source_region(self):
        before = preview_geometry((1000, 800), (500, 400), 1)
        after = preview_geometry((1000, 800), (500, 400), 2)
        self.assertAlmostEqual(before.uv_max[0] - before.uv_min[0],
                               2 * (after.uv_max[0] - after.uv_min[0]))

    def test_image_edges_have_background_instead_of_stretched_pixels(self):
        geometry = preview_geometry((1000, 800), (0, 0), 2)
        self.assertEqual(geometry.uv_min, (0, 0))
        self.assertEqual(geometry.image_min, (70, 70))
        self.assert_scale(geometry, (1000, 800), 10)

    def test_small_image_keeps_true_scale(self):
        geometry = preview_geometry((1, 1), (.5, .5), 1)
        self.assert_scale(geometry, (1, 1), 5)
        self.assertEqual(geometry.image_max[0] - geometry.image_min[0], 5)

    def test_invalid_geometry_is_rejected(self):
        for size, scale in (((0, 10), 1), ((10, 10), 0), ((10, 10), float("nan"))):
            with self.assertRaises(ValueError):
                preview_geometry(size, (0, 0), scale)


if __name__ == "__main__":
    unittest.main()
