"""Private snapshot cleanup; callers execute filesystem work on a worker."""
from pathlib import Path
import shutil
import time


class ClipboardCache:
    def __init__(self, root):
        self.root = Path(root)

    def discard(self, path):
        path = Path(path)
        if path.resolve().parent != self.root.resolve():
            raise ValueError("clipboard snapshot must be a direct child of its cache")
        if path.is_dir():
            shutil.rmtree(str(path), ignore_errors=True)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def cleanup(self):
        self.root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 7 * 24 * 60 * 60
        for child in self.root.iterdir():
            try:
                if child.stat().st_mtime < cutoff:
                    self.discard(child)
            except (OSError, ValueError):
                continue
