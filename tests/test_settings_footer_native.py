"""Settings page actions must never push Save/Cancel outside the footer."""
import sys
from types import SimpleNamespace
import unittest

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.dialogs.settings_form import SettingsDialog
from DearUIQt.qt.scroller import dpg_window_rect


class SettingsFooterTests(unittest.TestCase):
    def test_save_cancel_stay_inside_footer_on_every_page_and_resize(self):
        dpg.create_context()
        try:
            form = SettingsDialog(SimpleNamespace(after=lambda *args: None))
            dpg.create_viewport(title='Settings footer regression', width=760, height=560)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(form.tag, True)

            def ancestors(item):
                result = []
                while item:
                    item = dpg.get_item_parent(item)
                    if item:
                        result.append(item)
                return result

            def descendants(item):
                result = []
                for children in dpg.get_item_children(item).values():
                    for child in children:
                        result.append(child)
                        result.extend(descendants(child))
                return result

            # Settings pages are materialized lazily; request Updates before
            # asserting ownership of its action buttons.
            form._ensure_page('updates')
            page_actions = {dpg.get_item_configuration(item).get('label'): item
                            for item in descendants(form.page_host)
                            if dpg.get_item_info(item)['type'].endswith('mvButton')}
            for label in ('Refresh', 'Clear quarantine', 'Check for Updates', 'Update Now'):
                self.assertIn(label, page_actions)
                self.assertIn(form.pages['updates'], ancestors(page_actions[label]))
                self.assertNotIn(form.footer, ancestors(page_actions[label]))
            footer_labels = [dpg.get_item_configuration(item).get('label')
                             for item in descendants(form.footer)
                             if dpg.get_item_info(item)['type'].endswith('mvButton')]
            self.assertEqual(sorted(footer_labels), ['Cancel', 'Save', 'Set as Default'])
            self.assertEqual(dpg.get_item_configuration(form.set_default_button)['label'], 'Set as Default')
            self.assertIn(form.footer, ancestors(form.set_default_button))

            for width, height in ((760, 560), (680, 440), (900, 680)):
                dpg.configure_viewport(0, width=width, height=height)
                for page in form.pages:
                    form._show_page(page)
                    form._apply_layout()
                    for _ in range(4):
                        dpg.render_dearpygui_frame()
                    footer = dpg_window_rect(dpg, form.footer_shell, clip=True)
                    self.assertIsNotNone(footer)
                    for button in (form.set_default_button, form._default_button, form._reject_button):
                        x, y = dpg.get_item_rect_min(button)
                        w, h = dpg.get_item_rect_size(button)
                        self.assertGreater(w, 0)
                        self.assertGreater(h, 0)
                        self.assertGreaterEqual(y, footer[1])
                        self.assertLessEqual(y + h, footer[3])
                        self.assertLessEqual(y + h, dpg.get_viewport_client_height())
        finally:
            dpg.destroy_context()
