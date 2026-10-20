import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from winux_native_runtime import native_runtime_path


@unittest.skipUnless(os.name == "nt", "Windows native runtime discovery")
class InstalledNativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ["LOCALAPPDATA"]) / "Temp/opencode"
        self.directory = tempfile.TemporaryDirectory(dir=str(scratch))
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.runtime = self.project / "DearUIQt/native/runtime" / "cp{}{}-win_amd64".format(*sys.version_info[:2])

    def make_runtime(self, cache_tag=None):
        package = self.runtime / "dearpygui"
        package.mkdir(parents=True)
        for name in ("__init__.py", "dearpygui.py", "_dearpygui.pyd"):
            (package / name).write_bytes(b"test")
        (self.runtime / "dearuiqt_build.json").write_text(json.dumps({
            "native_abi": 1, "python_cache_tag": cache_tag or sys.implementation.cache_tag,
        }), encoding="utf-8")

    def test_missing_runtime_keeps_legacy_fallback(self):
        self.assertIsNone(native_runtime_path(str(self.project), environ={}))

    def test_matching_installed_runtime_is_selected(self):
        self.make_runtime()
        self.assertEqual(native_runtime_path(str(self.project), environ={}), str(self.runtime))

    def test_wrong_python_abi_is_never_loaded(self):
        self.make_runtime(cache_tag="cpython-999")
        self.assertIsNone(native_runtime_path(str(self.project), environ={}))

    def test_explicit_rollback_selects_legacy_backend(self):
        self.make_runtime()
        self.assertIsNone(native_runtime_path(str(self.project), environ={"WINUX_NATIVE_WINDOWS": "0"}))

    def test_runner_searches_native_runtime_before_old_vendor(self):
        import run_winux
        self.make_runtime()
        with patch.dict(os.environ, {"WINUX_NATIVE_WINDOWS": "1"}):
            self.assertEqual(run_winux._vendor_candidates(str(self.project))[0], str(self.runtime))


if __name__ == "__main__":
    unittest.main()
