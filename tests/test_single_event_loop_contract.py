from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SingleEventLoopContractTests(unittest.TestCase):
    def test_production_dialog_waits_do_not_pump_view_directly(self):
        files = [
            ROOT / "WinUx/dialogs/blocking_form.py",
            ROOT / "WinUx/ui/hosting/result_dialog.py",
            ROOT / "WinUx/dialogs/jobs/job_edit_form.py",
            ROOT / "DearUIQt/dialogs/qdialog.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"while\s+[^\n]*view\.update\(", str(path))
            self.assertNotIn("QEventLoop(pump=", text, str(path))

    def test_main_application_registers_one_host_turn(self):
        text = (ROOT / "WinUx/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("self._qapplication.setHostTurn(self.update)", text)

    def test_standalone_registers_application_host_turn(self):
        text = (ROOT / "WinUx/plotdigitizer/standalone.py").read_text(encoding="utf-8")
        self.assertIn("application.setHostTurn(host_turn)", text)

    def test_floating_runtime_uses_qeventloop_instead_of_render_while(self):
        text = (ROOT / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
        self.assertIn("self._event_loop = QEventLoop(application=self.application)", text)
        self.assertIn("self._event_loop.exec()", text)
        self.assertNotRegex(text, r"while\s+self\._wait_for_frame\(\)")

    def test_plotdigitizer_standalone_uses_qeventloop_for_main_run(self):
        text = (ROOT / "WinUx/plotdigitizer/standalone.py").read_text(encoding="utf-8")
        self.assertIn("event_loop = QEventLoop(application=application)", text)
        self.assertIn("event_loop.exec()", text)
        self.assertNotRegex(text, r"while\s+runtime\.isRunning\(\)")


if __name__ == "__main__":
    unittest.main()
