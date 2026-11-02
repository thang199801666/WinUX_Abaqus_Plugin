"""Explicit regex selectors and whitelisted Python/Abaqus-style arithmetic."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.services.reference_charts import (
    evaluate_reference_formula, validate_reference_formula, make_formula_reference,
    resolve_reference_formula_ids, normalize_reference_formula, generate_reference_ur_rf,
)


class ExplicitRegexFormulaTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            {'id': 'u', 'name': 'U3', 'points': [[0, 1], [1, 2], [2, 3]]},
            {'id': 'rf', 'name': 'RF3', 'points': [[0, 10], [1, 20], [2, 30]]},
        ]

    def points(self, expression, history=None):
        self.assertTrue(validate_reference_formula(expression, explicit_regex=True))
        return evaluate_reference_formula(expression, self.history if history is None else history)[0]['points']

    def test_signed_combine_and_standalone_selector(self):
        self.assertEqual(self.points('combine(regex(".*U3.*"),-regex(".*RF3.*"))'),
                         [[1, -10], [2, -20], [3, -30]])
        self.assertEqual(self.points('regex("U3")'), self.history[0]['points'])

    def test_ordinary_precedence_without_operator_spacing(self):
        self.assertEqual(self.points('regex("U3")+2*3'), [[0, 7], [1, 8], [2, 9]])
        self.assertEqual(self.points('(regex("U3")+2)*3'), [[0, 9], [1, 12], [2, 15]])
        self.assertEqual(self.points('10-2-regex("U3")'), [[0, 7], [1, 6], [2, 5]])
        self.assertEqual(self.points('2*regex("U3")/1e3'), [[0, .002], [1, .004], [2, .006]])

    def test_power_precedence_right_associativity_and_aliases(self):
        self.assertEqual(self.points('-regex("U3")**2'), [[0, -1], [1, -4], [2, -9]])
        self.assertEqual(self.points('(-regex("U3"))**2'), [[0, 1], [1, 4], [2, 9]])
        self.assertEqual(self.points('regex("U3")*2**3**2'), [[0, 512], [1, 1024], [2, 1536]])
        self.assertEqual(self.points('regex("U3")**-2'), [[0, 1], [1, .25], [2, 1 / 9]])
        self.assertEqual(self.points('power(regex("U3"),2)'), self.points('pow(regex("U3"),2)'))

    def test_regex_operators_and_commas_remain_inside_string(self):
        history = [dict(self.history[0], name='AA(U3),x'), self.history[1]]
        expr = r'combine(regex(r"A{1,3}\(U[1-3]\),x"),-regex("RF3"))'
        self.assertEqual(self.points(expr, history), [[1, -10], [2, -20], [3, -30]])

    def test_raw_strings_and_escaped_backslashes(self):
        self.assertEqual(self.points(r'regex(r"\bU3\b")'), self.history[0]['points'])
        self.assertEqual(self.points(r'regex("\\bU3\\b")'), self.history[0]['points'])
        with self.assertRaisesRegex(ValueError, 'raw string'):
            validate_reference_formula('regex("\\bU3\\b")', explicit_regex=True)

    def test_anchors_match_individual_names_and_catalog_ids(self):
        self.assertEqual(self.points('regex("^U3$")'), self.history[0]['points'])
        self.assertEqual(resolve_reference_formula_ids('regex("^U3$")', self.history), ['u'])
        self.assertEqual(resolve_reference_formula_ids('regex("^rf$")', self.history), ['rf'])

    def test_scalar_math_functions_and_constants(self):
        self.assertEqual(self.points('regex("U3")+sqrt(4)'), [[0, 3], [1, 4], [2, 5]])
        points = self.points('regex("U3")+sin(pi/2)+log(e)')
        self.assertEqual(points, [[0, 3], [1, 4], [2, 5]])

    def test_curve_math_functions(self):
        for name, function in (('sin', math.sin), ('cos', math.cos), ('tan', math.tan),
                               ('atan', math.atan), ('sinh', math.sinh), ('cosh', math.cosh),
                               ('tanh', math.tanh), ('log', math.log), ('ln', math.log),
                               ('log10', math.log10), ('exp', math.exp), ('sqrt', math.sqrt)):
            with self.subTest(function=name):
                self.assertEqual(self.points(name + '(regex("U3"))'),
                                 [[x, function(y)] for x, y in self.history[0]['points']])

    def test_percent_is_remainder_and_scaling_uses_decimal(self):
        self.assertEqual(self.points('regex("RF3")%7'), [[0, 3], [1, 6], [2, 2]])
        self.assertEqual(self.points('0.5*regex("RF3")'), [[0, 5], [1, 10], [2, 15]])
        with self.assertRaises(ValueError):
            validate_reference_formula('50%*regex("RF3")', explicit_regex=True)

    def test_math_domain_errors_are_reported_not_silently_skipped(self):
        for expression in ('regex("U3")/0', 'regex("U3")%0', 'sqrt(-regex("U3"))',
                           'log(-regex("U3"))', '(-regex("U3"))**0.5', 'regex("U3")*1e308'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.points(expression)

    def test_new_editor_requires_explicit_selectors_and_valid_arity(self):
        for expression in ('combine(U3,RF3)', '"U3"+1', '.*U3.*+1', 'regex(U3)',
                           'regex("a","b")', 'regex()', 'regex("[")', 'sin(regex("U3"),2)',
                           'combine(regex("U3"))', 'scale(regex("U3"),2,3)', '2+3'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                make_formula_reference(expression, explicit_regex=True)

    def test_python_execution_and_unsupported_ast_are_rejected(self):
        for expression in ('__import__("os")', 'regex("U3").__class__', 'regex("U3")[0]',
                           '[regex("U3")]', '(lambda: regex("U3"))()',
                           'regex("U3") if True else 0', 'open("file")+regex("U3")',
                           'regex(pattern="U3")', 'regex("U3")//2', 'regex("U3")^2'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                validate_reference_formula(expression, explicit_regex=True)

    def test_old_rules_still_evaluate_and_normalize_on_demand(self):
        for expression in ('combine(+.*U3.*, -.*RF3.*)', '.*U3.* + 2 * 3',
                           '50% * .*RF3.*', 'sqrt(square(.*U3.*))'):
            normalized = normalize_reference_formula(expression)
            self.assertIn('regex(', normalized)
            self.assertEqual(evaluate_reference_formula(expression, self.history)[0]['points'],
                             evaluate_reference_formula(normalized, self.history)[0]['points'])
        expression = 'regex("U3")/1000'
        self.assertEqual(normalize_reference_formula(expression), expression)

    def test_generators_emit_explicit_regex_and_resolve_without_points(self):
        rules = generate_reference_ur_rf(directions=(3,), antialiasing=False)
        self.assertIn('regex(', rules[0]['formula'])
        self.assertNotIn('combine(+/', rules[0]['formula'])
        self.assertEqual(resolve_reference_formula_ids(rules[0]['formula'], self.history), ['u', 'rf'])
        self.assertEqual(evaluate_reference_formula(rules[0]['formula'], self.history)[0]['points'],
                         [[1, -10], [2, -20], [3, -30]])

    def test_saving_does_not_evaluate_or_mutate_live_history(self):
        before = copy.deepcopy(self.history)
        rule = make_formula_reference('regex("^U3$")**2', 'Squared', explicit_regex=True)
        self.assertEqual(rule['points'], [])
        self.assertEqual(rule['formula'], 'regex("^U3$")**2')
        evaluate_reference_formula(rule['formula'], self.history)
        self.assertEqual(before, self.history)

    def test_legacy_and_new_generator_syntax_have_same_dedup_key(self):
        legacy = r'combine(+.*\bU3_ANTIALIASING\b.*, -.*\bRF3_ANTIALIASING\b.*)'
        generated = generate_reference_ur_rf(directions=(3,))[0]['formula']
        self.assertEqual(normalize_reference_formula(legacy, canonical=True),
                         normalize_reference_formula(generated, canonical=True))
        legacy_slash = r'combine(+/Node\/U3/, -/Node\/RF3/)'
        modern = 'combine(regex("Node/U3"), -regex("Node/RF3"))'
        self.assertEqual(normalize_reference_formula(legacy_slash, canonical=True),
                         normalize_reference_formula(modern, canonical=True))

    def test_regex_escaped_quotes_and_literal_backslashes(self):
        history = [dict(self.history[0], name='U"3'), self.history[1]]
        self.assertEqual(self.points(r'regex("U\"3")', history), self.history[0]['points'])
        history[0]['name'] = r'U\3'
        self.assertEqual(self.points(r'regex(r"U\\3")', history), self.history[0]['points'])

    def test_formula_limits_and_nonfinite_constants_fail_cleanly(self):
        for expression in ('regex("U3")+1e309', 'regex("' + 'a' * 17000 + '")',
                           'regex("U3")' + '+1' * 300, 'regex("U3")' + '+1' * 70):
            with self.subTest(length=len(expression)), self.assertRaises(ValueError):
                validate_reference_formula(expression, explicit_regex=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
