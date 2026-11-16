from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / 'WinUx' / 'dialogs' / 'selectors' / 'local_folder_form.py'
STYLE = ROOT / 'WinUx' / 'dialogs' / 'selectors' / 'folder_browser_style.py'


def test_selector_form_controls_share_one_explicit_height_contract():
    source = FORM.read_text(encoding='utf-8')
    ast.parse(source)
    assert 'self._folder_edit_control.setFixedHeight(METRICS.control_height)' in source
    assert 'file_type_control.setFixedHeight(METRICS.control_height)' in source
    assert 'height=METRICS.control_height)' in source  # action buttons


def test_selector_visual_height_is_compact_26px():
    source = STYLE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    value = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'BrowserMetrics':
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and getattr(stmt.target, 'id', None) == 'control_height':
                    value = ast.literal_eval(stmt.value)
    assert value == 26
