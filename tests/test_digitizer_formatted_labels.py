"""Real screenshot label pixels: no source-image path or sequence completion."""
import base64
import math
import os
import sys
import unittest
import zlib
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.axis_labels import parse_axis_label, format_axis_value, parse_axis_value_input
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.models import AxisScale

# Unmodified grayscale crops from Test-Plotdigitizer-04.png; only label strips
# are retained. The plot/axes are redrawn below, without numeric assumptions.
YEARS = 'eNrt1+9LE3EcB/D/Y8IWKl0whHPiOmKSPokh+KAHYvhMEBFhRFQPpGBECBNC3APBJxGCMLIaYZo4iig5kiIkTERCFrgHR9EGFWPcyYe+92Pm2sd68H3fg+LeDz5333vw4r73PsaNKEiQIEGC/DU1Z1b/TbeGdj2w6g+LSPU/cBk+H1sUs6Cp8Wf0OHEhPnN0TS6MG1NE9vGuuwC6HpgXNzwDZ9ftp6DclmOfn1OVDNHWeVV95E1IbZyLqI1zudrSI8m7REb7S3rTvh/ZoUp0w7smF8a1Qge1Wg3vuosKzt1zwYNwgd61bKLZQ/EQvvdtSLFfWwtUVHRLy9PemQNnlhC1cS6iNs5la3tNg2IPT3vF6eDNiJj9Oe+aXBi3HAL89jOuu1jEucMu+OWFOPQ8QLP25dmU3N1W1sRI5vS4OIwPOTOLqI1zEbVx7gm12XtYT4iTkamBqQ9LMcO7JpsmtxhemJh8j3fdRQbn9tZBs5JTDTxLRtSQf77FtuL9IXGcDjvzOqi2JhdUW5N7Qm32HsrKkvVKmVyNXey6cwh8HRvcXW1Gz57agrveAueO18Hl1uiKDyyl04B2exZoblSczIWcOQKqrckF1dbknlCbswc9qabGx5QSmf33gK/j7y7RxCTedRazOHf2F7jdtYxnTWVX+uluxsRXRO6SOMu0OPMapjbWBdTGuHxtR3tIDveLeSuFfB2Pu5b92Zq+DHfdxSrOXXXnvv3teOUqmhV/KRPyb02n/RdL18QYHXJmFlIb40Jq4++Xq83ew7e+HVpT9dOG+LWZB76ODW4hWiKjMw933YWJcysuuKF8JKNjHs2K76Yx2Xv90a3bByu+QnvKJ2eWELVxLqI2zuVqsyKRlnDkBs21aT3blO0c6E6Z9Wsy4VzKKInoNOFddwF0PTAb1cITJpyllPSn45NQRCRNb7WzHQ+9iaiNcxG1se6faquWnYNhEjYNrmX443oLnFsHP5u+sMCUj02/XGBtDa4PjyNIkCBBggQJ4lt+AoaxOKE='
COMMAS = 'eNrtnbGKFEEQht/Dg9tQE+EwODczvReQvXTgAh9gJjIw1XACE+EyQRTvkhN8gsPAwFAuUnBSNz5YKNydnqG3p6e7qqsbOfT/gprtPygm7Y/9GSIg53Zvjg9Nbrl89Hb49e3J0dHFMMeHJt/jRXVybn5tlpd08+BXPztz6DT5Pl/o6bD9+ng7nq362ZpDq8ldxu3vV9vx6rCfjTk0mnx+++uz3bjXz8ocKkX+42qHt/3d6Xa8POhnbQ61Jp9/9+vldpyt+tmaQ6vJZ7Z//k6b4090c/9nPztz6JJzl81icXC4eE4nb4i+Lh8//DjM8ZGaz3P1YTfXZKd5pObznP8ukwMAAAAAAAD+WVvgiQBBTmFj4Nz+rQ6Q5/MYY+Dc/q0O6MR5AGMMnNu/1QGtOA+y2+7c/q0OaMR5dLtz+7c6oBLn0e3O7d/qgFqcTyyEu925/Vsd0Irz6Ls7t3+rAzpZHmQ0Bs7t3+oAWS5gPa8DJHka0AQAAAAAAACAvyMjPNsgyKUywrMNgpykMqKb2oaOz+Psy4h2ahtaPuewMqKZ2oaGzyXb7b8PHNtQ8XnQE3gyop7ahprPJe9u/33g2IaWzyXbB8cwtQ0dk3OrXRnh2QYml7Oetw3RHBYCAAAAAAAAkK0MNK2GuC6wQkDVaojrAqK8VkNcFxDlthpi11ai3FYDtz217ZC2PbHVwFmIyfa8VkN0e16rgdMFZVoNIcq0GiAKAAAAAAAAAHfSRXj64Va5NbFLkUZilyKRxC5FMkldCtV2cWdC6Anc7eLOhOrd8zsTse2ZnQnOR5TqTIQo3plIlRMAAAAAAACA/08XeJ5ALQp8XeB5Ar0o8HWBvtUg0QU5rQZeF+S0GnhdEGs15GznWw3JFsLTBTmtBl4XqFsNMl2Q32qI6YIyrQZ4AgAAAAAAAMCdERJFLIQjI6yGKGMhHBlBlNeZiMsIotzOROxSTJTbmeC2y74Eod0u+xKEdnteZyK6Pa8zwcmIMp2JEGU6E9AQAAAAAAAAAKUtKEag7VCGQNuhEIG2QzFm2w5Ft8u/BKHZLv8ShGZ7fqshtj2z1cAZg1KthhDFWw1AzR81z8ce'


def real_label_chart():
    from PIL import ImageDraw
    image = Image.new('RGB', (817, 468), 'white')
    draw = ImageDraw.Draw(image)
    for y in (93, 138, 182, 227, 271, 316, 360, 405):
        draw.line((124, y, 804, y), fill=(180, 180, 180))
    draw.line((124, 93, 124, 405), fill='black')
    for payload, size, origin in ((YEARS, (655, 16), (105, 414)),
                                  (COMMAS, (94, 329), (30, 85))):
        image.paste(Image.frombytes('L', size, zlib.decompress(base64.b64decode(payload))), origin)
    return image, (124, 93, 804, 405)


class FormattedLabelTests(unittest.TestCase):
    def test_explicit_notation_classifies_only_matching_measured_values(self):
        for texts, scale in ((('e^1', 'e^2'), AxisScale.LN),
                             (('exp(1)', 'exp(2)'), AxisScale.LN),
                             (('10^1', '10^2'), AxisScale.LOG10),
                             (('1970-01-01', '1970-01-02'), AxisScale.DATETIME)):
            ticks = tuple(td.TickReading(i * 100, parse_axis_label(text)[0], text,
                                         .9, (1, 1, 20, 12)) for i, text in enumerate(texts))
            self.assertEqual(scale, td._observed_axis_scale(ticks, AxisScale.LINEAR))
            self.assertEqual(AxisScale.LOG10, td._observed_axis_scale(ticks, AxisScale.LOG10))
        mismatched = tuple(td.TickReading(i * 100, i + 1, text, .9, (1, 1, 20, 12))
                           for i, text in enumerate(('exp(1)', 'exp(2)')))
        self.assertEqual(AxisScale.LINEAR, td._observed_axis_scale(mismatched, AxisScale.LINEAR))

    def test_real_pixels_are_read_without_sequence_repair(self):
        image, rect = real_label_chart()
        with patch.object(td, '_year_sequence_detection', side_effect=AssertionError('sequence repair')), \
                patch.object(td, '_complete_lattice_ticks', side_effect=AssertionError('invented tick')):
            result = td.detect_calibration_ticks(image, rect)
        self.assertEqual(AxisScale.DATETIME, result.x.scale)
        self.assertEqual(AxisScale.LOG10, result.y.scale)
        self.assertEqual([1981, 1985, 1989, 1993, 1997, 2001, 2005, 2009],
                         [t.value for t in result.x.ticks])
        self.assertEqual([10 ** n for n in range(9, 1, -1)], [t.value for t in result.y.ticks])
        for axis in (result.x, result.y):
            self.assertFalse(axis.unread_positions)
            self.assertTrue(all(t.bbox != (0, 0, 0, 0) for t in axis.ticks))
        engine = DigitizerEngine()
        engine.image = image
        engine.set_plot_rect(rect)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=rect))
        self.assertEqual(AxisScale.DATETIME, engine.calibration.scale_x)
        self.assertEqual(AxisScale.LOG10, engine.calibration.scale_y)
        for px, py in ((200, 150), (500, 300), (738, 405)):
            value = engine.calibration.pixel_to_data(px, py)
            inverse = engine.calibration.data_to_pixel(*value)
            self.assertAlmostEqual(px, inverse[0], places=6)
            self.assertAlmostEqual(py, inverse[1], places=6)


    def test_datetime_values_format_as_calendar_labels_and_round_trip(self):
        timestamp = parse_axis_label('2020-01-21')[0]
        self.assertEqual('2020-01-21', format_axis_value(timestamp, AxisScale.DATETIME))
        self.assertEqual(timestamp, parse_axis_value_input('2020-01-21', AxisScale.DATETIME))
        self.assertEqual('1981', format_axis_value(1981, AxisScale.DATETIME))
        self.assertEqual(1981.0, parse_axis_value_input('1981', AxisScale.DATETIME))
        self.assertEqual('01:02:03', format_axis_value(3723, AxisScale.DATETIME))
        self.assertEqual(3723.0, parse_axis_value_input('01:02:03', AxisScale.DATETIME))

    def test_strict_text_formats(self):
        for text, expected in (('.6', .6), ('1,000,000', 1e6), ('1981', 1981),
                               ('1e-3', .001), ('10^3', 1000), ('exp(2)', math.exp(2)),
                               ('e^2', math.exp(2)), ('01:02:03', 3723),
                               ('1970-01-02', 86400)):
            with self.subTest(text=text):
                self.assertAlmostEqual(expected, parse_axis_label(text)[0])
        for text in ('1,00', '1,000,00', '25:00', '2026-02-30'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_axis_label(text)


if __name__ == '__main__':
    unittest.main()
