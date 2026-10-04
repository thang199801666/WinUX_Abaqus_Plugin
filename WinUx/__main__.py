"""Allow ``python -m WinUx`` to use the diagnostic-aware entry point."""

import os

from .application import run


if __name__ == "__main__":
    os.environ.setdefault("WINUX_STANDALONE_PROCESS", "1")
    run()
