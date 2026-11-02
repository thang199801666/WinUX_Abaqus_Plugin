"""U/RF formula presets: abaqus python tests/test_reference_ur_rf_generator.py."""
import copy
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.services.reference_charts import (
    generate_reference_ur_rf, evaluate_reference_formula, resolve_reference_formula_ids,
    ReferenceChartLibrary,
)


def catalog(step='Step-1', region='Node ASSEMBLY.1', axes=(1, 2, 3), suffix='_ANTIALIASING'):
    rows = []
    for axis in axes:
        for kind, factor in (('U', 1), ('RF', 10)):
            variable = '{}{}{}'.format(kind, axis, suffix)
            rows.append({
                'id': '{}:{}:{}'.format(step, region, variable), 'step': step,
                'historyRegion': region, 'output': variable,
                'displayName': '{} (FILTERED): {} PI: {}'.format(
                    'Spatial displacement' if kind == 'U' else 'Reaction force', variable, region),
                'points': [[0, axis * factor], [1, (axis + 1) * factor]],
            })
    return rows


class GeneratorTests(unittest.TestCase):
    def test_generated_regex_rules_survive_profile_storage_roundtrip(self):
        rows = catalog(axes=(3,))
        rules = generate_reference_ur_rf(rows)
        temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(prefix='winux-formula-preset-', dir=temp_root) as profile:
            ReferenceChartLibrary(root=profile).replace(rules)
            loaded = ReferenceChartLibrary(root=profile).snapshot()
        self.assertEqual(loaded[0]['formula'], rules[0]['formula'])
        self.assertEqual(evaluate_reference_formula(loaded[0]['formula'], rows)[0]['points'], [[3, -30], [4, -40]])

    def test_plot_metadata_snapshot_does_not_read_live_samples(self):
        from WinUx.ui.components.job_plots import JobPlotsWindow

        class NoPointAccess:
            def get(self, *args):
                raise AssertionError('Metadata-only generation read live XY points')

        window = SimpleNamespace(catalog={'history': catalog(axes=(3,))[0]},
                                 _series_points=NoPointAccess())
        rows = JobPlotsWindow.reference_formula_sources(window, include_points=False)
        self.assertEqual(rows[0]['points'], [])
        self.assertEqual(rows[0]['output'], 'U3_ANTIALIASING')

    def test_screenshot_labels_pair_without_structured_metadata(self):
        rows = [
            {'id': 'rf', 'displayName': 'Reaction force (FILTERED): RF3_ANTIALIASING PI: rootAssembly Node 1 in NSET POINTLOAD', 'points': [[0, 30], [1, 40]]},
            {'id': 'u', 'displayName': 'Spatial displacement (FILTERED): U3_ANTIALIASING PI: rootAssembly Node 1 in NSET POINTLOAD', 'points': [[0, 3], [1, 4]]},
        ]
        rules = generate_reference_ur_rf(rows, directions=(3,))
        self.assertEqual(len(rules), 1)
        self.assertIn('U3_ANTIALIASING', rules[0]['formula'])
        self.assertIn('RF3_ANTIALIASING', rules[0]['formula'])
        self.assertEqual(set(resolve_reference_formula_ids(rules[0]['formula'], rows)), {'u', 'rf'})
        self.assertEqual(evaluate_reference_formula(rules[0]['formula'], rows)[0]['points'], [[3, -30], [4, -40]])

    def test_all_directions_are_scoped_per_step_and_node(self):
        rows = []
        for step in ('Step-1', 'Step-2'):
            for region in ('Node ASSEMBLY.1', 'Node ASSEMBLY.2'):
                rows.extend(catalog(step, region))
                rows.extend(catalog(step, region, suffix=''))
        before = copy.deepcopy(rows)
        rules = generate_reference_ur_rf(list(reversed(rows)))
        self.assertEqual(len(rules), 12)
        for rule in rules:
            ids = resolve_reference_formula_ids(rule['formula'], rows)
            self.assertEqual(len(ids), 2, rule['formula'])
            selected = [row for row in rows if row['id'] in ids]
            self.assertEqual(len({row['step'] for row in selected}), 1)
            self.assertEqual(len({row['historyRegion'] for row in selected}), 1)
            self.assertTrue(all(row['output'].endswith('_ANTIALIASING') for row in selected))
            u = next(row for row in selected if row['output'].startswith('U'))
            rf = next(row for row in selected if row['output'].startswith('RF'))
            self.assertEqual(u['output'][1:], rf['output'][2:])
            self.assertEqual(evaluate_reference_formula(rule['formula'], rows)[0]['points'],
                             [[p[1], -q[1]] for p, q in zip(u['points'], rf['points'])])
        self.assertEqual(rows, before)
        self.assertEqual([rule['formula'] for rule in rules],
                         [rule['formula'] for rule in generate_reference_ur_rf(rows)])

    def test_raw_and_sign_options(self):
        rows = catalog(axes=(3,)) + catalog(axes=(3,), suffix='')
        rule = generate_reference_ur_rf(rows, directions=(3,), antialiasing=False,
                                        reverse_u=True, reverse_rf=False)[0]
        ids = resolve_reference_formula_ids(rule['formula'], rows)
        self.assertEqual(len(ids), 2)
        self.assertTrue(all('_ANTIALIASING' not in item for item in ids))
        self.assertEqual(evaluate_reference_formula(rule['formula'], rows)[0]['points'], [[-3, 30], [-4, 40]])

    def test_missing_pair_never_crosses_regions_or_steps(self):
        one = catalog(axes=(3,))
        two = catalog(region='Node ASSEMBLY.2', axes=(3,))
        with self.assertRaises(ValueError):
            generate_reference_ur_rf([one[0], two[1]], directions=(3,))
        two = catalog(step='Step-2', axes=(3,))
        with self.assertRaises(ValueError):
            generate_reference_ur_rf([one[0], two[1]], directions=(3,))

    def test_missing_direction_is_skipped_not_broadcast(self):
        rows = catalog(axes=(3,)) + catalog(axes=(1,))[:1]
        self.assertEqual(len(generate_reference_ur_rf(rows)), 1)

    def test_mixed_filter_and_component_numbers_do_not_pair(self):
        rows = catalog(axes=(3,))
        rows[0]['output'] = 'U30_ANTIALIASING'
        rows[0]['displayName'] = 'U30_ANTIALIASING'
        with self.assertRaises(ValueError):
            generate_reference_ur_rf(rows, directions=(3,))

        rows = catalog(axes=(3,))
        rows[0]['output'] = 'U3'
        rows[0]['displayName'] = 'U3'
        with self.assertRaises(ValueError):
            generate_reference_ur_rf(rows, directions=(3,))

    def test_unrelated_output_description_is_not_treated_as_displacement(self):
        rows = catalog(axes=(3,))
        unrelated = dict(rows[0], id='energy', output='ENER', displayName='Energy based on U3_ANTIALIASING')
        self.assertEqual(len(generate_reference_ur_rf(rows + [unrelated], directions=(3,))), 1)

    def test_ambiguous_duplicate_is_rejected_but_duplicate_catalog_id_is_deduplicated(self):
        rows = catalog(axes=(3,))
        self.assertEqual(len(generate_reference_ur_rf(rows + [dict(rows[0])])), 1)
        duplicate = dict(rows[0], id='another-history')
        with self.assertRaises(ValueError):
            generate_reference_ur_rf(rows + [duplicate])

    def test_metadata_with_regex_punctuation_is_escaped(self):
        rows = catalog(step="Load(1), 'Phase'/A", region='Node A[1].(RP)/load+', axes=(3,))
        rule = generate_reference_ur_rf(rows)[0]
        self.assertEqual(len(resolve_reference_formula_ids(rule['formula'], rows)), 2)
        self.assertEqual(evaluate_reference_formula(rule['formula'], rows)[0]['points'], [[3, -30], [4, -40]])

    def test_no_active_plot_generates_reusable_component_templates(self):
        rules = generate_reference_ur_rf()
        self.assertEqual(len(rules), 3)
        rows = catalog(axes=(3,)) + catalog(axes=(3,), suffix='')
        self.assertEqual(evaluate_reference_formula(rules[2]['formula'], rows)[0]['points'], [[3, -30], [4, -40]])
        raw = generate_reference_ur_rf(directions=(3,), antialiasing=False)[0]
        self.assertEqual(len(resolve_reference_formula_ids(raw['formula'], rows)), 2)

    def test_metadata_only_catalog_needs_no_live_samples(self):
        rows = catalog(axes=(3,))
        for row in rows:
            row['points'] = 123  # ODB catalog point count, not downloaded points.
        rule = generate_reference_ur_rf(rows)[0]
        self.assertEqual(len(resolve_reference_formula_ids(rule['formula'], rows)), 2)

    def test_invalid_directions(self):
        for axes in ((), (0,), (4,), ('bad',)):
            with self.subTest(axes=axes), self.assertRaises(ValueError):
                generate_reference_ur_rf(directions=axes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
