from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTabIndependenceContractTests(unittest.TestCase):
    def test_workflow_navigation_is_not_bound_to_current_changed(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py').read_text(encoding='utf-8')
        self.assertNotIn('tool_list.currentChanged.connect(self._show_tool)', source)
        self.assertIn('tool_list.userActivated.connect(self._show_tool)', source)

    def test_workflow_check_state_does_not_navigate(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'controllers' / 'calibration.py').read_text(encoding='utf-8')
        block = source.split('    def _workflow_check_clicked', 1)[1].split('    def _refresh_workflow_completion', 1)[0]
        self.assertNotIn('_show_tool', block)
        self.assertIn('_refresh_workflow_completion', block)

    def test_checklist_has_explicit_user_activation_signal(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'checklist.py').read_text(encoding='utf-8')
        self.assertIn('self.userActivated = Signal(self)', source)
        self.assertIn('self.userActivated.emit(key)', source)

    def test_native_checkbox_activation_precedes_completion_refresh(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'checklist.py').read_text(encoding='utf-8')
        block = source.split('    def _check_clicked', 1)[1].split('    def _add_native_item', 1)[0]
        self.assertLess(block.index('self.userActivated.emit(key)'), block.index('super()._check_clicked(sender, checked, key)'))
        self.assertIn('self.checkboxes.get(key) != sender', block)



if __name__ == '__main__':
    unittest.main()
