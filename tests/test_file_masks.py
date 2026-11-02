"""Shared WinSCP-style display masks: grammar, metadata and integrations."""
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.services.file_masks import compile_file_mask
from WinUx.services.file_filter import compile_file_filter
from WinUx.services.file_color_rules import FileColorRules, normalize_color_rules
from WinUx.ui.components.explorer_list_model import ListViewItem


class FileMasks(unittest.TestCase):
    def item(self, name='model.inp', **values):
        return ListViewItem(name, **values)

    def matches(self, mask, name, **values):
        return compile_file_mask(mask)(self.item(name, **values))

    def test_wildcards_sets_and_literal_wildcards(self):
        for mask, name in [('*.INP', 'job.inp'), ('photo????.jpg', 'photo1234.jpg'),
                           ('index_[a-c].html', 'index_b.html'), ('star[*].txt', 'star*.txt'),
                           ('question[?].txt', 'question?.txt'), ('open[[]', 'open['),
                           ('[;,|].txt', ';.txt')]:
            with self.subTest(mask=mask, name=name):
                self.assertTrue(self.matches(mask, name))
        self.assertFalse(self.matches('job?.inp', 'job.inp'))

    def test_dos_exceptions(self):
        for name in ('README', '.hidden', 'file.inp', 'folder'):
            self.assertTrue(self.matches('*.*', name))
        self.assertTrue(self.matches('*.', 'README'))
        self.assertFalse(self.matches('*.', 'file.inp'))
        self.assertTrue(self.matches('*/results/*.*', 'README', path='/work/results/README'))

    def test_include_exclude_comma_semicolon_and_empty_halves(self):
        for mask in ('*.inp,*.odb|*.bak', '*.inp; *.odb|*.bak', '|*.bak', '*.inp|', ''):
            self.assertTrue(self.matches(mask, 'job.inp'))
        self.assertFalse(self.matches('*.inp;*|job*', 'job.inp'))
        self.assertFalse(self.matches('|*.bak', 'job.bak'))

    def test_doubled_separators_and_operators_are_literal(self):
        for mask, name in [('file;;semi', 'file;semi'), ('file,,comma', 'file,comma'),
                           ('file||pipe', 'file|pipe'), ('file<<less', 'file<less'),
                           ('file>>more', 'file>more'), ('a||b|*.bak', 'a|b')]:
            with self.subTest(mask=mask):
                self.assertTrue(self.matches(mask, name))
        self.assertFalse(self.matches('file,,comma', 'file'))

    def test_directory_and_path_masks(self):
        self.assertTrue(self.matches('*/', 'folder', is_dir=True))
        self.assertFalse(self.matches('*/', 'file.inp'))
        self.assertTrue(self.matches('results/', 'results', is_dir=True))
        self.assertFalse(self.matches('results/', 'results'))
        self.assertTrue(self.matches('*/results/*.odb', 'a.odb', path='/work/results/a.odb'))
        self.assertTrue(self.matches('*/results/*.odb', 'a.odb', path=r'C:\work\results\a.odb'))
        self.assertFalse(self.matches('/work/*.odb', 'a.odb', path=r'C:\work\a.odb'))
        self.assertFalse(self.matches('/work/*.odb', 'a.odb', path='/work/sub/a.odb'))
        self.assertTrue(self.matches('/work/*/*.odb', 'a.odb', path='/work/sub/a.odb'))
        self.assertTrue(self.matches('*/results/*.odb', 'a.odb', path='/very/deep/work/results/a.odb'))
        self.assertTrue(self.matches(r'C:\work\*.odb', 'a.odb', path=r'C:\work\a.odb'))
        self.assertFalse(self.matches('*/results/*.odb', 'a.odb', path=''))

    def test_size_constraints_and_boundaries(self):
        self.assertTrue(self.matches('*.odb>=1M<=2M', 'a.odb', size=1024 ** 2))
        self.assertFalse(self.matches('*.odb>1M', 'a.odb', size=1024 ** 2))
        self.assertTrue(self.matches('*.odb>1.5K', 'a.odb', size=1537))
        self.assertTrue(self.matches('<1G', 'folder', size=10 ** 12, is_dir=True))
        self.assertFalse(self.matches('>0', 'folder', size=100, is_dir=True))
        self.assertTrue(self.matches('file<<name>=1', 'file<name', size=1))

    def test_absolute_modified_dates(self):
        modified = datetime(2026, 10, 24, 12, 30).timestamp()
        self.assertTrue(self.matches('*.inp>=2026-10-24 12:30<=2026-10-24 12:30:00',
                                     'a.inp', mtime=modified))
        self.assertFalse(self.matches('>2026-10-25', 'a.inp', mtime=modified))
        # Both immutable filesystem models and UI rows can use the matcher.
        model = SimpleNamespace(name='a.inp', path='/a.inp', is_dir=False, size=1, modified=modified)
        self.assertTrue(compile_file_mask('>=2026-10-24')(model))

    def test_relative_dates_and_clock_is_not_frozen_in_cache(self):
        now = datetime(2026, 10, 24, 12).timestamp()
        row = self.item('a.log', mtime=now - 29 * 86400)
        mask = compile_file_mask('*.log<30D')
        self.assertFalse(mask(row, now=now))
        self.assertTrue(mask(row, now=now + 2 * 86400))
        for unit, seconds in [('D', 86400), ('H', 3600), ('N', 60), ('S', 1)]:
            row.mtime = now - seconds
            self.assertTrue(compile_file_mask('>=1' + unit)(row, now=now))
        self.assertFalse(mask(self.item('folder', is_dir=True), now=now))
        row.mtime = datetime(2026, 10, 24).timestamp()
        self.assertTrue(compile_file_mask('>=today')(row, now=now))
        row.mtime = datetime(2026, 10, 23).timestamp()
        self.assertTrue(compile_file_mask('>=yesterday<today')(row, now=now))

    def test_missing_nonfinite_metadata_cannot_satisfy_constraints(self):
        row = SimpleNamespace(name='a', path='', is_dir=False)
        self.assertFalse(compile_file_mask('>1M')(row))
        self.assertFalse(compile_file_mask('>2026-01-01')(row))
        self.assertFalse(self.matches('>0', 'a', size=float('nan')))
        self.assertFalse(self.matches('>0', 'a', size=float('inf')))

    def test_invalid_and_deliberately_unsupported_syntax(self):
        for mask in ('*|*.bak|*.tmp', '*\n', './*.inp', '../*', '*/../*', '>nope',
                     '>2026-02-30', '>2026-01-01 25:00', '>=', '>1TB', '>1Y', '>2DS',
                     '>' + '9' * 1000 + 'D', '>' + '9' * 1000 + 'G', '*' * 4097):
            with self.subTest(mask=mask[:80]), self.assertRaises(ValueError):
                compile_file_mask(mask)

    def test_no_filesystem_io_and_no_clock_for_static_masks(self):
        row = self.item('job.inp', size=1024)
        with patch('pathlib.Path.stat', side_effect=AssertionError('I/O in mask')), \
                patch('WinUx.services.file_masks.time.time', side_effect=AssertionError('Unneeded clock')):
            self.assertTrue(compile_file_mask('*.inp>=1K')(row))

    def test_shared_filter_and_color_semantics(self):
        mask = '*.inp,*.odb>=1K|skip*'
        rows = [self.item('a.inp', size=1), self.item('a.odb', size=1024),
                self.item('small.odb', size=10), self.item('skip.inp', size=100)]
        rules = [dict(name='Models', enabled=True, scope='any', mask=mask, color='#123456')]
        color = FileColorRules(rules)
        filtered = compile_file_filter(mask)
        for row in rows:
            self.assertEqual(bool(color(row)), filtered(row))
        self.assertTrue(compile_file_filter('text document')(
            self.item('x', item_type='Text Document')))
        self.assertTrue(compile_file_filter('/work')(
            self.item('x', path='/work/x')))
        self.assertEqual(normalize_color_rules([dict(rules[0], mask='file||pipe')])[0]['mask'], 'file||pipe')

    def test_cache_is_bounded(self):
        self.assertIs(compile_file_mask('*.inp'), compile_file_mask('*.inp'))
        for index in range(400):
            compile_file_mask('*.{}'.format(index))
        self.assertLessEqual(compile_file_mask.cache_info().currsize, 256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
