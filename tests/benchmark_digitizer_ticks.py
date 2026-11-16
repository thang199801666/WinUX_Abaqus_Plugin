"""Benchmark actual-image tick OCR with Abaqus Python; no GUI or full suite."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from WinUx.plotdigitizer.core.tick_detection import detect_calibration_ticks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--rect', nargs=4, type=int, required=True, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    parser.add_argument('--repeat', type=int, choices=range(1, 11), default=2)
    parser.add_argument('--align-axes', action='store_true', help='Align left/bottom region edges before OCR, as Smart Region does')
    args = parser.parse_args()
    with Image.open(args.image) as source:
        image = source.convert('RGB')
    for run in range(args.repeat):
        start = time.perf_counter()
        result = detect_calibration_ticks(image, tuple(args.rect), align_axes=args.align_axes)
        record = {'run': run + 1, 'seconds': round(time.perf_counter() - start, 4)}
        if result.aligned_rect is not None:
            record['aligned_rect'] = result.aligned_rect
        for axis in ('x', 'y'):
            reading = getattr(result, axis)
            record[axis] = {'ready': reading.ready, 'scale': reading.scale.value,
                            'ticks': [[t.position, t.value] for t in reading.ticks],
                            'unread': reading.unread_positions}
        print(json.dumps(record))


if __name__ == '__main__':
    main()
