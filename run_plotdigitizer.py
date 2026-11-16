"""Direct Plot Digitizer launcher for bundled Python or ``abaqus python``.

Examples
--------
    abaqus python run_plotdigitizer.py
    abaqus python run_plotdigitizer.py C:\\data\\chart.png
    abaqus python run_plotdigitizer.py project.pdg
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    import run_winux
    run_winux._configure_bundled_dependencies(str(ROOT))
    from WinUx.plotdigitizer.standalone import main as open_digitizer
    return open_digitizer(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
