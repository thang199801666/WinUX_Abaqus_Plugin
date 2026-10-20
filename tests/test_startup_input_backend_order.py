"""Guard native context ordering and smoke-test the real controller startup."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StartupInputBackendTests(unittest.TestCase):
    def test_native_input_bridge_is_installed_after_context_before_viewport_setup(self):
        tree = ast.parse((ROOT / "WinUx" / "view.py").read_text(encoding="utf-8"))
        view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WinUXView")
        constructor = next(node for node in view.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")

        def lines(name):
            return sorted(node.lineno for node in ast.walk(constructor)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                          and node.func.attr == name)

        self.assertEqual(len(lines("installInputBackend")), 1)
        self.assertLess(lines("create_context")[0], lines("installInputBackend")[0])
        self.assertLess(lines("configure_app")[0], lines("installInputBackend")[0])
        self.assertLess(lines("installInputBackend")[0], lines("setup_dearpygui")[0])

    @unittest.skipUnless(os.name == "nt", "Requires native Windows GUI")
    def test_full_controller_boots_with_live_input_registry_in_fresh_process(self):
        # Use the current Abaqus/SMAPython interpreter in isolation: a native
        # access violation must fail this test, not terminate the test runner.
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--smoke-child"],
                                cwd=str(ROOT), capture_output=True, text=True,
                                errors="replace", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WINUX_STARTUP_INPUT_SMOKE_OK", result.stdout)


def startup_smoke_child():
    import ctypes
    from ctypes import wintypes
    from unittest.mock import patch
    import WinUx
    import dearpygui.dearpygui as dpg
    from DearUIQt.qt import QApplication
    from WinUx.bootstrap.application import run
    from WinUx.controller import WinUXController

    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    contexts, installs, observations, errors, apps = [], [], [], [], []
    create_context = dpg.create_context
    install_backend = QApplication.installInputBackend

    def create():
        result = create_context()
        contexts.append(True)
        return result

    def install(application, backend, *args, **kwargs):
        assert contexts, "Native input bridge ran before Dear PyGui context creation"
        result = install_backend(application, backend, *args, **kwargs)
        assert result, "Input backend could not allocate its native registry"
        installs.append(True)
        return result

    def factory():
        app = WinUXController()
        apps.append(app)

        def observe():
            try:
                hwnd = app.view._find_main_viewport_hwnd()
                assert hwnd and user32.IsWindowVisible(hwnd), "Main viewport was not visible"
                application = app.view._qapplication
                registry = application._input_handler_registry
                assert registry and dpg.does_item_exist(registry), "Input registry missing"
                assert application._pointer_bridge_installed, "Pointer bridge was not installed"
                observations.append(True)
            except Exception as exc:
                errors.append(exc)
            finally:
                app.view.request_shutdown()

        app.view.after_render(observe)
        app.view.after(6000, app.view.request_shutdown)
        return app

    # Exercise real preferences/controller/view/bootstrap, but do not connect
    # SSH, restore/execute scheduled jobs, enumerate the saved user folder, or
    # clean the user's clipboard cache during a startup-only smoke test.
    try:
        with patch.object(dpg, "create_context", side_effect=create), \
                patch.object(QApplication, "installInputBackend", install), \
                patch.object(WinUXController, "_auto_login_from_preferences"), \
                patch.object(WinUXController, "_start_background_services"), \
                patch.object(WinUXController, "_load_initial_local_async"), \
                patch.object(WinUXController, "_cleanup_old_clipboard_cache"):
            run(factory)
    finally:
        for app in apps:
            for manager in (app._background_tasks, app._transfer_tasks, app._analysis_tasks):
                manager.close(cancel_pending=True)
            app.server.request_shutdown()
    if errors:
        raise errors[0]
    assert contexts and installs and observations, "Startup did not reach a rendered main viewport"
    print("WINUX_STARTUP_INPUT_SMOKE_OK", flush=True)


if __name__ == "__main__":
    if "--smoke-child" in sys.argv:
        startup_smoke_child()
    else:
        unittest.main()
