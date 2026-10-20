from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "local_folder_form.py").read_text(encoding="utf-8")


def test_folder_list_tracks_and_replaces_empty_state_surface():
    assert "self._empty_state_frame = None" in SOURCE
    assert "empty_state = self._empty_state_frame" in SOURCE
    assert "empty_state.delete()" in SOURCE


def test_empty_folder_renders_real_empty_state_instead_of_suppressing_it():
    assert 'if not self._values:\n            self._add_empty_state()' in SOURCE
    assert 'self.empty_text != "This folder is empty."' not in SOURCE


def test_empty_state_is_positioned_below_details_header():
    assert "pos=(0, METRICS.header_height)" in SOURCE
    assert 'QLabel(self.empty_text, parent=message_cell)' in SOURCE
    assert '"Reading folders in this location..."' in SOURCE
