from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "WinUx" / "components" / "explorer_list_model.py"
LIST_VIEW = ROOT / "WinUx" / "components" / "explorer_list_view.py"
LIST_DATA = ROOT / "WinUx" / "components" / "explorer_data_view.py"
ROW_REGISTRY = ROOT / "WinUx" / "components" / "explorer_row_registry.py"
SERVER_PATH = ROOT / "WinUx" / "dialogs" / "server_path_form.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"


def load_model():
    spec = importlib.util.spec_from_file_location("winux_list_model_v4", MODEL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PresentationCacheTests(unittest.TestCase):
    def test_list_item_caches_date_size_and_sort_keys(self):
        module = load_model()
        item = module.ListViewItem(
            "Report.odb", "C:/tmp/Report.odb", False, 1536, 1_600_000_000,
            item_type="ODB File")
        self.assertEqual(item.cached_size_text, "1.5 KB")
        self.assertEqual(item.cached_name_sort, "report.odb")
        self.assertEqual(item.cached_type_sort, "odb file")
        old_date = item.cached_date_text
        item.size = 2048
        item.mtime += 60
        item.refresh_display_cache()
        self.assertEqual(item.cached_size_text, "2.0 KB")
        self.assertNotEqual(item.cached_date_text, old_date)

    def test_listview_has_incremental_topology_refresh(self):
        source = (LIST_VIEW.read_text(encoding="utf-8") + "\n"
                  + LIST_DATA.read_text(encoding="utf-8") + "\n"
                  + ROW_REGISTRY.read_text(encoding="utf-8"))
        self.assertIn("def _stable_item_identity", source)
        self.assertIn("old_topology != new_topology", source)
        self.assertIn("self._row_registry_can_reuse", source)
        self.assertIn("self._refresh_row_content()", source)
        self.assertIn("cached_date_text", source)
        self.assertIn("cached_size_text", source)


class BoundedSearchTests(unittest.TestCase):
    def test_server_path_uses_background_task_manager_in_production(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("task_submitter", source)
        self.assertIn('key="server-path-search:{}".format(id(self))', source)
        self.assertIn("replace=True", source)
        self.assertIn("task_submitter=self._submit_background", controller)

    def test_stale_server_model_backup_is_removed(self):
        self.assertFalse((ROOT / "WinUx" / "server_model.py.bak").exists())


if __name__ == "__main__":
    unittest.main()
