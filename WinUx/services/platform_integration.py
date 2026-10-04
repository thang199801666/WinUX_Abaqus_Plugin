"""Cross-platform integrations with the host operating system."""

import os
import subprocess
import sys


def launch_path(path):
    """Open ``path`` with the operating system's default application."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
