"""Reference arithmetic/regex compatibility: abaqus python tests/test_reference_formula_operators.py."""
import copy
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.services.reference_charts import (
    evaluate_reference_formula, make_formula_reference,
    resolve_reference_formula_ids, validate_reference_formula,
)
from WinUx.dialogs.reference_chart_form import FORMULA_FUNCTIONS, ReferenceChartDialog


class FormulaOperatorTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            {'id': 'u', 'displayName': 'U3', 'points': [[0, 1], [1, 2], [2, 3]]},
            {'id': 'rf', 'displayName': 'RF3', 'points': [[0, 10], [1, 20], [2, 0]]},
        ]

    def points(self, formula, history=None):
        self.assertTrue(validate_reference_formula(formula))
        return evaluate_reference_formula(formula, self.history if history is None else history)[0]['points']

    def test_requested_signed_combine(self):
        self.assertEqual(self.points('combine(+.*U3.*, -.*RF3.*)'), [[1, -10], [2, -20], [3, 0]])

    def test_unary_signs_nested_functions_and_groups(self):
        self.assertEqual(self.points('combine(-abs(-.*U3.*), +negate(.*RF3.*))'),
                         [[-1, -10], [-2, -20], [-3, 0]])
        self.assertEqual(self.points('-(.*U3.* + 1)'), [[0, -2], [1, -3], [2, -4]])

    def test_scalar_arithmetic_precedence_and_grouping(self):
        self.assertEqual(self.points('.*U3.* + 2 * 3'), [[0, 7], [1, 8], [2, 9]])
        self.assertEqual(self.points('(.*U3.* + 2) * 3'), [[0, 9], [1, 12], [2, 15]])
        self.assertEqual(self.points('10 - 2 - .*U3.*'), [[0, 7], [1, 6], [2, 5]])
        self.assertEqual(self.points('-2 * .*U3.* + 1'), [[0, -1], [1, -3], [2, -5]])

    def test_curve_arithmetic_and_zero_division_policy(self):
        self.assertEqual(self.points('.*RF3.* + .*U3.*'), [[0, 11], [1, 22], [2, 3]])
        self.assertEqual(self.points('.*RF3.* - .*U3.*'), [[0, 9], [1, 18], [2, -3]])
        self.assertEqual(self.points('.*RF3.* * .*U3.*'), [[0, 10], [1, 40], [2, 0]])
        self.assertEqual(self.points('.*U3.* / .*RF3.*'), [[0, .1], [1, .1]])

    def test_remainder_and_percentage_are_distinct(self):
        self.assertEqual(self.points('.*RF3.* % 7'), [[0, 3], [1, 6], [2, 0]])
        self.assertEqual(self.points('50% * .*RF3.*'), [[0, 5], [1, 10], [2, 0]])

    def test_scientific_numeric_expressions(self):
        self.assertEqual(self.points('scale(.*U3.*, 1e-3*2)'), [[0, .002], [1, .004], [2, .006]])
        self.assertEqual(self.points('scale(.*U3.*, 50%*2)'), [[0, 1], [1, 2], [2, 3]])

    def test_binary_operators_inside_combine(self):
        self.assertEqual(self.points('combine(.*U3.* * 2, -.*RF3.* / 1000)'),
                         [[2, -.01], [4, -.02], [6, 0]])

    def test_legacy_function_results_are_unchanged(self):
        expected = {
            'combine(.*U3.*, .*RF3.*)': [[1, 10], [2, 20], [3, 0]],
            'add(.*U3.*, .*RF3.*)': [[0, 11], [1, 22], [2, 3]],
            'subtract(.*RF3.*, .*U3.*)': [[0, 9], [1, 18], [2, -3]],
            'multiply(.*U3.*, .*RF3.*)': [[0, 10], [1, 40], [2, 0]],
            'divide(.*U3.*, .*RF3.*)': [[0, .1], [1, .1]],
            'average(.*U3.*, .*RF3.*)': [[0, 5.5], [1, 11], [2, 1.5]],
            'magnitude(.*U3.*, .*RF3.*)': [[0, math.sqrt(101)], [1, math.sqrt(404)], [2, 3]],
            'sqrt(square(.*U3.*))': [[0, 1], [1, 2], [2, 3]],
            'offset(scale(.*U3.*, 2), -1)': [[0, 1], [1, 3], [2, 5]],
        }
        for formula, points in expected.items():
            with self.subTest(formula=formula):
                self.assertEqual(self.points(formula), points)

    def test_regex_quantifiers_groups_and_character_classes_are_preserved(self):
        self.assertEqual(self.points('combine(+(?:U[1-3]), -(?:RF[1-3]))'),
                         [[1, -10], [2, -20], [3, 0]])
        history = [dict(self.history[0], displayName='AAU3'), self.history[1]]
        self.assertEqual(self.points('combine(A+U3, RF3)', history), [[1, 10], [2, 20], [3, 0]])
        self.assertEqual(self.points('combine(A{1,3}U3, RF3)', history), [[1, 10], [2, 20], [3, 0]])
        history[0]['displayName'] = 'A,U3'
        self.assertEqual(self.points('combine(A[,]U3, RF3)', history), [[1, 10], [2, 20], [3, 0]])

    def test_quoted_and_slash_delimited_selectors(self):
        self.assertEqual(self.points('combine(+/U3/, -"RF3")'), [[1, -10], [2, -20], [3, 0]])
        self.assertEqual(self.points('"U3" + "RF3"'), [[0, 11], [1, 22], [2, 3]])
        self.assertEqual(self.points('/U3/ / 2'), [[0, .5], [1, 1], [2, 1.5]])
        history = [dict(self.history[0], displayName='+U3'), self.history[1]]
        self.assertEqual(self.points(r'combine("\+U3", RF3)', history), [[1, 10], [2, 20], [3, 0]])
        history[0]['displayName'] = 'Node/U3'
        self.assertEqual(self.points('combine(/Node[/]U3/, RF3)', history), [[1, 10], [2, 20], [3, 0]])

    def test_catalog_resolution_descends_through_arithmetic_and_signs(self):
        self.assertEqual(resolve_reference_formula_ids(
            'combine(+.*U3.* * 2, -.*RF3.* / 1000)', self.history), ['u', 'rf'])

    def test_rules_persist_without_live_points_and_evaluation_does_not_mutate_sources(self):
        before = copy.deepcopy(self.history)
        formula = 'combine(+.*U3.*, -.*RF3.*)'
        saved = make_formula_reference(formula, 'Signed curve')
        self.assertEqual(saved['formula'], formula)
        self.assertEqual(saved['points'], [])
        self.points(saved['formula'])
        self.assertEqual(self.history, before)

    def test_invalid_input_and_empty_output_fail_cleanly(self):
        for formula in ('combine(U3,)', 'combine(U3, RF3', 'unknown(U3)', 'combine("U3, RF3)'):
            with self.subTest(formula=formula), self.assertRaises(ValueError):
                validate_reference_formula(formula)
        for formula in ('U3 / 0', 'U3 % 0', '1 / 0', '2 + 3'):
            with self.subTest(formula=formula), self.assertRaises(ValueError):
                evaluate_reference_formula(formula, self.history)

    def test_palette_offers_requested_example_and_operators(self):
        syntaxes = [syntax for _, syntax, _ in FORMULA_FUNCTIONS]
        names = {name for name, _, _ in FORMULA_FUNCTIONS}
        self.assertTrue({'combine', 'regex', 'abs', 'sqrt', 'sin', 'cos', 'tan',
                         'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh', 'exp',
                         'log', 'log10', 'average', 'magnitude'}.issubset(names))
        self.assertIn('combine(regex(".*U3.*"), -regex(".*RF3.*"))', syntaxes)
        for operator in '+-*/%':
            self.assertTrue(any(operator in syntax for syntax in syntaxes))
        dialog = SimpleNamespace(
            formula_edit=123, control_value=lambda *args: 'combine(.*U1, .*RF1)',
            set_control_value=Mock(), _mark_dirty=Mock(),
            _set_formula_palette_help=Mock(),
            view=SimpleNamespace(after=Mock()), focus_control=Mock())
        example = next(item for item in FORMULA_FUNCTIONS if item[0] == 'signed_combine')
        ReferenceChartDialog._formula_function_double_clicked(dialog, user_data=example)
        dialog.set_control_value.assert_called_once_with(123, 'combine(.*U1, .*RF1)combine(')
        dialog._mark_dirty.assert_called_once()
        dialog.control_value = lambda *args: 'combine(.*U3.*, .*RF3.*)'
        dialog.set_control_value.reset_mock()
        ReferenceChartDialog._formula_function_double_clicked(dialog, user_data=example)
        dialog.set_control_value.assert_called_once_with(123, 'combine(.*U3.*, .*RF3.*)combine(')

    def test_palette_inserts_complete_example_when_empty_then_appends_fragments(self):
        fragments = dict((name, expected) for name, expected in (
            ('regex', 'regex("pattern")'), ('combine', 'combine('),
            ('sqrt', 'sqrt('), ('cos', 'cos('), ('plus', ' + '),
            ('minus', ' - '), ('times', ' * '), ('quotient', ' / '),
            ('power', ' ** '), ('remainder', ' % ')))
        for name in fragments:
            entry = next(item for item in FORMULA_FUNCTIONS if item[0] == name)
            syntax = entry[1]
            dialog = SimpleNamespace(
                formula_edit=123, control_value=lambda *args: '',
                set_control_value=Mock(), _mark_dirty=Mock(),
                _set_formula_palette_help=Mock(),
                view=SimpleNamespace(after=Mock()), focus_control=Mock())
            ReferenceChartDialog._formula_function_double_clicked(dialog, user_data=entry)
            dialog.set_control_value.assert_called_once_with(123, syntax)
            dialog._mark_dirty.assert_called_once()

            for current in ('regex("custom")', 'combine(regex("U3"),\n'):
                dialog = SimpleNamespace(
                    formula_edit=123, control_value=lambda *args, _current=current: _current,
                    set_control_value=Mock(), _mark_dirty=Mock(),
                    _set_formula_palette_help=Mock(),
                    view=SimpleNamespace(after=Mock()), focus_control=Mock())
                ReferenceChartDialog._formula_function_double_clicked(dialog, user_data=entry)
                dialog.set_control_value.assert_called_once_with(123, current + fragments[name])
                dialog._mark_dirty.assert_called_once()

    def test_palette_double_click_inserts_selected_row_once(self):
        a = SimpleNamespace(data=lambda role: ('sqrt', 'sqrt(regex(".*U3.*"))', 'Square root.'))
        dialog = SimpleNamespace(
            _finished=False, _formula_function_double_clicked=Mock(),
            _set_formula_palette_help=Mock())
        ReferenceChartDialog._formula_palette_double_clicked(dialog, a)
        dialog._set_formula_palette_help.assert_called_once_with(
            ('sqrt', 'sqrt(regex(".*U3.*"))', 'Square root.'))
        dialog._formula_function_double_clicked.assert_called_once_with(
            user_data=('sqrt', 'sqrt(regex(".*U3.*"))', 'Square root.'))

        dialog._finished = True
        ReferenceChartDialog._formula_palette_double_clicked(dialog, a)
        self.assertEqual(dialog._formula_function_double_clicked.call_count, 1)


    def test_validate_formula_reports_valid_and_invalid_syntax(self):
        controls = {'formula': 'combine(regex(".*U3.*"), -regex(".*RF3.*"))'}
        dialog = SimpleNamespace(
            formula_edit='formula', status='status',
            control_value=lambda control, default=None: controls.get(control, default),
            set_control_value=Mock(), view=SimpleNamespace(after=Mock()),
            focus_control=Mock())
        self.assertTrue(ReferenceChartDialog._validate_formula(dialog))
        dialog.set_control_value.assert_called_with(
            'status', 'Formula syntax is valid. Click Save to keep this rule.')

        controls['formula'] = 'combine(regex("U3"),'
        dialog.set_control_value.reset_mock()
        self.assertFalse(ReferenceChartDialog._validate_formula(dialog))
        message = dialog.set_control_value.call_args.args[1]
        self.assertTrue(message.startswith('Formula error: '), message)

    def test_ur_rf_generate_allows_blank_dirty_formula_and_falls_back_to_template(self):
        # Active Plot has only raw U1/RF1 while the helper requests
        # ANTIALIASING.  Generate must still produce a visible reusable formula
        # and must not try to save/validate the blank draft first.
        controls = {
            'direction': 'U1 / RF1', 'aa': True,
            'reverse_u': False, 'reverse_rf': True, 'formula': '',
        }
        added = []
        dialog = SimpleNamespace(
            generate_direction='direction', generate_antialiasing='aa',
            generate_reverse_u='reverse_u', generate_reverse_rf='reverse_rf',
            formula_edit='formula', status='status', _formula_mode=True,
            _editor_dirty=True, _history_outputs=[
                {'id': 'u1', 'step': 'Load', 'historyRegion': 'Node RP', 'output': 'U1'},
                {'id': 'rf1', 'step': 'Load', 'historyRegion': 'Node RP', 'output': 'RF1'},
            ], _series=[],
            control_value=lambda control, default=None: controls.get(control, default),
            set_control_value=Mock(),
            _save_formula_rule=Mock(return_value=False),
            _commit_editor=Mock(return_value=False),
            _add_formula_series=lambda rules: added.extend(rules) or True,
            _refresh_list=Mock(), _load_item=Mock(),
        )
        self.assertTrue(ReferenceChartDialog._generate_ur_rf(dialog))
        dialog._save_formula_rule.assert_not_called()
        self.assertEqual(len(added), 1)
        self.assertIn('U1_ANTIALIASING', added[0]['formula'])
        self.assertIn('RF1_ANTIALIASING', added[0]['formula'])
        self.assertIn('-regex(', added[0]['formula'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
