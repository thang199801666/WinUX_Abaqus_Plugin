"""Open tools from the main viewport after the initial prewarm has gone idle."""
import os
import time
import unittest
from unittest.mock import Mock

from WinUx.controllers import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx import dialogs
from WinUx.plotdigitizer.integration import open_plot_digitizer


@unittest.skipUnless(os.name == "nt", "Requires native Windows viewports")
class InitialWarmDialogTests(unittest.TestCase):
    def test_initial_idle_host_opens_reference_and_digitizer(self):
        self.run_dialog_scenario(stall_first_host=False)

    def test_silent_warm_host_is_replaced_without_error_popup(self):
        self.run_dialog_scenario(stall_first_host=True)

    def run_dialog_scenario(self, stall_first_host):
        callbacks = {name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS}
        view = WinUXView(callbacks)
        errors, completed, pending = [], [], []
        view.show_error = lambda *args: errors.append(AssertionError(str(args)))
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])

        def scenario():
            pool = view._dialog_host_pool
            yield "initial-prewarm", lambda: any(worker.ready.is_set() for worker in pool._workers)
            # Unlike a cold first click, leave the graphics worker in its native
            # idle dispatcher before sending the first init command.
            idle_until = time.monotonic() + 2
            yield "idle-host", lambda: time.monotonic() >= idle_until
            if stall_first_host:
                def silent_events(stream):
                    # Drop acknowledgements from a real worker. It remains
                    # cloaked awaiting publish_commit, and the real socket's
                    # warm-start deadline must replace it without a popup.
                    for _message in stream:
                        pass
                    yield
                for worker in pool._workers:
                    if worker.ready.is_set():
                        worker.messages = silent_events(worker.messages)
                        break
            for cycle in range(3):
                reference = dialogs.ReferenceChartDialog(view, [], lambda *args: None)
                yield "reference-ready", lambda: reference._ready
                if stall_first_host and cycle == 0:
                    self.assertEqual(reference._ipc_retry_count, 1)
                    self.assertFalse(reference._from_prewarm)
                    self.assertLess(reference._open_elapsed_ms, reference.STARTUP_TIMEOUT * 1000)
                reference.destroy()
                yield "reference-recycled", lambda: reference._host_returned
                digitizer = open_plot_digitizer(view)
                yield "digitizer-ready", lambda: digitizer._ready
                digitizer.destroy()
                yield "digitizer-recycled", lambda: digitizer._host_returned
                completed.append(cycle)

        steps = scenario()

        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    name, predicate, deadline = pending[0]
                    if not predicate():
                        if time.monotonic() >= deadline:
                            raise AssertionError("Dialog startup stalled at " + name)
                        view.after(20, advance)
                        return
                    pending.clear()
                name, predicate = next(steps)
                print("Initial warm dialog: " + name, flush=True)
                pending.append((name, predicate, time.monotonic() + 30))
                view.after(20, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()

        view.after(100, advance)
        view.run()
        if errors:
            raise errors[0]
        self.assertEqual(completed, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
