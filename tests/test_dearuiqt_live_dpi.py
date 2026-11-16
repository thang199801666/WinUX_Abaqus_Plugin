from contextlib import contextmanager
from pathlib import Path
import itertools
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.gui import metrics_for_dpi
from DearUIQt.gui.dpi import (
    clear_backend_dpi_state, logical_dpi_for_backend, register_dpi_root,
    sync_backend_dpi,
)
from DearUIQt.widgets.widget import QWidget
from DearUIQt.widgets.buttons import ImGuiPushButton, QToolButton
from DearUIQt.core.object import QEvent


class LiveDpiBackend:
    def __init__(self, dpi=96):
        self.dpi = dpi
        self.dpi_calls = 0
        self._ids = itertools.count(1)
        self.items = {}
        self.configure_calls = []

    def get_logical_dpi(self):
        self.dpi_calls += 1
        return self.dpi, self.dpi

    def _add(self, **options):
        tag = next(self._ids)
        self.items[tag] = dict(options)
        return tag

    def add_window(self, **options):
        return self._add(**options)

    def add_child_window(self, **options):
        return self._add(**options)

    def add_button(self, **options):
        return self._add(**options)

    def add_group(self, **options):
        return self._add(**options)

    def does_item_exist(self, tag):
        return tag in self.items

    def configure_item(self, tag, **options):
        self.configure_calls.append((tag, dict(options)))
        self.items[tag].update(options)

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def get_item_state(self, _tag):
        return {}

    def get_item_parent(self, tag):
        return self.items[tag].get('parent', 0)

    def move_item(self, tag, parent=None, **_kwargs):
        self.items[tag]['parent'] = parent

    def delete_item(self, tag, **_kwargs):
        self.items.pop(tag, None)

    def set_value(self, tag, value):
        self.items[tag]['value'] = value

    def get_value(self, tag):
        return self.items[tag].get('value')


class TrackingRoot(QWidget):
    def __init__(self, *, backend):
        self.dpi_events = []
        self.geometry_updates = 0
        super().__init__(backend=backend)

    def changeEvent(self, event):
        if event.type() == QEvent.DevicePixelRatioChange:
            self.dpi_events.append((event.payload['oldDpi'], event.payload['dpi']))

    def updateGeometry(self):
        self.geometry_updates += 1
        return True


class LiveDpiLifecycleTests(unittest.TestCase):
    def tearDown(self):
        clear_backend_dpi_state()

    def test_backend_dpi_resolver_prefers_renderer_contract(self):
        backend = LiveDpiBackend(144)
        self.assertEqual(logical_dpi_for_backend(backend), 144.0)

    def test_one_monitor_transition_refreshes_tree_and_invalidates_root_once(self):
        backend = LiveDpiBackend(96)
        root = TrackingRoot(backend=backend)
        with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
             patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
            button = ImGuiPushButton('Run', parent=root, backend=backend)
        try:
            self.assertEqual(backend.items[button.tag]['height'], metrics_for_dpi(96).button_height)
            backend.dpi = 144
            changed = sync_backend_dpi(backend)
            self.assertGreaterEqual(changed, 2)
            self.assertEqual(root.dpi_events, [(96.0, 144.0)])
            self.assertEqual(root.geometry_updates, 1)
            self.assertEqual(backend.items[button.tag]['height'], metrics_for_dpi(144).button_height)

            calls = len(backend.configure_calls)
            self.assertEqual(sync_backend_dpi(backend), 0)
            self.assertEqual(root.geometry_updates, 1)
            self.assertEqual(len(backend.configure_calls), calls)
        finally:
            button.delete()
            root.delete()

    def test_explicit_button_height_survives_dpi_change(self):
        backend = LiveDpiBackend(96)
        with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
             patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
            button = ImGuiPushButton('Fixed', height=31, backend=backend)
        try:
            backend.dpi = 192
            sync_backend_dpi(backend)
            self.assertEqual(backend.items[button.tag]['height'], 31)
        finally:
            button.delete()

    def test_tool_button_default_height_and_icon_follow_live_dpi(self):
        backend = LiveDpiBackend(96)
        with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
             patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
            tool = QToolButton('Tool', backend=backend)
        try:
            backend.dpi = 144
            sync_backend_dpi(backend)
            metrics = metrics_for_dpi(144)
            self.assertEqual(backend.items[tool.tag]['height'], metrics.tool_button_height)
            self.assertEqual(tool.iconSize(), (metrics.tool_button_icon_size,) * 2)
        finally:
            tool.delete()

    def test_force_dispatch_is_available_for_backend_repolish(self):
        backend = LiveDpiBackend(120)
        root = TrackingRoot(backend=backend)
        try:
            register_dpi_root(root, backend)
            self.assertGreaterEqual(sync_backend_dpi(backend, force=True), 1)
            self.assertEqual(root.geometry_updates, 1)
        finally:
            root.delete()

    def test_legacy_native_parent_controls_share_one_primary_dpi_poll(self):
        backend = LiveDpiBackend(96)
        with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
             patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
            buttons = [ImGuiPushButton(str(index), parent=777, backend=backend)
                       for index in range(100)]
        try:
            backend.dpi_calls = 0
            self.assertEqual(sync_backend_dpi(backend), 0)
            self.assertEqual(backend.dpi_calls, 1)
            backend.dpi = 144
            backend.dpi_calls = 0
            self.assertEqual(sync_backend_dpi(backend), 100)
            self.assertEqual(backend.dpi_calls, 1)
        finally:
            for button in buttons:
                button.delete()

    def test_native_fallback_is_used_when_renderer_has_no_dpi_contract(self):
        class PlainBackend:
            pass
        backend = PlainBackend()
        with patch('DearUIQt.gui.dpi._windows_window_dpi', return_value=168.0):
            self.assertEqual(logical_dpi_for_backend(backend), 168.0)

    def test_runtime_polls_dpi_before_render_submission(self):
        from DearUIQt.runtime import QGuiRuntime

        class RenderBackend(LiveDpiBackend):
            def is_dearpygui_running(self):
                return True
            def render_dearpygui_frame(self):
                self.rendered = getattr(self, 'rendered', 0) + 1

        backend = RenderBackend(96)
        runtime = QGuiRuntime(backend)
        runtime._context_created = True
        with patch('DearUIQt.gui.dpi.sync_backend_dpi') as sync, \
             patch('DearUIQt.gui.popup_tracking.update_popup_positions'), \
             patch('DearUIQt.backends.shared_scrollers.update_shared_scrollers'), \
             patch('DearUIQt.backends.native_presentation.presentation_for', return_value=None):
            self.assertTrue(runtime.renderFrame())
        sync.assert_called_once_with(backend)
        self.assertEqual(backend.rendered, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
