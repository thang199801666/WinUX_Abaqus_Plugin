import os
import sys
import unittest
from unittest.mock import patch
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.models import AxisScale


class YRetryTests(unittest.TestCase):
    def test_only_retry_unrecognized_y_and_map_source_coordinates(self):
        image = Image.new('RGB', (700, 500), 'white')
        rect = (155, 60, 600, 390)
        empty = td.AxisTickDetection('y', (), 0, AxisScale.LINEAR)
        original = td._detect_axis
        calls = []
        def fake_axis(im, subrect, axis, scale, **kwargs):
            calls.append((im.size, axis, subrect))
            if axis == 'x':
                return td.AxisTickDetection('x', (), 0, scale)
            if im is image:
                return empty
            ys = (subrect[1], (subrect[1]+subrect[3])/2, subrect[3])
            return td.AxisTickDetection('y', tuple(td.TickReading(y, v, str(v), .9, (0,0,0,0))
                for y, v in zip(ys, (2000, 1000, 0))), .9, scale)
        with patch.object(td, '_detect_axis', side_effect=fake_axis):
            detected = td.detect_calibration_ticks(image, rect)
        self.assertTrue(detected.y.ready)
        self.assertEqual(3, len(calls))
        self.assertAlmostEqual(60, detected.y.ticks[0].position)
        self.assertAlmostEqual(390, detected.y.ticks[-1].position)

    def test_no_retry_if_y_is_valid(self):
        image = Image.new('RGB', (700, 500), 'white')
        ready = td.AxisTickDetection('y', tuple(td.TickReading(i, i, str(i), .9, (0,0,0,0))
            for i in (0, 100, 200)), .9, AxisScale.LINEAR)
        with patch.object(td, '_detect_axis', side_effect=[ready, ready]) as mock:
            result = td.detect_calibration_ticks(image, (155,60,600,390))
        self.assertEqual(2, mock.call_count)
        self.assertIs(result.y, ready)

if __name__ == '__main__':
    unittest.main()
