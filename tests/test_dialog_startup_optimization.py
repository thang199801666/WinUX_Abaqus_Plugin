"""Safe startup optimizations must retain host validity and UI isolation."""
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.dialogs import folder_browser_style as style
from WinUx.ui.hosting.host import QDialogHostManager, QDialogHostPool
from WinUx.ui.hosting.source_signature_cache import SourceSnapshot


class BrowserTextureWarmupTests(unittest.TestCase):
    def test_cached_generated_texture_does_not_stat_disk_again(self):
        with patch.object(style.dpg, "does_item_exist", return_value=True), \
                patch.object(Path, "is_file", side_effect=AssertionError("unexpected filesystem stat")):
            tag = style._generated_folder_selector_icon("folder", size=16)
        self.assertEqual(tag, "folder_selector_generated_folder_normal_16px")

    def test_missing_texture_still_checks_resource_and_falls_back(self):
        with patch.object(style.dpg, "does_item_exist", return_value=False), \
                patch.object(Path, "is_file", return_value=False) as exists:
            self.assertIsNone(style._generated_folder_selector_icon("folder", size=16))
        exists.assert_called_once_with()

    def test_warmup_is_bounded_graphics_only_and_deduplicates_tags(self):
        with patch.object(style, "navigation_texture", return_value="navigation") as normal, \
                patch.object(style, "navigation_disabled_texture", return_value="disabled") as disabled, \
                patch.object(style, "new_folder_texture", return_value="new"), \
                patch.object(style, "view_mode_texture", return_value="view"), \
                patch.object(style, "folder_item_texture", return_value="folder"), \
                patch.object(style, "_generated_folder_selector_icon", return_value=None), \
                patch.object(style.WindowsIconRegistry, "get_icon", return_value="shell-folder"), \
                patch.object(style.WindowsIconRegistry, "get_stock_icon", return_value="stock") as stock, \
                patch("WinUx.dialogs.floating_forms.create_form") as form, \
                patch("os.scandir", side_effect=AssertionError("prewarm must not list folders")):
            tags = style.prepare_browser_textures()
        self.assertEqual(normal.call_count, 9)
        self.assertEqual(disabled.call_count, 3)
        self.assertEqual([call.args[0] for call in stock.call_args_list], [7, 8, 9, 11, 12, 58, 94])
        self.assertEqual(len(tags), len(set(tags)))
        self.assertNotIn(None, tags)
        form.assert_not_called()


class DialogHostAffinityTests(unittest.TestCase):
    @staticmethod
    def host(kind):
        host = Mock()
        host.last_kind = kind
        host.idle_ack = True
        host.closed = False
        host.ready = threading.Event()
        host.ready.set()
        host.source_signature = ("source",)
        host.source_epoch = 0
        host.process.poll.return_value = None
        host.reusable = True
        host.reuse_count = 1
        host.lease = "old"
        return host

    def pool(self, hosts):
        pool = object.__new__(QDialogHostPool)
        pool._lock = threading.Lock()
        pool._closed = False
        pool.reusable = True
        pool._workers = list(hosts)
        pool._leased = set()
        pool._identity = Mock(return_value=SourceSnapshot(("source",), 0))
        pool.refill = Mock()
        return pool

    def test_same_kind_host_is_preferred_over_fifo_without_removing_fallbacks(self):
        confirmation, browser = self.host("blocking"), self.host("local_folder")
        pool = self.pool([confirmation, browser])
        self.assertIs(pool.claim(kind="local_folder", refill=False), browser)
        self.assertEqual(pool._workers, [confirmation])
        self.assertIn(browser, pool._leased)
        pool.refill.assert_not_called()

    def test_unavailable_matching_host_never_delays_other_ready_host(self):
        confirmation, browser = self.host("blocking"), self.host("local_folder")
        browser.ready.clear()
        browser.idle_ack = False
        pool = self.pool([confirmation, browser])
        self.assertIs(pool.claim(kind="local_folder", refill=False), confirmation)

    def test_source_validation_still_rejects_outdated_matching_host(self):
        confirmation, browser = self.host("blocking"), self.host("local_folder")
        browser.source_signature = ("outdated",)
        pool = self.pool([confirmation, browser])
        self.assertIs(pool.claim(kind="local_folder", refill=False), confirmation)
        browser.close.assert_called_once_with()

    def test_contention_returns_immediately_even_for_matching_kind(self):
        pool = self.pool([self.host("blocking")])
        with pool._lock:
            self.assertIsNone(pool.claim(kind="blocking"))

    def test_manager_records_kind_for_the_next_clean_lease(self):
        host = self.host(None)
        pool = Mock()
        pool.claim.return_value = host
        view = SimpleNamespace(_dialog_host_pool=pool, _dialog_prewarm_pool=pool)
        lease = QDialogHostManager(view, pool).acquire("settings")
        self.assertIs(lease.host, host)
        self.assertEqual(host.last_kind, "settings")
        pool.claim.assert_called_once_with(refill=False, kind="settings")


if __name__ == "__main__":
    unittest.main()
