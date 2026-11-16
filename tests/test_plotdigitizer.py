"""Interactive direct-run regression for Plot Digitizer.

Recommended Windows/Abaqus launch::

    abaqus python tests/test_plotdigitizer.py

The canonical direct launcher is ``run_plotdigitizer.py``. This test wrapper
intentionally delegates to the same entry point so test and production-direct
startup cannot drift apart.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    from run_plotdigitizer import main as run_direct
    return run_direct(sys.argv[1:] if argv is None else argv)


if __name__ == '__main__':
    raise SystemExit(main())
