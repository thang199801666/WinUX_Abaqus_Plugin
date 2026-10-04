"""Startup/version-discovery regression checks runnable with abaqus python."""
import importlib.util
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import winux_updater as updater
import winux_update_manifest as manifest


def deployment(root, version):
    root.mkdir(parents=True, exist_ok=True)
    for name in manifest.REQUIRED_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(version + "\n" if name == "VERSION" else "# fixture\n", encoding="utf-8")
    manifest.write_manifest(str(root))
    return root


class StartupFastPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = deployment(self.root / "local", "1.2.0")
        self.server = deployment(self.root / "server", "1.2.0")

    def tearDown(self):
        self.temp.cleanup()

    def test_current_version_does_not_read_manifest_or_stat_release_files(self):
        with patch.object(updater, "source_descriptor", side_effect=AssertionError("manifest IO before startup")), \
             patch.object(updater, "source_is_valid", side_effect=AssertionError("release scan before startup")):
            status = updater.get_update_status(str(self.local), str(self.server), environ={})
        self.assertFalse(status["available"])
        self.assertFalse(status["manifest_checked"])
        self.assertEqual(status["reason"], "local version is current")

    def test_normal_launch_reads_shared_version_only_once_and_never_shows_update_ui_when_current(self):
        prompt = Mock(side_effect=AssertionError("unexpected source/update prompt"))
        with patch.object(updater, "read_version", wraps=updater.read_version) as read, \
             patch.object(updater, "source_descriptor", side_effect=AssertionError("unnecessary manifest read")), \
             patch.object(updater, "_log"):
            status = updater.update_local_if_newer(str(self.local), server_dir=str(self.server), environ={},
                source_prompt=prompt, dialog_available=prompt, sync_callable=prompt)
        self.assertFalse(status["updated"])
        shared_reads = [call for call in read.call_args_list if Path(call.args[0]) == self.server]
        self.assertEqual(len(shared_reads), 1)
        prompt.assert_not_called()

    def test_version_is_reprobed_on_each_launch_not_cached_between_launches(self):
        first = updater.get_update_status(str(self.local), str(self.server), environ={})
        (self.server / "VERSION").write_text("1.3.0\n", encoding="utf-8")
        second = updater.get_update_status(str(self.local), str(self.server), environ={})
        self.assertFalse(first["available"])
        self.assertTrue(second["available"])
        self.assertEqual(second["server_version"], "1.3.0")
        self.assertTrue(second["manifest_checked"])
        self.assertFalse(second["manifest_valid"])

    def test_newer_version_still_validates_the_manifest(self):
        deployment(self.server, "1.3.0")
        with patch.object(updater, "source_descriptor", wraps=updater.source_descriptor) as descriptor:
            status = updater.get_update_status(str(self.local), str(self.server), environ={})
        self.assertTrue(status["available"])
        self.assertTrue(status["manifest_checked"])
        self.assertTrue(status["manifest_valid"])
        descriptor.assert_called_once_with(str(self.server), verify_hashes=False)

    def test_manifest_only_immutable_release_source_is_still_supported(self):
        source = self.root / "published"
        release = deployment(source / "releases" / "1.3.0", "1.3.0")
        payload = manifest.build_manifest(str(release), release_path="releases/1.3.0")
        manifest.write_manifest(str(source), payload)
        status = updater.get_update_status(str(self.local), str(source), environ={})
        self.assertTrue(status["available"])
        self.assertEqual(status["release_dir"], str(release))

    def test_skip_update_does_not_probe_the_network_during_source_resolution(self):
        with patch.object(updater, "configured_update_source", side_effect=AssertionError("network discovery")), \
             patch.object(updater, "source_descriptor", side_effect=AssertionError("manifest discovery")):
            status = updater.get_update_status(str(self.local), str(self.server), environ={"WINUX_SKIP_UPDATE": "1"})
        self.assertFalse(status["available"])

    def test_update_rechecks_fresh_version_after_lock(self):
        deployment(self.server, "1.3.0")
        class Lock:
            def acquire(self):
                (self.server / "VERSION").write_text("1.2.0\n", encoding="utf-8")
            def release(self):
                pass
        lock = Lock()
        lock.server = self.server
        sync = Mock()
        with patch.object(updater, "_log"):
            status = updater.update_local_if_newer(str(self.local), str(self.server), environ={},
                dialog_available=lambda *args: True, progress_factory=lambda *args: None,
                lock_factory=lambda path: lock, sync_callable=sync)
        self.assertFalse(status["updated"])
        self.assertEqual(status["server_version"], "1.2.0")
        sync.assert_not_called()

    def test_accepted_update_keeps_transactional_installer_path(self):
        deployment(self.server, "1.3.0")
        sync = Mock(return_value="1.3.0")
        lock = Mock()
        before_sync = Mock()
        with patch.object(updater, "_log"):
            status = updater.update_local_if_newer(str(self.local), str(self.server), environ={},
                dialog_available=lambda *args: True, progress_factory=lambda *args: None,
                lock_factory=lambda path: lock, sync_callable=sync, before_sync=before_sync)
        self.assertTrue(status["updated"])
        before_sync.assert_called_once()
        sync.assert_called_once_with(str(self.server), str(self.local), progress_callback=None)


class LazyViewStartupTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "requires the Windows Dear PyGui runtime")
    def test_importing_view_does_not_resolve_dialog_constructors(self):
        path = Path(__file__).resolve().parents[1] / "WinUx" / "view.py"
        spec = importlib.util.spec_from_file_location("WinUx._startup_view_check", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertNotIn("LoginDialog", vars(module))
        self.assertNotIn("BlockingDialog", vars(module))
        self.assertNotIn("TransferCenterDialog", vars(module))
        constructor = Mock()
        module.LoginDialog = constructor
        self.assertIs(module._dialog_type("LoginDialog"), constructor)
        view = object.__new__(module.WinUXView)
        callback = Mock()
        view.callbacks = {"login": callback}
        dialog = view.show_login()
        constructor.assert_called_once_with(view, callback)
        self.assertIs(dialog, constructor.return_value)


if __name__ == "__main__":
    unittest.main()
