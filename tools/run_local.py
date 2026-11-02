"""Open this edited checkout instead of the installed immutable release.

Usage: abaqus python tools/run_local.py
Close your other WinUx window after finishing transfers before running this.
Overrides are confined to this Python process; persisted updater state is untouched.
"""
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    os.environ['WINUX_APP_DIR'] = str(root)
    os.environ['WINUX_PREFER_BUNDLED_RUNTIME'] = '1'
    os.environ['WINUX_SKIP_UPDATE'] = '1'
    sys.path.insert(0, str(root))
    import run_winux
    assert Path(run_winux._project_dir()).resolve() == root
    print('WinUx local source: {}'.format(root), flush=True)
    run_winux.main()


if __name__ == '__main__':
    main()
