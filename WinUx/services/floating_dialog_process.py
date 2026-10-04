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
    connection = socket.create_connection(("127.0.0.1", int(os.environ.pop("WINUX_FLOAT_DIALOG_PORT"))), timeout=25)
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    connection.settimeout(None)
    try:
        connection.sendall(encode_message({"event": "hello", "token": os.environ.pop("WINUX_FLOAT_DIALOG_TOKEN")}))
        messages = read_messages(connection)
        prepared = None
        if os.environ.pop("WINUX_FLOAT_DIALOG_PREWARM", "") == "1":
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
        FloatingDialogRuntime(connection, messages, initial, prepared=prepared).run()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        try:
            connection.sendall(encode_message({"event": "error", "message": str(exc)}))
        except OSError:
            pass
        return 1
    finally:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
