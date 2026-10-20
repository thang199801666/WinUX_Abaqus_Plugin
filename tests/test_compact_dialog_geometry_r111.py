"""GUI-independent regression checks for compact Qt-style message dialogs."""
from __future__ import annotations

import ast
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sizer():
    # Do not import DearUIQt.dialogs.__init__: CI Linux has no native DearPyGui
    # extension. The helper is intentionally render/backend independent.
    path = ROOT / "DearUIQt" / "dialogs" / "sizing.py"
    spec = spec_from_file_location("dearuiqt_compact_dialog_sizing", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compact_message_size


def test_short_confirmation_uses_a_compact_height():
    size = _sizer()("Are you sure you want to exit WinUx?", heading="Exit WinUx?")
    assert size == (480, 148)
    assert size[1] < 190  # old global minimum
    assert size[1] < 220  # old unconditional BlockingDialog height


def test_input_dialog_keeps_room_for_an_editor():
    size = _sizer()("Enter bookmark name:", heading="Rename Bookmark", kind="input")
    assert size[1] >= _sizer()("Enter bookmark name:", heading="Rename Bookmark")[1] + 36


def test_multiline_messages_expand_without_cutting_off_content():
    size = _sizer()
    short = size("Proceed?", heading="Confirm")[1]
    multiline = size("Line one\nLine two\nLine three", heading="Confirm")[1]
    assert multiline > short
    # Long content never turns into a very tall screen-covering modal; its
    # scrollable body stays responsible for making *all* text accessible.
    assert size("Line\n" * 200, heading="Long text")[1] == 360


def test_long_wrapped_text_and_explicit_empty_rows_count():
    size = _sizer()
    assert size("X" * 400, heading="Title")[1] > size("X" * 30, heading="Title")[1]
    assert size("a\n\nb", heading="Title")[1] > size("a\nb", heading="Title")[1]


def test_minimum_width_and_legacy_tool_dialog_minimum_are_separate():
    size = _sizer()
    assert size("message", width=1)[0] == 360
    metrics = (ROOT / "DearUIQt" / "dialogs" / "theme.py").read_text()
    assert "MIN_DIALOG_HEIGHT = 190" in metrics
    assert "COMPACT_DIALOG_MIN_HEIGHT = 136" in metrics


def test_blocking_form_sizes_before_building_the_native_window():
    source = (ROOT / "WinUx" / "dialogs" / "blocking_form.py").read_text()
    tree = ast.parse(source)
    cls = next(item for item in tree.body if isinstance(item, ast.ClassDef)
               and item.name == "BlockingDialog")
    init = next(item for item in cls.body if isinstance(item, ast.FunctionDef)
                and item.name == "__init__")
    calls = [n for n in ast.walk(init) if isinstance(n, ast.Call)]
    sizing_call = next(n for n in calls if isinstance(n.func, ast.Name)
                       and n.func.id == "compact_message_size")
    super_init = next(n for n in calls if isinstance(n.func, ast.Attribute)
                      and n.func.attr == "__init__" and isinstance(n.func.value, ast.Call)
                      and isinstance(n.func.value.func, ast.Name)
                      and n.func.value.func.id == "super")
    assert sizing_call.lineno < super_init.lineno
    assert any(k.arg == "compact" and isinstance(k.value, ast.Constant) and k.value.value is True
               for k in super_init.keywords)
    assert "self.preferred_size = (480, content_height)" in source


def test_button_box_preserves_the_compact_minimum():
    source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
    cls = ast.parse(source)
    assert "self._minimum_dialog_height" in source
    assert 'getattr(\n                self, "_minimum_dialog_height", DialogMetrics.MIN_DIALOG_HEIGHT)' in source
    assert "min_size=(DialogMetrics.MIN_DIALOG_WIDTH, self._minimum_dialog_height)" in source


def test_delete_preview_does_not_accumulate_excess_footer_gap():
    size = _sizer()
    message = "\n".join([
        "You are about to permanently delete 9 item(s) from server.",
        "",
        "- Test-17-0283-Case-7-1.abq",
        "- Test-17-0283-Case-7-1.com",
        "- Test-17-0283-Case-7-1.dat",
        "- Test-17-0283-Case-7-1.inp",
        "- Test-17-0283-Case-7-1.log",
        "- Test-17-0283-Case-7-1.mdl",
        "- ... and 3 more",
        "",
        "WARNING: This action cannot be undone.",
        "Select OK only when you are sure you want to continue.",
    ])
    width, height = size(message, heading="Delete permanently?")
    assert width == 480
    # The old 19px-per-row heuristic produced 367px of client content and a
    # conspicuous blank band. Keep this representative warning near 313px.
    assert 300 <= height <= 320


def test_message_box_table_is_content_sized_not_remaining-space_sized():
    source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
    block = source.split("def message_box_body", 1)[1].split("def field", 1)[0]
    assert "header_row=False, width=-1, height=0" in block
