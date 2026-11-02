"""Plot Digitizer workspace compatibility: abaqus python tests/test_digitizer_workspace_state.py."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.plotdigitizer.application.workspace_state import normalize_workspace_state


class WorkspacePanelCompatibilityTests(unittest.TestCase):
    def test_calibration_method_round_trip_and_legacy_default(self):
        for method in ('manual', 'smart'):
            state = normalize_workspace_state({'version': 1, 'calibration_method': method})
            self.assertEqual(method, state['calibration_method'])
            self.assertEqual(state, normalize_workspace_state(state))
        self.assertEqual('smart', normalize_workspace_state({'version': 1})['calibration_method'])
        with self.assertRaises(ValueError):
            normalize_workspace_state({'version': 1, 'calibration_method': 'unknown'})

    def test_legacy_point_modes_become_unified_edit(self):
        for mode in ('manual', 'delete'):
            state = {'version': 1, 'pick_mode': mode, 'edit_enabled': False}
            result = normalize_workspace_state(state)
            self.assertIsNone(result['pick_mode'])
            self.assertTrue(result['edit_enabled'])
            self.assertEqual(state['pick_mode'], mode)

    def test_legacy_extraction_pages_restore_to_combined_page(self):
        for tool in ('manual', 'automatic', 'extract'):
            self.assertEqual(normalize_workspace_state({'version': 1, 'tool': tool})['tool'], 'extract')

    def test_legacy_reduction_panel_is_preserved(self):
        state = {'version': 1, 'disclosures': {'axes': False, 'advanced': True, 'reduction': True}}
        original = copy.deepcopy(state)
        normalized = normalize_workspace_state(state)
        self.assertEqual(normalized['disclosures'], state['disclosures'])
        self.assertEqual(state, original)
        self.assertEqual(normalize_workspace_state(normalized), normalized)

    def test_new_options_alias_is_migrated_without_mutating_input(self):
        state = {'version': 1, 'disclosures': {'data_options': True}}
        self.assertEqual(normalize_workspace_state(state)['disclosures'], {'reduction': True})
        self.assertEqual(state['disclosures'], {'data_options': True})

    def test_original_project_key_wins_when_both_are_present(self):
        state = {'version': 1, 'disclosures': {'data_options': True, 'reduction': False}}
        self.assertEqual(normalize_workspace_state(state)['disclosures'], {'reduction': False})

    def test_legacy_calibration_sequence_is_not_resumed(self):
        state = {'version': 1, 'calibration_sequence': ['x1', 'x2', 'y1', 'y2']}
        normalized = normalize_workspace_state(state)
        self.assertEqual(normalized['calibration_sequence'], [])
        self.assertEqual(state['calibration_sequence'], ['x1', 'x2', 'y1', 'y2'])

    def test_unknown_keys_and_invalid_panel_states_still_fail_validation(self):
        for disclosures in ([], {'unrecognized': True}, {'data_options': 'yes'}, {'reduction': 1}):
            with self.subTest(disclosures=disclosures), self.assertRaises(ValueError):
                normalize_workspace_state({'version': 1, 'disclosures': disclosures})


if __name__ == '__main__':
    unittest.main(verbosity=2)
