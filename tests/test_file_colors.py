"""Pure filename rules and preference persistence."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.file_colors import FILE_COLORS, file_name_color
from WinUx.ui.components.explorer_list_model import ListViewItem
from WinUx.preferences.general import GeneralPreferences
from WinUx.services.file_color_rules import FileColorRules, default_color_rules, normalize_color_rules


class FileColors(unittest.TestCase):
    def rule(self, mask='*.inp;*.odb|*.bak', **values):
        return dict(name='Models', enabled=True, scope='file', color='#123456', mask=mask, **values)

    def test_custom_masks_priority_disabled_and_parent(self):
        first = self.rule()
        second = dict(first, name='Fallback', mask='*', color='#ABCDEF')
        matcher = FileColorRules([first, second])
        self.assertEqual(matcher(ListViewItem('MODEL.ODB')), (18, 52, 86, 255))
        self.assertEqual(matcher(ListViewItem('model.odb.bak')), (171, 205, 239, 255))
        self.assertIsNone(matcher(ListViewItem('model.odb', is_dir=True)))
        self.assertIsNone(matcher(ListViewItem('..', data={'parent': True})))
        self.assertEqual(FileColorRules([second, first])(ListViewItem('a.inp')), (171, 205, 239, 255))
        self.assertEqual(FileColorRules([dict(first, enabled=False), second])(ListViewItem('a.inp')),
                         (171, 205, 239, 255))
        self.assertIsNone(FileColorRules([])(ListViewItem('folder', is_dir=True)))

    def test_literal_masks_exclusion_only_and_scopes(self):
        matcher = FileColorRules([dict(self.rule('README'), scope='any')])
        self.assertIsNotNone(matcher(ListViewItem('readme')))
        self.assertIsNone(matcher(ListViewItem('README.txt')))
        matcher = FileColorRules([self.rule('|*.bak;*.tmp')])
        self.assertIsNotNone(matcher(ListViewItem('a.inp')))
        self.assertIsNone(matcher(ListViewItem('a.BAK')))
        self.assertIsNotNone(FileColorRules([dict(self.rule('*'), scope='directory')])(
            ListViewItem('folder', is_dir=True)))

    def test_validation_and_defaults_are_independent(self):
        for key, value in [('mask', ''), ('mask', '*.inp|*.bak|*.tmp'), ('mask', '../*'),
                           ('mask', '* > invalid'), ('color', '#123'), ('color', '#GGGGGG'),
                           ('name', ''), ('scope', 'unknown'), ('enabled', 'false')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                normalize_color_rules([dict(self.rule(), **{key: value})])
        rules = default_color_rules()
        rules[0]['color'] = '#FFFFFF'
        self.assertNotEqual(default_color_rules()[0]['color'], '#FFFFFF')

    def test_rule_preferences_roundtrip_empty_and_corrupt_fallback(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as profile:
            prefs = GeneralPreferences(root=profile)
            self.assertEqual(prefs.load()['file_color_rules'], default_color_rules())
            prefs.save(auto_login=True, file_color_rules=[self.rule()])
            prefs.save(auto_login=False)
            self.assertEqual(prefs.load()['file_color_rules'], [self.rule()])
            prefs.save(auto_login=False, file_color_rules=[])
            self.assertEqual(prefs.load()['file_color_rules'], [])
            prefs._store.save({'file_color_rules': [{'color': 'broken'}], 'file_colors': False})
            self.assertEqual(prefs.load()['file_color_rules'], default_color_rules())
            self.assertFalse(prefs.load()['file_colors'])

    def test_rules_and_priority(self):
        cases = [
            (ListViewItem('folder', is_dir=True), 'directory'),
            (ListViewItem('link', data={'mode': 0o120777}), 'symlink'),
            (ListViewItem('junction', is_dir=True, data={'is_symlink': True}), 'symlink'),
            (ListViewItem('run', data={'mode': 0o100750}), 'executable'),
            (ListViewItem('RUN.EXE'), 'executable'),
            (ListViewItem('archive.TAR.GZ'), 'archive'),
            (ListViewItem('image.PNG'), 'image'),
            (ListViewItem('.private', is_dir=True), 'hidden'),
            (ListViewItem('private.exe', data={'is_hidden': True}), 'hidden'),
        ]
        for row, role in cases:
            self.assertEqual(file_name_color(row), FILE_COLORS[role])
        for row in (ListViewItem('plain.inp'), ListViewItem('fake.exe', data={'mode': 0o100644}),
                    ListViewItem('..', is_dir=True, data={'parent': True})):
            self.assertIsNone(file_name_color(row))

    def test_preferences_default_save_and_preserve(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as profile:
            prefs = GeneralPreferences(root=profile)
            self.assertTrue(prefs.load()['file_colors'])
            prefs.save(auto_login=False, show_hidden_files=True, file_colors=False)
            self.assertFalse(prefs.load()['file_colors'])
            prefs.save_auto_login(True)
            self.assertFalse(prefs.load()['file_colors'])
            self.assertTrue(prefs.load()['show_hidden_files'])
            prefs.save(auto_login=True, file_colors=True)
            self.assertTrue(prefs.load()['file_colors'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
