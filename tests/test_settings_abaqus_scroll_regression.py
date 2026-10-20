"""Regression coverage for the Abaqus Versions page scroll/height contract.

Native Dear PyGui rendering is tested separately on Windows; these tests keep
layout and page-state regressions detectable on headless CI.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.dialogs.settings_form import SettingsDialog
from DearUIQt.dialogs import qt_dialog


def test_form_layout_is_content_height_not_remaining_parent_height():
    """A stretch-height table in an auto-resize group can grow every frame."""
    calls = []
    backend = SimpleNamespace(
        mvTable_SizingStretchProp=4,
        add_table=lambda **kwargs: calls.append(kwargs) or "form_table",
        add_table_column=lambda **kwargs: None,
        bind_item_theme=lambda *_args: None,
    )
    with patch.object(qt_dialog, "dpg", backend), patch.object(
        qt_dialog, "form_row_theme", return_value=None
    ):
        result = qt_dialog.QtDialog.form_layout(SimpleNamespace(content="body"), parent="section")
    assert result == "form_table"
    assert calls == [dict(
        parent="section", header_row=False, width=-1, height=0,
        policy=4, pad_outerX=False, borders_innerH=False,
        borders_outerH=False, borders_innerV=False, borders_outerV=False,
    )]


def test_reset_scroll_ignores_stale_page_and_closed_dialog():
    values = []
    viewport = SimpleNamespace(verticalScrollBar=lambda: SimpleNamespace(
        setValue=lambda value: values.append(value)))
    dialog = SimpleNamespace(
        _current_page="abaqus", winfo_exists=lambda: True, page_scroll=viewport)
    assert SettingsDialog._reset_page_scroll_if_current(dialog, "performance") is False
    assert values == []
    assert SettingsDialog._reset_page_scroll_if_current(dialog, "abaqus") is True
    assert values == [0]
    dialog.winfo_exists = lambda: False
    assert SettingsDialog._reset_page_scroll_if_current(dialog, "abaqus") is False
    assert values == [0]


def test_deferred_scroll_reset_does_not_steal_user_scroll_on_another_page():
    values = []
    pending = []
    fake = SimpleNamespace(
        _current_page="abaqus",
        page_scroll=SimpleNamespace(verticalScrollBar=lambda: SimpleNamespace(
            setValue=lambda value: values.append(value))),
        winfo_exists=lambda: True,
        view=SimpleNamespace(after_render=lambda callback, key: pending.append((callback, key))),
    )
    fake._reset_page_scroll_if_current = lambda key: SettingsDialog._reset_page_scroll_if_current(fake, key)
    SettingsDialog._schedule_page_scroll_reset(fake, "abaqus")
    assert values == [0] and len(pending) == 1
    fake._current_page = "performance"
    callback, key = pending.pop()
    assert callback(key) is False
    assert values == [0]


def test_abaqus_list_height_tracks_installed_versions(monkeypatch):
    from contextlib import nullcontext
    from WinUx.dialogs import settings_form

    results = []

    class StubList:
        def __init__(self, *_args, **kwargs):
            results.append(kwargs["visible_rows"])
            self.currentTextChanged = SimpleNamespace(connect=lambda callback: None)

        def setCurrentText(self, text):
            pass

    backend = SimpleNamespace(group=lambda **kwargs: nullcontext("buttons"))
    monkeypatch.setattr(settings_form, "dpg", backend)
    monkeypatch.setattr(settings_form, "QtListView", StubList)
    for count, expected in [(1, 2), (2, 2), (4, 4), (12, 6)]:
        state = SimpleNamespace(
            _versions=[f"abq{i}" for i in range(count)],
            view=SimpleNamespace(after=lambda *args: None),
            header=lambda *args, **kwargs: None,
            section=lambda *args, **kwargs: nullcontext("commands"),
            own_widget=lambda widget: widget,
            field=lambda *args, **kwargs: "editor",
            set_control_value=lambda *args: None,
            action=lambda *args, **kwargs: None,
            form_layout=lambda *args, **kwargs: "command_form",
            form_layout_row=lambda *args, **kwargs: "default_combo",
            combo=lambda *args, **kwargs: None,
        )
        SettingsDialog._build_abaqus_page(state, "abaqus_page", {"default_command": "abq0"})
        assert results[-1] == expected
