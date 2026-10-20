"""Regression for Windows WSAENOTSOCK noise during normal WinUx shutdown."""

from __future__ import annotations

import socket
import threading
import time
import unittest

from WinUx.server_model import SSHServerModel


class _Socket:
    def __init__(self, events):
        self.events = events
        self.shutdown_calls = []
        self.closed = False

    def shutdown(self, how):
        self.shutdown_calls.append(how)
        self.events.append("socket.shutdown")

    def close(self):
        self.closed = True
        self.events.append("socket.close")


class _Transport:
    def __init__(self, sock, allow_exit):
        self.sock = sock
        self._allow_exit = allow_exit
        self.join_calls = []

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_calls.append(timeout)
        self.sock.events.append("transport.join")
        self._allow_exit.wait(timeout)


class _Resource:
    def __init__(self, events, name):
        self.events = events
        self.name = name
        self.closed = threading.Event()

    def close(self):
        self.events.append(self.name + ".close")
        self.closed.set()


class _Client(_Resource):
    def __init__(self, events, transport):
        super().__init__(events, "client")
        self.transport = transport

    def get_transport(self):
        return self.transport

    def close(self):
        super().close()
        # Model the final close normally owned by paramiko.SSHClient/Transport.
        self.transport.sock.close()


class SSHShutdownSocketRegressionTests(unittest.TestCase):
    def test_shutdown_wakes_transport_without_closing_socket_under_recv(self):
        events = []
        allow_exit = threading.Event()
        sock = _Socket(events)
        transport = _Transport(sock, allow_exit)
        server = SSHServerModel()
        server.shell = _Resource(events, "shell")
        server.sftp = _Resource(events, "sftp")
        server.client = _Client(events, transport)

        started = time.monotonic()
        server.request_shutdown()
        elapsed = time.monotonic() - started

        # UI shutdown remains non-blocking and only half-closes the socket on
        # the calling thread.  Keeping the WinSock handle valid lets Paramiko's
        # recv() observe EOF instead of WinError 10038 (WSAENOTSOCK).
        self.assertLess(elapsed, 0.25)
        self.assertEqual(sock.shutdown_calls, [socket.SHUT_RDWR])
        self.assertFalse(sock.closed)
        self.assertEqual(events[:2], ["socket.shutdown", "transport.join"])

        allow_exit.set()
        self.assertTrue(server.client is None)
        deadline = time.monotonic() + 1.0
        while not sock.closed and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(sock.closed)
        self.assertIn("client.close", events)
        self.assertLess(events.index("transport.join"), events.index("socket.close"))


if __name__ == "__main__":
    unittest.main()
