import unittest

from WinUx.services.reference_charts import (
    evaluate_reference_formula, make_formula_reference,
    resolve_reference_formula_ids)


class ReferenceFormulaTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"id": "u1", "displayName": "Antialising Node U1", "output": "U1",
             "historyRegion": "Node 1", "points": [[0, 0], [1, 2], [2, 4]]},
            {"id": "rf1", "displayName": "Antialising Node RF1", "output": "RF1",
             "historyRegion": "Node 1", "points": [[0, 10], [1, 20], [2, 30]]},
            {"id": "u2", "displayName": "Antialising Node U2", "output": "U2",
             "historyRegion": "Node 1", "points": [[0, 1], [1, 3], [2, 5]]},
        ]


    def test_formula_rule_can_be_created_without_active_history(self):
        item = make_formula_reference(
            r"combine(.*Antialising.*U1, .*Antialising.*RF1)")
        self.assertEqual(item["kind"], "formula")
        self.assertEqual(item["points"], [])
        self.assertIn("combine(", item["formula"])

    def test_formula_regex_resolves_exact_catalog_ids_without_live_points(self):
        catalog = [
            {k: v for k, v in row.items() if k != "points"}
            for row in self.history
        ]
        ids = resolve_reference_formula_ids(
            r"combine(.*Antialising.*U1, .*Antialising.*RF1)", catalog)
        self.assertEqual(ids, ["u1", "rf1"])

    def test_combine_uses_first_value_as_x_and_second_as_y(self):
        result = evaluate_reference_formula(
            r"combine(.*Antialising.*U1, .*Antialising.*RF1)", self.history)
        self.assertEqual(result[0]["points"], [[0, 10], [2, 20], [4, 30]])

    def test_math_functions_keep_time_axis(self):
        result = evaluate_reference_formula(r"add(.*U1, .*U2)", self.history)
        self.assertEqual(result[0]["points"], [[0, 1], [1, 5], [2, 9]])
        result = evaluate_reference_formula(r"magnitude(.*U1, .*U2)", self.history)
        self.assertAlmostEqual(result[0]["points"][1][1], (13) ** 0.5)

    def test_nested_and_scalar_functions(self):
        result = evaluate_reference_formula(r"abs(negate(.*U1))", self.history)
        self.assertEqual(result[0]["points"], [[0, 0], [1, 2], [2, 4]])
        result = evaluate_reference_formula(r"scale(.*U1, 2)", self.history)
        self.assertEqual(result[0]["points"], [[0, 0], [1, 4], [2, 8]])

    def test_regex_must_match_current_plot_and_have_data(self):
        with self.assertRaises(ValueError):
            evaluate_reference_formula(r"combine(.*DOES_NOT_EXIST, .*RF1)", self.history)
        empty = list(self.history) + [{"id": "a", "displayName": "EMPTY", "points": []}]
        with self.assertRaises(ValueError):
            evaluate_reference_formula(r"abs(EMPTY)", empty)


if __name__ == "__main__":
    unittest.main()
