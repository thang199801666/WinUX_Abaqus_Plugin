"""Native multi-window bridge accepts DearPyGui string aliases.

Regression for Plot tear-off: WinUx deliberately names its primary renderer item
``winux_primary``. Native-window calls must resolve that alias through DPG instead
of passing it to ``int()``.
"""
from types import SimpleNamespace

from DearUIQt.backends.native_windows import NativeWindowBackend


class _FakeNativeBackend:
    def __init__(self):
        self.aliases = {
            "winux_primary": 101,
            "plot_float": 202,
        }
        self.configured = []
        self.handles = {101: 10001, 202: 10002}

    def get_alias_id(self, alias):
        return self.aliases.get(alias, 0)

    def dearuiqt_enable_native_windows(self):
        return True

    def dearuiqt_native_windows_enabled(self):
        return True

    def dearuiqt_configure_native_window(self, tag, owner_tag, modal):
        self.configured.append((tag, owner_tag, bool(modal)))
        return True

    def dearuiqt_native_window_handle(self, tag):
        return self.handles.get(tag, 0)


def test_native_configure_resolves_string_item_and_owner_aliases():
    backend = _FakeNativeBackend()
    native = NativeWindowBackend(backend)

    assert native.configure("plot_float", owner="winux_primary", modal=False)
    assert backend.configured[-1] == (202, 101, False)
    assert native._configured_item_tag == 202
    assert native._configured_owner_tag == 101


def test_native_alias_resolution_accepts_widget_tag_and_all_followup_calls():
    backend = _FakeNativeBackend()
    native = NativeWindowBackend(backend)
    window = SimpleNamespace(tag="plot_float")
    owner = SimpleNamespace(tag="winux_primary")

    native.configure(window, owner=owner, modal=False)
    assert native.setModal(window, True)
    assert backend.configured[-1] == (202, 101, True)
    # No Win32 APIs are needed for raw handle resolution itself.
    assert native._rawWinId(window) == 10002
    # On non-Windows the method returns the handle after owner sync becomes a no-op.
    assert native.winId(window) == 10002


def test_unresolved_text_alias_reports_alias_error_not_int_literal_error():
    native = NativeWindowBackend(_FakeNativeBackend())
    try:
        native._rendererTag("missing_alias")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("unresolved alias should fail")

    assert "missing_alias" in message
    assert "invalid literal for int" not in message
