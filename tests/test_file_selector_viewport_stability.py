import inspect
import unittest

from WinUx.dialogs.local_folder_form import FolderListView, LocalPathDialog


class FileSelectorViewportStabilityTests(unittest.TestCase):
    def test_table_stays_direct_child_of_list_view(self):
        source = inspect.getsource(FolderListView.setItems)
        self.assertIn('columns=column_count, parent=self.tag', source)
        self.assertNotIn('_viewport_host_frame', source)
        self.assertIn('native hierarchy flat', source)

    def test_empty_state_stays_direct_child_of_list_view(self):
        source = inspect.getsource(FolderListView._add_empty_state)
        self.assertIn('parent=self.tag, width=-1, height=76', source)
        self.assertNotIn('_viewport_host_frame', source)

    def test_navigation_does_not_double_rebuild_old_empty_new(self):
        source = inspect.getsource(LocalPathDialog._navigate)
        self.assertIn('self.listbox.setInteractionEnabled(False)', source)
        self.assertNotIn('self.listbox.setEnabled(False)', source)
        self.assertIn('self._set_status("Loading...")', source)
        self.assertNotIn('self.listbox.setItems([])', source)

    def test_apply_reenables_list_before_commit(self):
        source = inspect.getsource(LocalPathDialog._apply_entries)
        self.assertIn('setInteractionEnabled', source)
        self.assertIn('set_interaction(True)', source)
        self.assertNotIn('setEnabled', source)

    def test_folder_list_view_uses_logical_interaction_gate(self):
        source = inspect.getsource(FolderListView.setInteractionEnabled)
        self.assertIn('_interaction_enabled', source)
        body = source.split('\n        self._interaction_enabled', 1)[1]
        self.assertNotIn('backend.', body)
        self.assertNotIn('_configure_many', body)
        self.assertNotIn('.setEnabled(', body)

    def test_navigation_result_does_not_restore_old_folder_scroll(self):
        source = inspect.getsource(LocalPathDialog._apply_entries)
        self.assertIn('is_navigation = (generation == getattr(self, "_navigation_generation", None))', source)
        self.assertIn('if can_snapshot_interaction and not is_navigation:', source)
        self.assertIn('self.listbox.setVerticalScrollValue(0.0)', source)


if __name__ == '__main__':
    unittest.main()
