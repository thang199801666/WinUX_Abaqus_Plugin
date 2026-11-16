"""Main-runner selection without mutating installed runtime caches."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
from winux_runtime import installation_state as state
from winux_runtime.update.manifest import REQUIRED_FILES


class RuntimeRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = {'LOCALAPPDATA': str(self.base), 'WINUX_INSTALL_MODE': 'versioned'}

    def deployment(self, name, version='1.1.6', revision=1):
        directory = self.base / name
        for relative in REQUIRED_FILES:
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(version if relative == 'VERSION' else '# fixture')
        (directory / 'update_manifest.json').write_text(json.dumps(
            {'version': version, 'package_revision': revision}))
        return directory

    def test_identity_rejects_stale_malformed_and_noninteger_revisions(self):
        directory = self.deployment('bundle')
        path = directory / 'update_manifest.json'
        for identity in ({'version': '1.1.5', 'package_revision': 999},
                         {'version': '1.1.6', 'package_revision': True},
                         {'version': '1.1.6', 'package_revision': 2.5},
                         {'version': '1.1.6', 'package_revision': float('inf')},
                         {'version': '1.1.6', 'package_revision': -2}, [], None):
            path.write_text(json.dumps(identity))
            self.assertEqual(state.package_revision(str(directory)), -1)
        path.write_text('{broken')
        self.assertEqual(state.package_revision(str(directory)), -1)
        path.unlink()
        self.assertEqual(state.package_revision(str(directory)), -1)

    def test_equal_release_prefers_higher_revision_only(self):
        bundle = self.deployment('bundle', revision=2)
        for revision, prefer_bundle in ((1, True), (2, False), (3, False)):
            active = self.deployment('active', revision=revision)
            with patch.object(state, 'load_state', return_value={'active_version': '1.1.6'}), \
                    patch.object(state, 'version_dir', return_value=str(active)):
                result = state.resolve_active_installation(str(bundle), self.env, recover=False)
            self.assertEqual(Path(result), bundle if prefer_bundle else active)

    def test_semantic_version_wins_over_revision(self):
        bundle = self.deployment('bundle', revision=200)
        future = self.deployment('future', version='1.1.7', revision=1)
        older = self.deployment('older', version='1.1.5', revision=999)
        self.assertTrue(state.deployment_is_newer(str(future), str(bundle)))
        self.assertTrue(state.deployment_is_newer(str(bundle), str(older)))

    def test_recovered_history_does_not_shadow_newer_bundle(self):
        bundle = self.deployment('bundle', revision=2)
        recovered = self.deployment('previous', revision=1)
        with patch.object(state, 'load_state', return_value={'active_version': 'broken'}), \
                patch.object(state, 'recover_interrupted_transaction'), \
                patch.object(state, 'version_dir', return_value=str(self.base / 'missing')), \
                patch.object(state, '_recover_from_history', return_value=str(recovered)) as recover:
            self.assertEqual(Path(state.resolve_active_installation(str(bundle), self.env)), bundle)
            recover.assert_called_once()

    def test_readonly_selection_never_recovers_or_writes_state(self):
        bundle = self.deployment('bundle')
        with patch.object(state, 'load_state', return_value={'active_version': 'broken'}), \
                patch.object(state, 'version_dir', return_value=str(self.base / 'missing')), \
                patch.object(state, 'recover_interrupted_transaction') as transaction, \
                patch.object(state, '_recover_from_history') as history:
            self.assertEqual(Path(state.resolve_active_installation(str(bundle), self.env, recover=False)), bundle)
            transaction.assert_not_called()
            history.assert_not_called()

    def test_stale_environment_rebinds_to_runner_adjacent_hotfix(self):
        bundled = self.deployment('bundle', revision=2)
        old = self.deployment('old', revision=1)
        with patch.dict(os.environ, dict(self.env, WINUX_APP_DIR=str(old)), clear=True), \
                patch.object(run_winux, '__file__', str(bundled / 'run_winux.py')):
            self.assertEqual(Path(run_winux._project_dir()), bundled)

    def test_switch_rejects_older_and_incomplete_but_accepts_future_release(self):
        bundle = self.deployment('bundle', revision=2)
        older = self.deployment('old', revision=1)
        future = self.deployment('future', version='1.1.7')
        incomplete = self.deployment('incomplete', version='1.1.8')
        (incomplete / 'DearUIQt' / '__init__.py').unlink()
        with patch.object(sys, 'path', list(sys.path)), patch.dict(os.environ, self.env):
            for candidate, expected in ((older, bundle), (incomplete, bundle), (future, future)):
                self.assertEqual(Path(run_winux._switch_to_active_project(
                    str(bundle), {'active_dir': str(candidate)})), expected)

    def test_main_keeps_update_checks_and_imports_current_feature_modules(self):
        old = self.deployment('old', revision=0)
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        def application():
            import WinUx.view
            import WinUx.services.transfer_timestamps as legacy_transfer_timestamps
            from WinUx.services.transfer import timestamps as transfer_timestamps
            from WinUx.dialogs.local_folder_form import LocalPathDialog, LocalFolderDialog
            from WinUx.dialogs.local_file_form import LocalFileDialog
            from WinUx.dialogs.path_selection import PathSelectionOptions
            import DearUIQt.backends.shared_scrollers as scrollers
            self.assertEqual(Path(WinUx.view.__file__).resolve(), ROOT / 'WinUx' / 'ui' / 'main_window.py')
            self.assertIs(legacy_transfer_timestamps, transfer_timestamps)
            self.assertEqual(Path(transfer_timestamps.__file__).resolve(), ROOT / 'WinUx' / 'services' / 'transfer' / 'timestamps.py')
            self.assertTrue(issubclass(LocalFolderDialog, LocalPathDialog))
            self.assertTrue(issubclass(LocalFileDialog, LocalPathDialog))
            self.assertTrue(PathSelectionOptions('file', multiple=True).multiple)
            self.assertTrue(PathSelectionOptions('folder', multiple=True).multiple)
            self.assertEqual(Path(scrollers.__file__).resolve().parents[1], ROOT / 'DearUIQt')
        with patch.dict(os.environ, dict(self.env, WINUX_APP_DIR=str(ROOT)), clear=True), \
                patch.object(sys, 'argv', ['run_winux.py']), \
                patch.object(sys, 'path', list(sys.path)), \
                patch.object(run_winux, '_existing_winux_pid', return_value=None), \
                patch('winux_runtime.update.updater.update_local_if_newer',
                      return_value={'active_dir': str(old), 'available': False}) as updater:
            run_winux.main(run_callable=application)
            updater.assert_called_once()
            self.assertNotEqual(os.environ.get('WINUX_SKIP_UPDATE'), '1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
