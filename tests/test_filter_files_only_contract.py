from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'WinUx' / 'ui' / 'components' / 'file_panel.py'


def test_filter_never_hides_directories():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'if bool(getattr(item, "is_dir", False)):' in source
    assert 'or matches(item)' in source


def test_status_count_uses_same_directory_passthrough_rule():
    source = SOURCE.read_text(encoding='utf-8')
    status_start = source.index('    def _update_item_status(self, filtered=None) -> None:')
    status_end = source.index('    def apply_filter(self, query: str) -> bool:', status_start)
    status = source[status_start:status_end]
    assert 'bool(getattr(item, "is_dir", False)) or matches(item)' in status
