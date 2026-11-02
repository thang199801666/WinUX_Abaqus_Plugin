"""Regression coverage for document-style framed chart-area detection."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core import extraction


def document_chart():
    image = Image.new('RGB', (512, 387), 'white')
    draw = ImageDraw.Draw(image)
    # Dense page/title content above the chart used to pull the global profile
    # detector upward and make it return a document-sized rectangle.
    draw.text((20, 14), 'The graph below shows the proportion of the population aged 65 and over',
              fill=(25, 25, 25))
    draw.text((20, 28), 'between 1940 and 2040 in three different countries.', fill=(25, 25, 25))
    draw.text((140, 76), 'Proportion of population aged 65 and over', fill=(25, 25, 25))

    frame = (106, 97, 407, 274)
    left, top, right, bottom = frame
    draw.rectangle(frame, outline=(100, 100, 100))
    for y in (126, 156, 186, 216, 245):
        draw.line((left, y, right, y), fill=(150, 150, 150))
    # Curves deliberately cross the frame/grid but do not own the geometry.
    draw.line((left, 242, 166, 250, 226, 231, 286, 221, 347, 176, right, 114),
              fill=(25, 25, 25), width=2)
    draw.line((left, 229, 166, 214, 226, 191, 286, 196, 347, 157, right, 127),
              fill=(80, 80, 80), width=2)
    draw.line((left, 215, 166, 207, 226, 168, 286, 186, 347, 186, right, 98),
              fill=(40, 40, 40), width=2)

    for x, label in zip((106, 166, 226, 286, 347, 407),
                        ('1940', '1960', '1980', '2000', '2020', '2040')):
        draw.text((x - 10, 281), label, fill=(30, 30, 30))
    draw.text((246, 297), 'Year', fill=(30, 30, 30))

    # Detached legend below the plot must not become the chart bottom edge.
    draw.rectangle((214, 328, 303, 375), outline=(80, 80, 80))
    draw.line((220, 339, 249, 339), fill=(40, 40, 40))
    draw.text((258, 333), 'Japan', fill=(30, 30, 30))
    draw.line((220, 353, 249, 353), fill=(40, 40, 40))
    draw.text((258, 347), 'Sweden', fill=(30, 30, 30))
    draw.line((220, 367, 249, 367), fill=(40, 40, 40))
    draw.text((258, 361), 'USA', fill=(30, 30, 30))
    return image, frame


class PlotAreaFrameTests(unittest.TestCase):
    def test_document_text_and_legend_do_not_expand_plot_frame(self):
        image, frame = document_chart()
        self.assertEqual(extraction.detect_plot_area(image), frame)

    def test_frame_detector_matches_with_and_without_numpy(self):
        image, frame = document_chart()
        accelerated = extraction.detect_plot_area(image)
        with mock.patch.object(extraction, 'np', None):
            scalar = extraction.detect_plot_area(image)
        self.assertEqual(accelerated, frame)
        self.assertEqual(scalar, frame)


if __name__ == '__main__':
    unittest.main()
