"""Launcher regression: abaqus python tests/test_launcher.py."""
import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
from winux_runtime import launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix='winux-launcher-',
            dir=Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode')
        self.addCleanup(self.temporary.cleanup)
        self.previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, self.previous_cwd)
        os.chdir(self.temporary.name)

    def test_bundled_root_does_not_depend_on_cae_cwd(self):
        self.assertEqual(Path(launcher._bundled_project_dir()), ROOT)
        self.assertEqual(Path(launcher.resolve_project_dir(
            environ={'WINUX_INSTALL_MODE': 'legacy'})), ROOT)
        self.assertEqual(Path(launcher._runner_path()), ROOT / 'run_winux.py')
        self.assertEqual(Path(launcher.build_abaqus_command()[-1]), ROOT / 'run_winux.py')

    def test_normal_launch_builds_correct_child_from_an_unrelated_cwd(self):
        captured = {}

        class Child:
            pid = 123456
            def poll(self):
                return 0

        def spawn(command, **kwargs):
            captured.update(kwargs)
            captured['command'] = command
            return Child()

        with patch.dict(os.environ, {'WINUX_PREFER_BUNDLED_RUNTIME': '1'}), \
                patch.object(launcher, '_log_path', return_value=str(
                    Path(self.temporary.name) / 'launch.log')), \
                patch.object(launcher, '_ACTIVE_PROCESSES', []), \
                patch.object(launcher, '_ACTIVE_PROCESS', None):
            _child, started = launcher.launch_winux(popen_factory=spawn)
        self.assertTrue(started)
        self.assertEqual(Path(captured['env']['WINUX_APP_DIR']), ROOT)
        self.assertEqual(Path(captured['env']['PYTHONPATH'].split(os.pathsep)[0]), ROOT)
        self.assertIn(str(ROOT / 'run_winux.py'), captured['command'][-1])

    def test_equal_legacy_bootstrap_does_not_shadow_packaged_runtime(self):
        # Load only the Python-2-compatible selector helpers, not FOX/CAE UI.
        tree = ast.parse((ROOT / 'WinUx_plugin.py').read_text(encoding='utf-8'))
        names = {'_read_bundled_version', '_package_revision', '_release_key',
                 '_prefer_bundled_hotfix', '_activate_self_updated_bootstrap'}
        code = ast.Module(body=[node for node in tree.body
                               if isinstance(node, ast.FunctionDef) and node.name in names],
                          type_ignores=[])
        namespace = dict(os=os, sys=sys, json=json, tempfile=tempfile,
                         __file__=str(ROOT / 'WinUx_plugin.py'))
        exec(compile(code, 'WinUx_plugin.py', 'exec'), namespace)
        version = (ROOT / 'VERSION').read_text().strip()
        revision = json.loads((ROOT / 'update_manifest.json').read_text())['package_revision']
        base = Path(self.temporary.name)
        active = base / 'WinUx' / 'bootstrap' / 'versions' / version
        active.mkdir(parents=True)
        for name in ('winux_launcher.py', 'winux_updater.py', 'run_winux.py'):
            (active / name).write_text('# legacy bootstrap')
        (active / 'VERSION').write_text(version)
        (active / 'update_manifest.json').write_text(json.dumps({'version': version, 'package_revision': revision}))
        state = base / 'WinUx' / 'bootstrap' / 'state'
        state.mkdir()
        (state / 'current.json').write_text(json.dumps({'active_version': version}))
        with patch.dict(os.environ, {'LOCALAPPDATA': str(base)}, clear=True):
            self.assertIsNone(namespace['_activate_self_updated_bootstrap']())
            self.assertEqual(os.environ['WINUX_BOOTSTRAP_MODE'], 'bundled')
            self.assertEqual(os.environ['WINUX_PREFER_BUNDLED_RUNTIME'], '1')
        (active / 'update_manifest.json').write_text(json.dumps({'version': version, 'package_revision': revision + 1}))
        self.assertFalse(namespace['_prefer_bundled_hotfix'](version, str(active)))
        (active / 'update_manifest.json').write_text(json.dumps({'version': version, 'package_revision': revision}))
        (active / 'winux_runtime').mkdir()
        (active / 'winux_runtime' / 'launcher.py').write_text('# packaged bootstrap')
        self.assertFalse(namespace['_prefer_bundled_hotfix'](version, str(active)))

    def test_runner_honors_bundled_selection_without_touching_cached_state(self):
        with patch.dict(os.environ, {
                'WINUX_APP_DIR': str(ROOT), 'WINUX_PREFER_BUNDLED_RUNTIME': '1',
                'WINUX_SKIP_UPDATE': '0', 'WINUX_HEALTH_CHECK': '0'}), \
                patch('winux_runtime.installation_state.resolve_active_installation') as resolve:
            self.assertEqual(Path(run_winux._project_dir()), ROOT)
            resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
