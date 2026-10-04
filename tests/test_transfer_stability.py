from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "WinUx" / "services" / "remote_transfer.py"


class TransferStabilityTests(unittest.TestCase):
    def test_stream_transfers_have_stall_and_exit_deadlines(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn("TRANSFER_STALL_TIMEOUT_SECONDS", source)
        self.assertIn("STREAM_EXIT_TIMEOUT_SECONDS", source)
        self.assertIn("SFTP_REQUEST_TIMEOUT_SECONDS", source)
        self.assertIn("Upload stalled for more than", source)
        self.assertIn("Download stalled for more than", source)

    def test_server_navigation_never_lists_directory_on_ui_path(self):
        source = (ROOT / "WinUx" / "controllers" / "navigation.py").read_text(encoding="utf-8")
        block = source[source.index("    def open("):source.index("    def local_loaded(")]
        self.assertIn('"server-navigation", worker, key="server-navigation"', block)
        self.assertIn('replace=True', block)
        self.assertIn("self.server.list_directory(path)", block)
        self.assertIn("self.view.after", block)
        # The list call is nested in worker(), not executed before the thread is started.
        self.assertLess(block.index("def worker():"), block.index("self.server.list_directory(path)"))


    def test_regular_upload_download_use_dedicated_channels_on_single_transport(self):
        source = TRANSFER.read_text(encoding="utf-8")
        facade = (ROOT / "WinUx" / "server_model.py").read_text(encoding="utf-8")
        self.assertIn("RemoteTransferMixin", facade)
        upload = source[source.index("    def upload("):source.index("    def _upload_dir", source.index("    def upload("))]
        download = source[source.index("    def download("):source.index("    def _download_dir", source.index("    def download("))]
        self.assertIn("with self._auxiliary_session() as (transfer_client, transfer_sftp)", upload)
        self.assertIn("with self._auxiliary_session() as (transfer_client, transfer_sftp)", download)
        self.assertNotIn("@_serialized_wire_call\n    def upload", source)
        self.assertNotIn("@_serialized_wire_call\n    def download", source)

    def test_shutdown_breaks_the_single_transport_socket(self):
        source = (ROOT / "WinUx" / "server_model.py").read_text(encoding="utf-8")
        self.assertIn("break_client_socket(client)", source)
        self.assertNotIn("self._auxiliary_clients", source)
        self.assertIn("one transport", source)

    def test_reconnect_refresh_reuses_async_navigation(self):
        facade = (ROOT / "WinUx" / "controller.py").read_text(encoding="utf-8")
        source = (ROOT / "WinUx" / "controllers" / "connection.py").read_text(encoding="utf-8")
        start = source.index("    def restored")
        block = source[start:]
        self.assertIn("self.app.open_path(self.view.right, folder, False)", block)
        self.assertNotIn("self.server.list_directory(folder)", block)
        self.assertIn("return self._connection_controller().restored(generation)", facade)


if __name__ == "__main__":
    unittest.main()
