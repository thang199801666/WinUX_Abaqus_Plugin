from pathlib import Path


def test_job_viewer_uses_slightly_larger_rows_and_header():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'ui' / 'components' / 'jobs_view.py').read_text(encoding='utf-8')
    assert 'set_metrics(row_height=27, header_height=28, cell_padding=7)' in source
