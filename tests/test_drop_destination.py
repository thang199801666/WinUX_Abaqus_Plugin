"""Drag release must never infer a download from a missing/stale target."""
from pathlib import Path, PurePosixPath
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.explorer_transfer_interaction import ExplorerTransferInteractionMixin
from WinUx.controllers.transfer import TransferController


class App(ExplorerTransferInteractionMixin):
    pass


class DropDestinationTests(unittest.TestCase):
    def app(self):
        app = App()
        app._closing = False
        local = SimpleNamespace(panel_id='local', current_path=Path('C:/local'),
                                clear_external_drop_highlight=Mock(), status=Mock(),
                                selected_transfer_paths=lambda: [Path('C:/local/a.inp')])
        server = SimpleNamespace(panel_id='server', current_path=PurePosixPath('/work'),
                                 clear_external_drop_highlight=Mock(), status=Mock(),
                                 selected_transfer_paths=lambda: [PurePosixPath('/work/a.inp')])
        app.view = SimpleNamespace(panels=[local, server], left=local, right=server,
                                   after=Mock(side_effect=lambda delay, callback, *args: callback(*args)))
        app.server = SimpleNamespace(connected=True, normalize=PurePosixPath,
                                     transfer=Mock(), download=Mock(), upload=Mock())
        app.model = SimpleNamespace(normalize=Path, transfer=Mock())
        app._process_queued_drop = Mock()
        app._drop_target = Mock(return_value=(server, server.current_path, (500, 200)))
        app._drop_is_valid = TransferController(app).drop_is_valid
        app._opposite_panel = Mock(side_effect=AssertionError('must not infer opposite pane'))
        app._drag_target_panel = local
        app._drag_target_destination = local.current_path
        app._drag_target_point = (100, 200)
        return app, local, server

    def assert_no_transfer(self, app):
        app._process_queued_drop.assert_not_called()
        app._opposite_panel.assert_not_called()
        app.server.download.assert_not_called()
        app.server.upload.assert_not_called()

    def test_server_release_back_in_current_folder_ignores_stale_local_hover(self):
        app, local, server = self.app()
        app.drop(server, 500, 200, False)
        self.assert_no_transfer(app)
        self.assertIsNone(app._drag_target_panel)
        self.assertIsNone(app._drag_target_destination)

    def test_server_child_folder_stays_on_server_even_with_local_hover_cache(self):
        app, local, server = self.app()
        app._drop_target.return_value = server, PurePosixPath('/work/child'), (500, 200)
        app.drop(server, 500, 200, False)
        app._process_queued_drop.assert_called_once_with(
            server, server, PurePosixPath('/work/child'), False, [PurePosixPath('/work/a.inp')])
        app._opposite_panel.assert_not_called()

    def test_actual_local_release_still_downloads_to_explicit_local_target(self):
        app, local, server = self.app()
        app._drag_target_panel, app._drag_target_destination = server, server.current_path
        app._drop_target.return_value = local, local.current_path, (100, 200)
        app.drop(server, 100, 200, True)
        app._process_queued_drop.assert_called_once_with(
            server, local, local.current_path, True, [PurePosixPath('/work/a.inp')])

    def test_unknown_outside_or_gutter_release_never_uses_cache(self):
        for target in ((None, None, None),):
            app, local, server = self.app()
            app._drop_target.return_value = target
            app.drop(server, 300, 200, True)
            self.assert_no_transfer(app)
        for point in ((0, 0), (None, None), ('bad', 10), (float('nan'), 10), (float('inf'), 10)):
            app, local, server = self.app()
            app.drop(server, *point, False)
            self.assert_no_transfer(app)
            app._drop_target.assert_not_called()

    def test_valid_negative_monitor_coordinates_are_not_lost(self):
        app, local, server = self.app()
        app._drop_target.return_value = local, local.current_path, (-500, -200)
        app.drop(server, -500, -200, True)
        self.assertEqual(app._process_queued_drop.call_args.args[1], local)

    def test_local_release_back_in_current_folder_does_not_upload(self):
        app, local, server = self.app()
        app._drag_target_panel, app._drag_target_destination = server, server.current_path
        app._drop_target.return_value = local, local.current_path, (100, 200)
        app.drop(local, 100, 200, True)
        self.assert_no_transfer(app)

    def test_queued_drop_without_target_cannot_become_download(self):
        for target, destination in ((None, None), (None, Path('C:/local')), (False, None)):
            app, local, server = self.app()
            controller = TransferController(app)
            controller.opposite_panel = Mock(side_effect=AssertionError('no fallback'))
            controller.start_drop_transfer = Mock()
            controller.process_queued_drop(server, target, destination, True, [PurePosixPath('/work/a.inp')])
            controller.opposite_panel.assert_not_called()
            controller.start_drop_transfer.assert_not_called()
            self.assert_no_transfer(app)

    def test_server_folder_drop_performs_remote_move_not_download(self):
        app, local, server = self.app()
        app._refresh_all = Mock()
        app._submit_transfer = Mock(side_effect=lambda name, worker, **kwargs: worker())
        controller = TransferController(app)
        controller.process_queued_drop(server, server, PurePosixPath('/work/child'), False,
                                       [PurePosixPath('/work/a.inp')])
        app.server.transfer.assert_called_once()
        self.assertTrue(app.server.transfer.call_args.kwargs['move'])
        app.server.download.assert_not_called()
        app.server.upload.assert_not_called()

    def test_motion_validation_is_cached_but_release_is_always_fresh(self):
        app, local, server = self.app()
        local.set_external_drop_highlight_at = Mock()
        server.drag_transfer_paths = Mock(return_value=[PurePosixPath('/work/a.inp')])
        app._drop_is_valid = Mock(wraps=app._drop_is_valid)
        app.drag_start(server)
        for _ in range(100):
            app.drag_motion(server, 500, 200)
        self.assertEqual(app._drop_is_valid.call_count, 1)
        self.assertEqual(server.drag_transfer_paths.call_count, 1)
        app._drop_target.return_value = local, local.current_path, (100, 200)
        for _ in range(100):
            app.drag_motion(server, 100, 200)
        self.assertEqual(app._drop_is_valid.call_count, 2)
        self.assertEqual(server.drag_transfer_paths.call_count, 1)
        # Hovering the same target must not clear/repaint its highlight each
        # frame. The row-level highlighter already deduplicates unchanged rows.
        local.clear_external_drop_highlight.assert_called_once()
        server.clear_external_drop_highlight.assert_called_once()
        app._drop_target.return_value = server, server.current_path, (500, 200)
        app.drop(server, 500, 200, False)
        self.assertEqual(app._drop_is_valid.call_count, 3)
        self.assert_no_transfer(app)

    def test_release_uses_drag_snapshot_not_a_changed_selection(self):
        app, local, server = self.app()
        server.drag_transfer_paths = Mock(return_value=[PurePosixPath('/work/original.odb')])
        app.drag_start(server)
        server.selected_transfer_paths = Mock(return_value=[PurePosixPath('/work/other.odb')])
        app._drop_target.return_value = local, local.current_path, (100, 200)
        app.drop(server, 100, 200, True)
        self.assertEqual(app._process_queued_drop.call_args.args[-1],
                         [PurePosixPath('/work/original.odb')])
        server.selected_transfer_paths.assert_not_called()

    def test_explicit_empty_drag_never_falls_back_to_new_selection(self):
        app, local, server = self.app()
        app._drop_target.return_value = local, local.current_path, (100, 200)
        app.drop(server, 100, 200, True, dragged_items=[])
        self.assert_no_transfer(app)
        self.assertIsNone(app._drag_target_panel)

    def test_invalid_hover_clears_highlight_and_cached_destination(self):
        app, local, server = self.app()
        local.set_external_drop_highlight_at = Mock()
        app.drag_start(server)
        app._drop_target.return_value = local, local.current_path, (100, 200)
        app.drag_motion(server, 100, 200)
        clears = local.clear_external_drop_highlight.call_count
        app._drop_target.return_value = None, None, None
        self.assertFalse(app.drag_motion(server, 300, 200))
        self.assertEqual(local.clear_external_drop_highlight.call_count, clears + 1)
        self.assertIsNone(app._drag_target_panel)
        self.assertIsNone(app._drag_target_destination)

    def test_reconnect_during_drag_cannot_target_a_different_server(self):
        app, local, server = self.app()
        app._connection_generation = 1
        app.drag_start(server)
        app._connection_generation = 2
        app._drop_target.return_value = local, local.current_path, (100, 200)
        self.assertFalse(app.drag_motion(server, 100, 200))
        app.drop(server, 100, 200, True)
        self.assert_no_transfer(app)

    def test_disconnected_source_server_cannot_offer_a_download(self):
        app, local, server = self.app()
        app.server.connected = False
        self.assertFalse(app._drop_is_valid(server, local,
                         [PurePosixPath('/work/a.inp')], local.current_path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
