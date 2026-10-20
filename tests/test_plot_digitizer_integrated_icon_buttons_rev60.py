from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"


def test_icon_text_actions_overlay_raster_inside_real_qpushbutton():
    source = FORM.read_text(encoding="utf-8")
    block = source.split("def _icon_action(", 1)[1].split("def _icon_only_action(", 1)[0]
    assert "ICON_ACTION_HEIGHT = 26" in source
    assert "ICON_ACTION_GUTTER = 26" in source
    assert "display_label = \"   \" + str(label)" in block
    assert "button = self.action(" in block
    assert "button = self._toggle_action(" in block
    assert "overlay_widget = QCanvas(" in block
    assert "image = QPainter(overlay_widget).drawImage(" in block
    assert "self._icon_action_draws[button] = image" in block
    assert "wrapper.click()" in block


def test_disabled_icon_text_actions_dim_the_embedded_raster():
    source = FORM.read_text(encoding="utf-8")
    assert "def set_control_enabled(self, item, enabled):" in source
    assert "image = self._icon_action_draws.get(item)" in source
    assert "(155, 155, 155, 170)" in source
