"""Pixel regressions from the user's 537x441 chart (axis labels only)."""
import base64
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageOps
from test_digitizer_tick_auto_calibration import _font
from WinUx.plotdigitizer.core import tick_detection as td

# Cropped grayscale axis-label pixels, not an assumed/generated numeric series.
X_LABELS = (
    'eNrtltlX4kgUxv/tmcd56Aft5cwZ7WPbNm6NCu4tAhEIURQdbQQElH1NIIlBtkCAVKoyCdBic9oU79N5yjl8dfm+3626KVX9/fx+/g8PEst0VcbroFgpCeDHok6jbyQGNYZuwoGy90izbWjoQGnVleGyOkNX+whjpCMoP944muti5GpPKNF1iA/YrzJMfRywLht64EoVcRSQ/0VAJLKlSntgDbbZEtsZCxDncpPOuz4WePnc47FFRo7ES3vFIGk/SXpczqL+2g46SZePM0gMuIjDKw7+gzunyJOIZOijFvfutgavCnvppS45DEwlcUa5HVkFFxDkNB2RVkbALu2sgViMnXoJUtARSP/qAfkJgZzwUQ5XQy/VClMkcVYd74Bda5H1rhVwO0UkDjLs2T9DG927pbmUwQrGSpbpDavWRlRadXPR1SuDjnajnk+WxpB4lGOdG4yRDzl1tvW+NqDy5LRnBU7EOAfx9BOzvdnBEZcLCZ7e3Bu2uxNa/Jg2EDdThcfYQgDoO/ZvH3+3cjXhAlQq1dDbe91mM1F8DC7ePbdc+CurovKaH3fsiuu3QO28CQwYxYijVQPi8NqsdTD0rqob2nHkbjbDBkcU1Gv23cZwIUT9c2PisNEMzA2Ig4jp4jZY6mGIIwWhrt2MJY6gptsfEu9GHd/W0hhx+YtOXK0ue/LXm+FJF0BqBD/lR6FgzjQmXvhDC/tkceFOXXwljlT0ntTPUdgZD5kNiAOvlVPV7GxJs1Y7Np1YzBnD8oAYEVdRI3Bwg4MTnh8Q75KzxA21E8YORCScbiWnGORQON9NgEHA41Toa9p46uedNl5H0Nwzuazm7CSNp5uTtZ3maI5k7MTj8y/0n4K20TcpHPHk8j1UldkLfXB9Po4QH6nXv0bK6VZFVVNvNexyyBwqZw+IxlTEe0mXL9VG0xGX3PPJTn1/r4abhwHnVR47xvV5674q6O2TfQvOKDFHNQ2aw/s9t7xeVAmaopXUobs1oZCYTMRyNlCw52RYGBtozFwrILn2gIvJbfgkRM/kkdwO2k8vtt8dsa8SR3crDxCSS10IJM/SI+zbzTyWOAKKHLVEnvoKnIY4BP3b5TzsH+GId08OsyJQcPlUyX8Ub8raCJJ7V8c+PSD/6hrEE+5SB0CkAJlYqCHRYREmWgIglKxmGcqwYqMYSdM+p/0+76Q2vNgx1/++4qBWvf3GQa7bbou3qxGD0dx0fiWJlRiK2xuZdYvv2OSXsMQB6W9ZZvZtNmdOmYJ4+KRTtZkpmzmKudnSHxa/2WxuHheQNs1rf35c4yy8pAUMLEfB6/ef0IdlrehlO2yXcovbPtuXy59nGyp7T/2Hn+OweFgNvlk/stkC7THKUihU6uCnXJcJhwqS2ovWB5c+rmOwa2ArE4yxsvp4L8tCIhBlJMMtBp+0iz5KFwCbLRaLdAuzH0VGg1xJKLCZDt5zuC+nVMhrRRkJny+n6Uo9MdgZBjRYgZr5gibmZfYByHwiECtPiJFUCAVSPFAb0W4zq2sF+eV3F3/kXuhGxwN7Q9B1CA6WQVx9NCqMhg/WiTosrU5RWlWnq/msQ1CdIuAL8a8DImVM4NnAf9hWo5o='
)
Y_12000 = (
    'eNqNjt1PgnAUhv//7nLO3FoluoURNDXNHCs/aa7sApVBUqmBH6C/nIoCAueEq2666r15drZn73sQEXAf+MZfwp4EfDJ1ET1d6n44IU1ZGof3TusoswBh9d59s4Doj1zxE3FQblRzwtZVSuVyRnTth3yNv37zjQpfK/ALotQT6RniaGAta/HxlCuRRTFpqBHRmmQYItDqWo6KprXi2dAKABzhxJAoGUGN9YpxB712VMrcbnCTuhmjd7+3EMwq23GeE4Ow90g8T0FoHzYvKjt0OVb/seynbFPbBeLZK2I/rlwd+xiEUyzvoE3/dvl1arj1AxhSgh80KLN1YMDmjjZL6TlMY20TvXpujtZphGHZnOy0EpdcSvLsfKzA0KNAY1LZJL8iCOuFh745CjNZg2v0VOKFH2hyfwkYLPsvug0E/xPyBSKrbi0='
)


def tile(data, size):
    return Image.frombytes('L', size, zlib.decompress(base64.b64decode(data)))


class CloseTitleOcrTests(unittest.TestCase):
    def test_six_pixel_2000_does_not_inherit_an_unreliable_font_face(self):
        # Original -03 label pixels: a face hinted from another tiny label
        # previously turned printed 2000 into 2008.
        image = tile('eNp9j8sLAVEYxf94ysKChYWRZwoppTDjzpUkRZL3I+SVxx0JMXMzY+7cz8jGht/inMXpdDoAvzDhd6T3sSwOGOtjVOgYbISxNLD0HpKltkFuWtN5XbiWGglMt8EVnfnOkzjRJg67qSazhhRiwDNVKcZAF1pI5PDwMNIoDk1L9ptgpeulyBOof4RzHKj7EK6tiEI3zqE6D+/2wph2o3QWWt5b3iPCNltLEZPoxPk+nyifga2zqcoF+Bt78aNf9u/XC3LG8IM=', (27, 10))
        rows = ('.###....###....###....###', '....#..#...#..#...#..#...',
                '...##.##...####...#.##...', '..#...##...#.##...#.##...',
                '##.....#...#..#...#..#...', '#####...###....###....###')
        mask = [bytearray(c == '#' for c in row) for row in rows]
        for hint in (None, 5):
            reading = td._read_small_source_word(image, (1, 2, 25, 7), mask, font_hint=hint)
            self.assertIsNotNone(reading)
            self.assertEqual(2000, reading[1])

    def test_close_x_title_does_not_merge_words_or_erase_decimal(self):
        image = Image.new('RGB', (537, 441), 'white')
        draw = ImageDraw.Draw(image)
        rect = (136, 79, 496, 368)
        for x in (136, 180, 224, 269, 315, 360, 405, 449, 496):
            draw.line((x, 79, x, 368), fill=(220, 220, 220))
        draw.rectangle(rect, outline=(90, 90, 90), width=2)
        draw.rectangle((22, 46, 511, 414), outline=(130, 130, 130), width=3)
        image.paste(tile(X_LABELS, (370, 12)), (128, 372))
        draw.text((240, 387), 'AverageLVDT (in)', font=_font(12), fill=(100, 100, 100))
        for box in (rect, (134, 78, 498, 370)):
            with self.subTest(box=box), patch.object(td, '_read_rotated_source_word',
                                                    side_effect=AssertionError('unnecessary rotated OCR')):
                result = td._detect_axis(image, box, 'x', td.AxisScale.LINEAR)
            self.assertTrue(result.ready)
            self.assertEqual([0, .4, .8, 1.2, 1.6, 2, 2.4, 2.8, 3.2], [t.value for t in result.ticks])
            self.assertFalse(result.unread_positions)
            self.assertTrue(all(t.bbox[3] < 387 for t in result.ticks))

    def test_faint_12000_survives_threshold_shortlisting(self):
        image = Image.new('RGB', (160, 300), 'white')
        image.paste(tile(Y_12000, (38, 11)), (96, 254))
        bbox = (97, 256, 132, 262)
        mask = td._binary_mask(image.crop((97, 256, 133, 263)))
        for hint in (None, 5):
            result = td._read_small_source_word(image, bbox, mask, font_hint=hint)
            self.assertIsNotNone(result)
            self.assertEqual(12000, result[1])

    def test_fast_autocontrast_is_pixel_equivalent_to_pillow(self):
        for low, high in ((0, 255), (17, 227), (80, 190), (100, 100)):
            image = Image.frombytes('L', (16, 16), bytes(low + (high - low) * i // 255 for i in range(256)))
            self.assertEqual(ImageOps.autocontrast(image).tobytes(), td._autocontrast_gray(image).tobytes())


if __name__ == '__main__':
    unittest.main()
