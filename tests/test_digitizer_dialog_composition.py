import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIALOG = ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py'
CONTROLLERS = ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'controllers'


class PlotDigitizerDialogCompositionTests(unittest.TestCase):
    def test_root_dialog_is_bounded_composition_module(self):
        source = DIALOG.read_text(encoding='utf-8')
        self.assertLess(len(source.splitlines()), 2000)
        tree = ast.parse(source)
        dialog = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == 'PlotDigitizerDialog')
        init = next(node for node in dialog.body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
        rendered = ast.unparse(init)
        for name in ('CanvasController', 'CalibrationController', 'DataController', 'ProjectController'):
            self.assertIn(name, rendered)

    def test_qobject_children_are_created_after_dialog_base_init(self):
        tree = ast.parse(DIALOG.read_text(encoding='utf-8'))
        dialog = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == 'PlotDigitizerDialog')
        init = next(node for node in dialog.body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
        statements = [ast.unparse(node) for node in init.body]
        super_index = next(i for i, text in enumerate(statements)
                           if text.startswith('super().__init__('))
        tx_index = next(i for i, text in enumerate(statements)
                        if 'QEditTransaction(parent=self)' in text)
        self.assertGreater(tx_index, super_index)

    def test_feature_controller_modules_exist(self):
        expected = {
            'canvas.py': 'CanvasController',
            'calibration.py': 'CalibrationController',
            'data.py': 'DataController',
            'project.py': 'ProjectController',
        }
        for filename, classname in expected.items():
            tree = ast.parse((CONTROLLERS / filename).read_text(encoding='utf-8'))
            cls = next((node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == classname), None)
            self.assertIsNotNone(cls, filename)
            init = next(node for node in cls.body
                        if isinstance(node, ast.FunctionDef) and node.name == '__init__')
            self.assertIn('self.owner = owner', ast.unparse(init))

    def test_heavy_methods_delegate_from_dialog(self):
        tree = ast.parse(DIALOG.read_text(encoding='utf-8'))
        dialog = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == 'PlotDigitizerDialog')
        methods = {node.name: node for node in dialog.body if isinstance(node, ast.FunctionDef)}
        expected = {
            '_redraw': 'CanvasController',
            '_start_tick_calibration': 'CalibrationController',
            '_start_extraction': 'DataController',
            '_open_image': 'ProjectController',
        }
        for method, controller in expected.items():
            rendered = ast.unparse(methods[method])
            self.assertLessEqual(len(methods[method].body), 1, method)
            self.assertIn(controller, rendered)
            self.assertIn('self._controller', rendered)

    def test_controller_implementations_do_not_import_dialog_root(self):
        for path in CONTROLLERS.glob('*.py'):
            if path.name == '__init__.py':
                continue
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('plotdigitizer.ui.dialog import', source, path.name)
            self.assertNotIn('from ..dialog import', source, path.name)


if __name__ == '__main__':
    unittest.main()
