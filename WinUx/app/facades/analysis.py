"""INP and ODB analysis compatibility facade methods."""
from __future__ import annotations



class AnalysisFacadeMixin:
    def _inp_analysis_controller(self):
        component = getattr(self, "_inp_analysis", None)
        if component is None:
            from ...controllers.inp.analysis import InpAnalysisController
            component = InpAnalysisController(self)
            self._inp_analysis = component
        return component
    def check_inp(self, panel):
        return self._inp_analysis_controller().check_inp(panel)
    def _inp_check_succeeded(self, panel, summary):
        return self._inp_analysis_controller()._inp_check_succeeded(panel, summary)
    def _inp_check_failed(self, panel, error):
        return self._inp_analysis_controller()._inp_check_failed(panel, error)
    def _odb_analysis_controller(self):
        component = getattr(self, "_odb_analysis", None)
        if component is None:
            from ...controllers.odb.analysis import OdbAnalysisController
            component = OdbAnalysisController(self)
            self._odb_analysis = component
        return component
    def check_odb(self, panel, selected_paths=None):
        return self._odb_analysis_controller().check_odb(panel, selected_paths)
    def _odb_check_succeeded(self, panel, result):
        return self._odb_analysis_controller()._odb_check_succeeded(panel, result)
    def _odb_check_failed(self, panel, error):
        return self._odb_analysis_controller()._odb_check_failed(panel, error)
    def upgrade_odb(self, panel, selected_paths=None):
        return self._odb_analysis_controller().upgrade_odb(panel, selected_paths)
    def _odb_upgrade_checked(self, panel, result):
        return self._odb_analysis_controller()._odb_upgrade_checked(panel, result)
    def _start_odb_upgrade(self, panel, paths, abaqus_command):
        return self._odb_analysis_controller()._start_odb_upgrade(
            panel, paths, abaqus_command)
    def _odb_upgrade_succeeded(self, panel, result):
        return self._odb_analysis_controller()._odb_upgrade_succeeded(panel, result)
    def _odb_upgrade_failed(self, panel, error):
        return self._odb_analysis_controller()._odb_upgrade_failed(panel, error)
    def extract_odb(self, panel, selected_paths=None):
        return self._odb_analysis_controller().extract_odb(panel, selected_paths)
    def _odb_extract_catalog_ready(self, panel, path, catalog):
        return self._odb_analysis_controller()._odb_extract_catalog_ready(panel, path, catalog)
    def _extract_odb_selected(self, panel, path, selection):
        return self._odb_analysis_controller()._extract_odb_selected(panel, path, selection)
    def _odb_extract_succeeded(self, panel, result):
        return self._odb_analysis_controller()._odb_extract_succeeded(panel, result)
    def _odb_extract_failed(self, panel, error):
        return self._odb_analysis_controller()._odb_extract_failed(panel, error)
