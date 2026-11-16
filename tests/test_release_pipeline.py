"""Release-pipeline regression guards."""
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]

from tools import release


class ReleasePipelineTests(unittest.TestCase):
    def test_manifest_diff_reports_changed_new_and_deleted_paths(self):
        previous = {"files": [
            {"path": "same.py", "size": 1, "sha256": "a" * 64},
            {"path": "changed.py", "size": 1, "sha256": "b" * 64},
            {"path": "deleted.py", "size": 1, "sha256": "c" * 64},
        ]}
        current = {"files": [
            {"path": "same.py", "size": 1, "sha256": "a" * 64},
            {"path": "changed.py", "size": 2, "sha256": "d" * 64},
            {"path": "new.py", "size": 1, "sha256": "e" * 64},
        ]}
        changed, deleted = release.manifest_diff(previous, current)
        self.assertEqual(changed, ["changed.py", "new.py"])
        self.assertEqual(deleted, ["deleted.py"])


    def test_actual_tree_diff_uses_real_file_bytes_not_manifest_state(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            current = Path(temp) / "current"
            base.mkdir(); current.mkdir()
            (base / "same.py").write_text("same\n", encoding="utf-8")
            (current / "same.py").write_text("same\n", encoding="utf-8")
            (base / "changed.py").write_text("old\n", encoding="utf-8")
            (current / "changed.py").write_text("new\n", encoding="utf-8")
            (base / "deleted.txt").write_text("gone\n", encoding="utf-8")
            (current / "new.txt").write_text("new\n", encoding="utf-8")
            changed, deleted = release.actual_tree_diff(base, current)
            self.assertEqual(changed, ["changed.py", "new.txt"])
            self.assertEqual(deleted, ["deleted.txt"])

    def test_actual_tree_diff_accepts_full_zip_with_project_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            current = Path(temp) / "current"
            base.mkdir(); current.mkdir()
            (base / "a.py").write_text("a=1\n", encoding="utf-8")
            (current / "a.py").write_text("a=2\n", encoding="utf-8")
            archive_path = Path(temp) / "baseline.zip"
            release.create_full_zip(archive_path, root=base)
            changed, deleted = release.actual_tree_diff(archive_path, current)
            self.assertEqual(changed, ["a.py"])
            self.assertEqual(deleted, [])


    def test_baseline_generated_cleanup_paths_collapses_cache_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Project"
            cache = root / "pkg" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"junk")
            (root / "trace.log").write_text("junk", encoding="utf-8")
            archive_path = Path(temp) / "baseline.zip"
            # Build this zip manually because create_full_zip intentionally
            # excludes exactly the generated artifacts under test.
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.write(cache / "module.pyc", arcname="Project/pkg/__pycache__/module.pyc")
                archive.write(root / "trace.log", arcname="Project/trace.log")
            cleanup = release.baseline_generated_cleanup_paths(archive_path)
            self.assertEqual(cleanup, ["pkg/__pycache__/", "trace.log"])

    def test_full_archive_excludes_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Project"
            root.mkdir()
            (root / "keep.py").write_text("print('ok')\n", encoding="utf-8")
            cache = root / "pkg" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "bad.pyc").write_bytes(b"junk")
            (root / "debug.log").write_text("junk", encoding="utf-8")
            target = Path(temp) / "full.zip"
            release.create_full_zip(target, root=root)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
            self.assertIn("Project/keep.py", names)
            self.assertFalse(any("__pycache__" in name for name in names))
            self.assertFalse(any(name.endswith(".pyc") or name.endswith(".log") for name in names))

    def test_changes_archive_always_contains_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Project"
            root.mkdir()
            (root / "update_manifest.json").write_text("{}\n", encoding="utf-8")
            (root / "changed.py").write_text("x=1\n", encoding="utf-8")
            target = Path(temp) / "changes.zip"
            release.create_changes_zip(target, ["changed.py"], ["old.py"], root=root)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                deleted = archive.read("DELETE_THESE_PATHS.txt").decode("utf-8")
            self.assertIn("changed.py", names)
            self.assertIn("update_manifest.json", names)
            self.assertIn("old.py", deleted)

    def test_changes_archive_preserves_manifest_covered_readme_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Project"
            root.mkdir()
            (root / "update_manifest.json").write_text("{}\n", encoding="utf-8")
            (root / "CHANGES_ONLY_README.txt").write_text("WinUx release instructions\n", encoding="utf-8")
            target = Path(temp) / "changes.zip"
            release.create_changes_zip(target, ["CHANGES_ONLY_README.txt"], [], root=root)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist().count("CHANGES_ONLY_README.txt"), 1)
                self.assertEqual(archive.read("CHANGES_ONLY_README.txt"), (root / "CHANGES_ONLY_README.txt").read_bytes())
            self.assertTrue(release.verify_changes_archive(target))

    def test_release_tool_is_fail_closed_and_verifies_extracted_full_archive(self):
        source = (ROOT / "tools" / "release.py").read_text(encoding="utf-8")
        self.assertIn("source_descriptor(str(extracted), verify_hashes=True)", source)
        self.assertIn("assert_clean_tree(extracted)", source)
        self.assertIn("if completed.returncode:", source)
        self.assertIn("raise RuntimeError", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
