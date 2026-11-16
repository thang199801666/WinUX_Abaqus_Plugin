"""Repeatable detector timings (no GUI/OCR or changes to source images).

abaqus python tools/benchmark_digitizer_detector.py --repeat 3 --verify [chart.png]
"""
import argparse
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core import ExtractionSettings
from WinUx.plotdigitizer.core import extraction


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image', nargs='?')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--scalar', action='store_true')
    parser.add_argument('--verify', action='store_true', help='Compare each result with the Python fallback')
    args = parser.parse_args()
    if args.scalar and hasattr(extraction, 'np'):
        extraction.np = None
    print('Detector backend: {}; repeat={}; GUI/OCR excluded'.format(
        'NumPy ' + extraction.np.__version__ if extraction.np is not None else 'Python',
        max(1, args.repeat)), flush=True)
    if args.image:
        image = Image.open(args.image).convert('RGB')
    else:
        image = Image.new('RGB', (1400, 900), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((100, 80, 100, 800, 1300, 800), fill='black', width=2)
        draw.line([(x, 700 - round(500 * ((x - 100) / 1200) ** .5))
                   for x in range(100, 1301)], fill=(220, 45, 55), width=3)
    for factor in (1, 2):
        sample = image if factor == 1 else image.resize((image.width * factor, image.height * factor))
        roi = (0, 0, sample.width - 1, sample.height - 1)
        colors = extraction.detect_curve_colors(sample, roi)
        target = colors[0] if colors else (220, 45, 55)
        # All stages use identical explicit inputs across accelerated/scalar runs.
        for name, work in (
            ('region', lambda: extraction.detect_plot_area(sample)),
            ('palette', lambda: extraction.detect_curve_colors(sample, roi)),
            ('extract', lambda: extraction.extract_curve(sample, roi, target, ExtractionSettings())),
        ):
            if args.verify and extraction.np is not None:
                with patch.object(extraction, 'np', None):
                    expected = work()
                assert work() == expected, '{} accelerated/scalar mismatch'.format(name)
            times, result = [], None
            for _ in range(max(1, args.repeat)):
                start = time.perf_counter()
                result = work()
                times.append(time.perf_counter() - start)
            summary = result if name == 'region' else len(result)
            print('{}x{} {:7s}: {:8.2f} ms; result={}'.format(
                sample.width, sample.height, name, statistics.median(times) * 1000, summary), flush=True)


if __name__ == '__main__':
    main()
