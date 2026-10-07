"""Abaqus Python entry point for process-isolated WinUx dialog runtimes."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from run_winux import _configure_bundled_dependencies
_configure_bundled_dependencies(str(ROOT))

from WinUx.dialogs.floating_runtime import FloatingDialogRuntime, PreparedViewport
from WinUx.services.floating_protocol import encode_message, read_messages


def main():
    port = int(os.environ.pop("WINUX_FLOAT_DIALOG_PORT"))
    token = os.environ.pop("WINUX_FLOAT_DIALOG_TOKEN")
    prewarm_requested = os.environ.pop("WINUX_FLOAT_DIALOG_PREWARM", "") == "1"
    connection = None
    try:
        try:
            connection = socket.create_connection(("127.0.0.1", port), timeout=25)
        except OSError:
            # A prewarm worker can be retired while Abaqus' Python wrapper is
            # still starting. In that race the parent listener has already
            # closed; this is normal cleanup, not a dialog crash worth logging.
            if prewarm_requested:
                return 0
            raise
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.settimeout(None)
        connection.sendall(encode_message({"event": "hello", "token": token}))
        messages = read_messages(connection)
        prepared = None
        if prewarm_requested:
            prepared = PreparedViewport(connection, messages)
            initial = prepared.wait_for_init()
            if initial is None:
                return 0
        else:
            initial = next(messages)
        if initial.get("command") != "init":
            raise ValueError("Floating dialog requires an init handshake.")
        # All WinUx floating UI is Dear ImGui / Dear PyGui.  Individual
        # controls may emulate Qt/Fusion geometry and behavior, but no Tk/Qt
        # runtime is selected for any dialog kind.
        runtime = FloatingDialogRuntime(connection, messages, initial, prepared=prepared)
        runtime.run()
    except Exception as exc:
        trace_text = traceback.format_exc()
        try:
            sys.stderr.write(trace_text)
            sys.stderr.flush()
        except Exception:
            pass
        try:
            connection.sendall(encode_message({
                "event": "error",
                "message": str(exc),
                "traceback": trace_text,
                "stage": str(getattr(locals().get("runtime", None), "stage", "startup") or "startup"),
            }))
        except OSError:
            pass
        return 1
    finally:
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
