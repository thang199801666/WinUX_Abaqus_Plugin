import unittest
from unittest.mock import patch

from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.ui.controllers.project import ProjectController


class _DataController:
    def _fmt(self, value):
        return 'fmt:{}'.format(value)

    def _key_point(self, key):
        return ('parsed', key)


class _ProjectController:
    def _project_frame(self):
        return 123


class _DialogOwner:
    def __init__(self):
        self.data = _DataController()
        self.project = _ProjectController()

    def _controller(self, name, controller_type):
        if name == '_data_controller':
            return self.data
        if name == '_project_controller':
            return self.project
        raise AssertionError(name)


class _Renderer:
    def get_frame_count(self):
        return 77


class _ProjectOwner:
    def _renderer_backend(self):
        return _Renderer()


class DigitizerInstanceDelegateRegressionTests(unittest.TestCase):
    def test_dialog_fmt_is_instance_delegate(self):
        owner = _DialogOwner()
        self.assertEqual(PlotDigitizerDialog._fmt(owner, 5), 'fmt:5')

    def test_dialog_key_point_is_instance_delegate(self):
        owner = _DialogOwner()
        self.assertEqual(PlotDigitizerDialog._key_point(owner, 'manual:2'), ('parsed', 'manual:2'))

    def test_dialog_project_frame_is_instance_delegate(self):
        owner = _DialogOwner()
        self.assertEqual(PlotDigitizerDialog._project_frame(owner), 123)

    def test_project_controller_project_frame_uses_owner_fallback(self):
        controller = ProjectController(_ProjectOwner())
        with patch('WinUx.plotdigitizer.ui.controllers.project.QApplication.instance', return_value=None):
            self.assertEqual(controller._project_frame(), 77)


if __name__ == '__main__':
    unittest.main()
