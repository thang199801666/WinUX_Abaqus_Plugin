from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
SPLITTER_LAYOUT = ROOT / "WinUx" / "ui" / "splitter_layout.py"
VIEW_RUNTIME_SOURCE = VIEW.read_text(encoding="utf-8") + "\n" + SPLITTER_LAYOUT.read_text(encoding="utf-8")
HOST = ROOT / "WinUx" / "platform" / "native_dialog_host.py"
EXPLORER = ROOT / "WinUx" / "components" / "explorer_list_view.py"


class ModalInputGateRegressionTests(unittest.TestCase):
    def test_splitter_uses_native_owner_enabled_state(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("def _native_owner_accepts_input", source)
        self.assertIn("IsWindowEnabled", source)
        self.assertIn("def _splitter_input_blocked", source)
        self.assertIn("pointer_input_is_blocked", source)
        self.assertIn("or pointer_input_is_blocked(owner)", source)
        self.assertIn("self._horizontal_splitter_owner = object()", source)
        self.assertIn("self._plot_splitter_owner = object()", source)

    def test_splitter_hover_and_cursor_are_suppressed_behind_foreground_surface(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertGreaterEqual(source.count("_splitter_input_blocked("), 10)
        self.assertIn("self._horizontal_splitter_owner", source)
        self.assertIn("self._plot_splitter_owner", source)
        self.assertIn("hovered = (not blocked", source)


    def test_native_dialogs_block_background_dpg_input(self):
        gate = (ROOT / "WinUx" / "components" / "interaction_gate.py").read_text(encoding="utf-8")
        view = VIEW.read_text(encoding="utf-8")
        host = HOST.read_text(encoding="utf-8")

        self.assertIn("def register_native_pointer_surface", gate)
        self.assertIn("def acquire_native_modal_input", gate)
        self.assertIn("def native_background_input_blocked", gate)
        self.assertIn("_native_modal_release_pending", gate)
        self.assertIn("GetWindowRect", gate)
        self.assertIn("GetAsyncKeyState", gate)

        self.assertIn("native_background_input_blocked", view)
        self.assertIn("self._drain_dpg_callbacks(discard=True)", view)
        self.assertIn("release_pointer_input()", view)

        self.assertIn("self._register_native_input_surface(window)", host)
        self.assertIn("self._set_native_modal_input(True)", host)
        self.assertIn("self._set_native_modal_input(False)", host)

    def test_native_modal_gate_is_acquired_before_show_is_queued(self):
        host = HOST.read_text(encoding="utf-8")
        show_start = host.index("    def show(self):")
        show_end = host.index("    def hide(self):", show_start)
        show = host[show_start:show_end]
        self.assertLess(
            show.index("self._set_native_modal_input(True)"),
            show.index('self.post("show")'),
        )

    def test_no_cross_thread_native_modal_counter(self):
        host = HOST.read_text(encoding="utf-8")
        explorer = EXPLORER.read_text(encoding="utf-8")
        self.assertNotIn("_NATIVE_MODAL_COUNT", host)
        self.assertNotIn("is_native_modal_active", host)
        self.assertNotIn("is_native_modal_active", explorer)


if __name__ == "__main__":
    unittest.main()
