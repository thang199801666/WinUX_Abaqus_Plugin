from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py').read_text(encoding='utf-8')


def test_statusbar_keeps_flat_known_working_child_window_structure():
    assert 'self._body_host' not in SOURCE
    assert 'self._layout_root_regions' not in SOURCE
    assert 'self.content, padding=(self.OUTER_MARGIN, 0)' in SOURCE
    assert 'self.content, quick_access=False' in SOURCE
    assert 'parent=self.content, width=-1, height=-self.STATUS_HEIGHT' in SOURCE


def test_statusbar_stays_direct_child_of_content():
    assert 'parent=self.content, width=-1, height=self.STATUS_HEIGHT' in SOURCE
    assert 'self.status_bar.setTheme(status_bar_theme' in SOURCE
    assert 'self._status_top_rule_canvas' in SOURCE
