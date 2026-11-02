"""Regression guards for the deployable WinUx/DearUIQt source layout."""
import ast
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winux_runtime.update.manifest import source_descriptor


class ProjectStructureTests(unittest.TestCase):
    def test_dearuiqt_is_a_single_root_level_package(self):
        self.assertTrue((ROOT / "DearUIQt" / "__init__.py").is_file())
        self.assertTrue((ROOT / "WinUx" / "__init__.py").is_file())
        self.assertFalse((ROOT / "WinUx" / "DearUIQt").exists())

    def test_all_relative_import_modules_resolve_on_disk(self):
        """Catch stale relative imports after moving modules between packages."""
        source_root = ROOT / "WinUx"
        offenders = []
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            rel = path.relative_to(ROOT).with_suffix("")
            package_parts = list(rel.parts[:-1])
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.level:
                    continue
                up = node.level - 1
                if up > len(package_parts):
                    offenders.append((str(path.relative_to(ROOT)), node.lineno, "relative import escapes package"))
                    continue
                target_parts = package_parts[:len(package_parts) - up]
                if node.module:
                    target_parts.extend(node.module.split("."))
                target = ROOT.joinpath(*target_parts)
                if not (target.with_suffix(".py").is_file() or target.is_dir()):
                    rendered = "." * node.level + (node.module or "")
                    offenders.append((str(path.relative_to(ROOT)), node.lineno, rendered))
        self.assertEqual(offenders, [])

    def test_dearuiqt_does_not_import_winux(self):
        offenders = []
        for path in sorted((ROOT / "DearUIQt").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "WinUx" or alias.name.startswith("WinUx.")
                           for alias in node.names):
                        offenders.append(str(path.relative_to(ROOT)))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "WinUx" or module.startswith("WinUx."):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


    def test_canonical_application_modules_are_packaged_by_responsibility(self):
        expected = (
            ROOT / "WinUx" / "app" / "controller.py",
            ROOT / "WinUx" / "ui" / "main_window.py",
            ROOT / "WinUx" / "services" / "ssh_server.py",
            ROOT / "WinUx" / "services" / "inp_reader.py",
            ROOT / "WinUx" / "platform" / "resources.py",
            ROOT / "WinUx" / "services" / "server_notepad" / "process.py",
        )
        self.assertTrue(all(path.is_file() for path in expected))
        self.assertFalse((ROOT / "WinUx" / "services" / "server_notepad_process.py").exists())

    def test_legacy_top_level_modules_are_compatibility_aliases(self):
        alias_targets = {
            "controller.py": "WinUx.app.controller",
            "view.py": "WinUx.ui.main_window",
            "server_model.py": "WinUx.services.ssh_server",
            "inp_reader.py": "WinUx.services.inp_reader",
            "resources.py": "WinUx.platform.resources",
        }
        for filename, target in alias_targets.items():
            text = (ROOT / "WinUx" / filename).read_text(encoding="utf-8")
            self.assertIn("alias_module", text)
            self.assertIn(target, text)


    def test_feature_families_use_canonical_subpackages(self):
        canonical = (
            ROOT / "WinUx" / "services" / "transfer" / "remote.py",
            ROOT / "WinUx" / "services" / "transfer" / "tree.py",
            ROOT / "WinUx" / "services" / "odb" / "remote.py",
            ROOT / "WinUx" / "services" / "odb" / "upgrade.py",
            ROOT / "WinUx" / "runtime" / "terminal" / "buffer.py",
            ROOT / "WinUx" / "runtime" / "terminal" / "vt.py",
            ROOT / "WinUx" / "ui" / "components" / "explorer" / "list_view.py",
            ROOT / "WinUx" / "ui" / "components" / "explorer" / "pointer_dispatch.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))

    def test_flat_feature_modules_are_compatibility_aliases(self):
        aliases = {
            ROOT / "WinUx" / "services" / "remote_transfer.py": "WinUx.services.transfer.remote",
            ROOT / "WinUx" / "services" / "transfer_tree.py": "WinUx.services.transfer.tree",
            ROOT / "WinUx" / "services" / "remote_odb.py": "WinUx.services.odb.remote",
            ROOT / "WinUx" / "services" / "odb_upgrade.py": "WinUx.services.odb.upgrade",
            ROOT / "WinUx" / "runtime" / "terminal_buffer.py": "WinUx.runtime.terminal.buffer",
            ROOT / "WinUx" / "runtime" / "vt_terminal.py": "WinUx.runtime.terminal.vt",
            ROOT / "WinUx" / "ui" / "components" / "explorer_list_view.py": "WinUx.ui.components.explorer.list_view",
            ROOT / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py": "WinUx.ui.components.explorer.pointer_dispatch",
        }
        for path, target in aliases.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn("alias_module", text)
            self.assertIn(target, text)


    def test_dialog_features_use_canonical_subpackages(self):
        canonical = (
            ROOT / "WinUx" / "dialogs" / "selectors" / "local_folder_form.py",
            ROOT / "WinUx" / "dialogs" / "jobs" / "job_schedule_form.py",
            ROOT / "WinUx" / "dialogs" / "transfer" / "transfer_center_form.py",
            ROOT / "WinUx" / "dialogs" / "odb" / "odb_extract_form.py",
            ROOT / "WinUx" / "dialogs" / "reference" / "reference_chart_form.py",
            ROOT / "WinUx" / "dialogs" / "settings" / "settings_form.py",
            ROOT / "WinUx" / "dialogs" / "console" / "console_form.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))

    def test_flat_dialog_feature_modules_are_compatibility_aliases(self):
        aliases = {
            ROOT / "WinUx" / "dialogs" / "local_folder_form.py": "WinUx.dialogs.selectors.local_folder_form",
            ROOT / "WinUx" / "dialogs" / "job_schedule_form.py": "WinUx.dialogs.jobs.job_schedule_form",
            ROOT / "WinUx" / "dialogs" / "transfer_center_form.py": "WinUx.dialogs.transfer.transfer_center_form",
            ROOT / "WinUx" / "dialogs" / "odb_extract_form.py": "WinUx.dialogs.odb.odb_extract_form",
            ROOT / "WinUx" / "dialogs" / "reference_chart_form.py": "WinUx.dialogs.reference.reference_chart_form",
            ROOT / "WinUx" / "dialogs" / "settings_form.py": "WinUx.dialogs.settings.settings_form",
            ROOT / "WinUx" / "dialogs" / "console_form.py": "WinUx.dialogs.console.console_form",
        }
        for path, target in aliases.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn("alias_module", text)
            self.assertIn(target, text)

    def test_controller_features_use_canonical_subpackages(self):
        canonical = (
            ROOT / "WinUx" / "controllers" / "explorer" / "navigation.py",
            ROOT / "WinUx" / "controllers" / "explorer" / "commands.py",
            ROOT / "WinUx" / "controllers" / "jobs" / "polling.py",
            ROOT / "WinUx" / "controllers" / "jobs" / "schedule.py",
            ROOT / "WinUx" / "controllers" / "transfer" / "controller.py",
            ROOT / "WinUx" / "controllers" / "transfer" / "clipboard.py",
            ROOT / "WinUx" / "controllers" / "inp" / "analysis.py",
            ROOT / "WinUx" / "controllers" / "odb" / "analysis.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))
        self.assertFalse((ROOT / "WinUx" / "controllers" / "transfer.py").exists())

    def test_flat_controller_feature_modules_are_compatibility_aliases(self):
        aliases = {
            ROOT / "WinUx" / "controllers" / "navigation.py": "WinUx.controllers.explorer.navigation",
            ROOT / "WinUx" / "controllers" / "file_commands.py": "WinUx.controllers.explorer.commands",
            ROOT / "WinUx" / "controllers" / "job_polling.py": "WinUx.controllers.jobs.polling",
            ROOT / "WinUx" / "controllers" / "job_schedule.py": "WinUx.controllers.jobs.schedule",
            ROOT / "WinUx" / "controllers" / "clipboard_transfer.py": "WinUx.controllers.transfer.clipboard",
            ROOT / "WinUx" / "controllers" / "sync_preview.py": "WinUx.controllers.transfer.sync_preview",
            ROOT / "WinUx" / "controllers" / "inp_analysis.py": "WinUx.controllers.inp.analysis",
            ROOT / "WinUx" / "controllers" / "odb_analysis.py": "WinUx.controllers.odb.analysis",
        }
        for path, target in aliases.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn("alias_module", text)
            self.assertIn(target, text)

    def test_ui_behaviors_use_grouped_subpackages(self):
        canonical = (
            ROOT / "WinUx" / "ui" / "behaviors" / "docking" / "plot.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "docking" / "console.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "splitter" / "behavior.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "splitter" / "layout.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "input" / "pointer.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "window" / "lifecycle.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "window" / "compact_job_monitor.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "window" / "startup_docking.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "window" / "application_menu.py",
            ROOT / "WinUx" / "ui" / "behaviors" / "window" / "dialog_facade.py",
            ROOT / "WinUx" / "app" / "facades" / "connection.py",
            ROOT / "WinUx" / "app" / "facades" / "jobs.py",
            ROOT / "WinUx" / "app" / "facades" / "explorer.py",
            ROOT / "WinUx" / "app" / "facades" / "transfer.py",
            ROOT / "WinUx" / "app" / "facades" / "analysis.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))

    def test_main_window_and_controller_are_composition_roots(self):
        main_path = ROOT / "WinUx" / "ui" / "main_window.py"
        controller_path = ROOT / "WinUx" / "app" / "controller.py"
        main_tree = ast.parse(main_path.read_text(encoding="utf-8"))
        controller_tree = ast.parse(controller_path.read_text(encoding="utf-8"))
        main_class = next(node for node in main_tree.body
                          if isinstance(node, ast.ClassDef) and node.name == "WinUXView")
        controller_class = next(node for node in controller_tree.body
                                if isinstance(node, ast.ClassDef) and node.name == "WinUXController")
        main_bases = {ast.unparse(base) for base in main_class.bases}
        controller_bases = {ast.unparse(base) for base in controller_class.bases}
        self.assertIn("ViewLifecycleMixin", main_bases)
        self.assertIn("StartupDockingMixin", main_bases)
        self.assertIn("ApplicationMenuMixin", main_bases)
        self.assertIn("DialogFacadeMixin", main_bases)
        self.assertIn("CompactJobMonitorMixin", main_bases)
        self.assertIn("ConnectionFacadeMixin", controller_bases)
        self.assertIn("JobsFacadeMixin", controller_bases)
        self.assertIn("ExplorerFacadeMixin", controller_bases)
        self.assertIn("AnalysisFacadeMixin", controller_bases)
        self.assertIn("TransferFacadeMixin", controller_bases)
        self.assertIn("ConsoleFacadeMixin", controller_bases)
        self.assertIn("SavedNavigationMixin", controller_bases)
        main_methods = {node.name for node in main_class.body if isinstance(node, ast.FunctionDef)}
        controller_methods = {node.name for node in controller_class.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_wait_for_ui_frame", main_methods)
        self.assertNotIn("_finish_deferred_startup", main_methods)
        self.assertNotIn("_build_menu", main_methods)
        self.assertNotIn("show_login", main_methods)
        self.assertNotIn("collapse_to_job_monitor", main_methods)
        self.assertNotIn("console_refresh", controller_methods)
        self.assertNotIn("bookmark_command", controller_methods)
        self.assertNotIn("login", controller_methods)
        self.assertNotIn("job_command", controller_methods)
        self.assertNotIn("open_path", controller_methods)
        self.assertNotIn("check_odb", controller_methods)
        self.assertNotIn("quick_transfer", controller_methods)


    def test_reference_chart_is_composed_from_feature_subsystems(self):
        reference_dir = ROOT / "WinUx" / "dialogs" / "reference"
        canonical = (
            reference_dir / "reference_chart_form.py",
            reference_dir / "regex_tester.py",
            reference_dir / "preview.py",
            reference_dir / "formula_authoring.py",
            reference_dir / "formula_catalog.py",
            reference_dir / "series_library.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))

        root_path = reference_dir / "reference_chart_form.py"
        root_text = root_path.read_text(encoding="utf-8")
        root_tree = ast.parse(root_text)
        dialog_class = next(node for node in root_tree.body
                            if isinstance(node, ast.ClassDef)
                            and node.name == "ReferenceChartDialog")
        bases = {ast.unparse(base) for base in dialog_class.bases}
        self.assertIn("ReferencePreviewMixin", bases)
        self.assertIn("ReferenceFormulaMixin", bases)
        self.assertIn("ReferenceSeriesLibraryMixin", bases)
        direct_methods = {node.name for node in dialog_class.body
                          if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_reduce_xy_samples", direct_methods)
        self.assertNotIn("_open_regex_tester", direct_methods)
        self.assertNotIn("_refresh_list", direct_methods)
        self.assertLess(len(root_text.splitlines()), 1000)

        regex_text = (reference_dir / "regex_tester.py").read_text(encoding="utf-8")
        regex_tree = ast.parse(regex_text)
        imported_modules = set()
        for node in ast.walk(regex_tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.add(node.module or "")
        self.assertFalse(any(module.endswith("reference_chart_form")
                             for module in imported_modules))

    def test_tick_detection_is_composed_from_focused_subsystems(self):
        core = ROOT / "WinUx" / "plotdigitizer" / "core"
        ticks = core / "ticks"
        canonical = (
            ticks / "shared.py",
            ticks / "types.py",
            ticks / "pixels.py",
            ticks / "axis_math.py",
            ticks / "recognition.py",
            ticks / "source_ocr.py",
            ticks / "sequences.py",
            ticks / "pipeline.py",
        )
        self.assertTrue(all(path.is_file() for path in canonical))
        facade = core / "tick_detection.py"
        facade_text = facade.read_text(encoding="utf-8")
        self.assertLess(len(facade_text.splitlines()), 250)
        self.assertIn("_TickDetectionFacadeModule", facade_text)
        self.assertIn("from .ticks.pipeline import", facade_text)
        self.assertNotIn("def _detect_axis_impl", facade_text)
        self.assertNotIn("def _cached_small_source_word", facade_text)
        self.assertNotIn("def _zero_anchored_template_detection", facade_text)

    def test_flat_ui_behaviors_are_compatibility_aliases(self):
        aliases = {
            ROOT / "WinUx" / "ui" / "behaviors" / "plot_docking.py": "WinUx.ui.behaviors.docking.plot",
            ROOT / "WinUx" / "ui" / "behaviors" / "console_docking.py": "WinUx.ui.behaviors.docking.console",
            ROOT / "WinUx" / "ui" / "behaviors" / "splitter_behavior.py": "WinUx.ui.behaviors.splitter.behavior",
            ROOT / "WinUx" / "ui" / "behaviors" / "splitter_layout.py": "WinUx.ui.behaviors.splitter.layout",
            ROOT / "WinUx" / "ui" / "behaviors" / "pointer_routing.py": "WinUx.ui.behaviors.input.pointer",
        }
        for path, target in aliases.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn("alias_module", text)
            self.assertIn(target, text)

    def test_compatibility_helper_is_not_owned_by_ui(self):
        root_helper = (ROOT / "WinUx" / "_compat.py").read_text(encoding="utf-8")
        ui_helper = (ROOT / "WinUx" / "ui" / "_compat.py").read_text(encoding="utf-8")
        self.assertIn("def alias_module", root_helper)
        self.assertIn("from .._compat import alias_module", ui_helper)

    def test_manifest_has_no_generated_or_nested_framework_files(self):
        manifest = json.loads((ROOT / "update_manifest.json").read_text(encoding="utf-8"))
        paths = [entry["path"].replace("\\", "/") for entry in manifest["files"]]
        self.assertFalse(any("/__pycache__/" in "/{}".format(path) for path in paths))
        self.assertFalse(any(path.endswith((".pyc", ".pyo")) for path in paths))
        self.assertFalse(any(path.startswith("WinUx/DearUIQt/") for path in paths))

    def test_manifest_matches_current_source(self):
        descriptor = source_descriptor(str(ROOT), verify_hashes=True)
        self.assertEqual(descriptor["version"], (ROOT / "VERSION").read_text().strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
