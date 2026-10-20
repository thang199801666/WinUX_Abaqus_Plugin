"""Regressions for the fixed-size SSH Login window."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIN = (ROOT / "WinUx" / "dialogs" / "login_form.py").read_text(encoding="utf-8")
QTDIALOG = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
NATIVE = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text(encoding="utf-8")


def test_login_declares_fixed_size_for_both_dialog_host_paths():
    assert "NATIVE_RESIZABLE = False" in LOGIN
    assert "ALLOW_MINIMIZE = False" in LOGIN
    assert "ALLOW_MAXIMIZE = False" in LOGIN
    assert 'super().__init__(view, "SSH Login", 420, 212, resizable=False)' in LOGIN


def test_qdialog_fixed_window_disables_retained_and_native_resize_paths():
    assert "no_resize=not self._resizable" in QTDIALOG
    assert "def setFixedSize(self, width, height=None):" in QTDIALOG
    assert "self.after_first_present(self._apply_native_resize_policy_once)" in QTDIALOG
    assert "backend.setResizable(self.tag, self._resizable)" in QTDIALOG
    assert "backend.setCaptionButtons(" in QTDIALOG
    assert "ALLOW_MINIMIZE = False" in QTDIALOG


def test_native_fixed_frame_removes_resize_border_and_maximize_box():
    assert "WS_THICKFRAME = 0x00040000" in NATIVE
    assert "WS_MAXIMIZEBOX = 0x00010000" in NATIVE
    assert "SWP_FRAMECHANGED = 0x0020" in NATIVE
    assert "desired = current & ~mask" in NATIVE
    assert "def setCaptionButtons" in NATIVE
    assert "desired &= ~WS_MINIMIZEBOX" in NATIVE
