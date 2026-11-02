"""Validation and linked count/factor fields for the unified Samples dialog."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from WinUx.plotdigitizer.ui.samples_dialog import SamplesDialog


class SamplesDialogTests(unittest.TestCase):
    def validate(self, target='20', factor='2', error='0.5', method=SamplesDialog.COUNT, current=10):
        return SamplesDialog.validate_settings(method, current, target, factor, error)

    def test_target_count_can_increase_reduce_or_stay(self):
        for target in (5, 10, 20):
            value, error = self.validate(str(target), str(target / 10))
            self.assertEqual(value, {'mode': 'count', 'target': target})
            self.assertEqual(error, '')

    def test_invalid_counts_and_factors(self):
        for target in ('', '0', '-2', '1.5', 'nan', '1000001'):
            self.assertIsNone(self.validate(target=target)[0])
        for factor in ('', '0', '-1', 'nan', 'inf', '1e999', 'abc'):
            self.assertIsNone(self.validate(factor=factor)[0])

    def test_simplify_uses_only_finite_nonnegative_error(self):
        for error in ('0', '0.5', '2'):
            value, message = self.validate('', '', error, SamplesDialog.SIMPLIFY)
            self.assertEqual(value, {'mode': 'simplify', 'max_error': float(error)})
            self.assertEqual(message, '')
        for error in ('', '-1', 'nan', 'inf', 'abc'):
            self.assertIsNone(self.validate(error=error, method=SamplesDialog.SIMPLIFY)[0])

    def test_insufficient_points(self):
        self.assertIsNone(self.validate(current=1)[0])
        self.assertIsNone(self.validate(current=2, method=SamplesDialog.SIMPLIFY)[0])

    def test_count_and_factor_link_both_directions(self):
        target, factor = ['30'], ['1']
        state = SimpleNamespace(
            _syncing=False, current_count=10, _validate=Mock(),
            target_editor=SimpleNamespace(text=lambda: target[0], setText=lambda v: target.__setitem__(0, v)),
            factor_editor=SimpleNamespace(text=lambda: factor[0], setText=lambda v: factor.__setitem__(0, v)))
        SamplesDialog._target_changed(state)
        self.assertEqual(float(factor[0]), 3)
        factor[0] = '0.5'
        SamplesDialog._factor_changed(state)
        self.assertEqual(target[0], '5')
        self.assertFalse(state._syncing)


if __name__ == '__main__':
    unittest.main()
