"""Release-tree hygiene guards for the incremental refactor."""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "WinUx"


class PackageHygieneTests(unittest.TestCase):
    def test_stale_nested_package_tree_is_removed(self):
        self.assertFalse((PACKAGE / "WinUx").exists())

    def test_duplicate_package_test_tree_is_removed(self):
        self.assertFalse((PACKAGE / "tests").exists())

    def test_runtime_sources_do_not_reference_removed_nested_package(self):
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            if "vendor" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "WinUx.WinUx" in text or "WinUx/WinUx" in text or "WinUx\\\\WinUx" in text:
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
