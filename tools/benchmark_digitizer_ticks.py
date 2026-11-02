"""Profile tick/OCR regression fixtures without starting the GUI.

abaqus python tools/benchmark_digitizer_ticks.py --case linear --repeat 2 --profile
abaqus python tools/benchmark_digitizer_ticks.py --case datetime --repeat 2
"""
import argparse
import cProfile
from pathlib import Path
import pstats
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.plotdigitizer.core.tick_detection import detect_calibration_ticks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('linear', 'datetime'), default='linear')
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if args.case == 'datetime':
        from test_digitizer_tick_scale_detection import _rotated_iso_datetime_chart
        image, rect, _dates, _values = _rotated_iso_datetime_chart()
    else:
        from test_digitizer_tick_auto_calibration import make_chart
        image, rect = make_chart()
    profile = cProfile.Profile() if args.profile else None
    expected = None
    for run in range(max(1, args.repeat)):
        start = time.perf_counter()
        if profile is not None:
            profile.enable()
        result = detect_calibration_ticks(image, rect)
        if profile is not None:
            profile.disable()
        elapsed = time.perf_counter() - start
        signature = [(axis.scale.value, [(tick.position, tick.value, tick.text) for tick in axis.ticks])
                     for axis in (result.x, result.y)]
        assert result.ready, result
        if expected is not None:
            assert signature == expected, 'Tick readings changed between runs'
        expected = signature
        print('{} run {} ({}): {:.2f} ms; X={} {}, Y={} {}'.format(
            args.case, run + 1, 'cold' if run == 0 else 'warm', elapsed * 1000,
            result.x.scale.value, len(result.x.ticks), result.y.scale.value, len(result.y.ticks)), flush=True)
    if profile is not None:
        pstats.Stats(profile).strip_dirs().sort_stats('tottime').print_stats(25)


if __name__ == '__main__':
    main()
