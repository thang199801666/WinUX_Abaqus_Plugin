"""Release-tree hygiene guards for the incremental refactor."""
from __future__ import annotations

from pathlib import Path
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "WinUx"


class PackageHygieneTests(unittest.TestCase):
    def test_stale_nested_package_tree_is_removed(self):
        self.assertFalse((PACKAGE / "WinUx").exists())

    def test_duplicate_package_test_tree_is_removed(self):
        self.assertFalse((PACKAGE / "tests").exists())


    def test_release_tree_contains_no_markdown_files(self):
        # Markdown documents (README/ARCHITECTURE/AGENT_GUIDE) are developer
        # docs that live in the repository but must never ship: the update
        # manifest walk packages the deployment tree and drops every ignored
        # suffix (.md/.markdown) at packaging time.
        import tempfile

        import winux_update_manifest

        for suffix in (".md", ".markdown"):
            self.assertIn(suffix, winux_update_manifest.IGNORED_SUFFIXES)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VERSION").write_text("1.1.4\n")
            (root / "WinUx").mkdir()
            (root / "WinUx" / "__main__.py").write_text("# app\n")
            (root / "DearUIQt").mkdir()
            (root / "DearUIQt" / "__init__.py").write_text("# dear ui qt\n")
            (root / "README.md").write_text("readme\n")
            (root / "DearUIQt" / "ARCHITECTURE.md").write_text("docs\n")
            shipped = winux_update_manifest.iter_deployment_files(str(root))
        shipped_files = sorted(
            name.replace(os.sep, "/") for name in shipped if Path(name).suffix
        )
        self.assertEqual(shipped_files, ["DearUIQt/__init__.py", "WinUx/__main__.py"])
        self.assertFalse(
            any(Path(name).suffix in {".md", ".markdown"} for name in shipped)
        )

        # The reusable in-tree package surface also stays markdown-free.
        in_tree_markdown = [
            path.relative_to(ROOT).as_posix()
            for path in PACKAGE.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in {".md", ".markdown"}
        ]
        self.assertEqual(in_tree_markdown, [])

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
