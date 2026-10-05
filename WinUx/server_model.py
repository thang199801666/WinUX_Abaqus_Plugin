from __future__ import annotations

import json
import re
import socket
import threading
from contextlib import contextmanager
from collections import deque
from pathlib import PurePosixPath

from .runtime import BoundedTextBuffer
from .services.server_text import RemoteTextConflictError, ServerTextMixin
from .services.remote_odb import RemoteODBMixin
from .services.remote_transfer import RemoteTransferMixin
from .services.remote_filesystem import RemoteFilesystemMixin
from .services.remote_jobs import RemoteJobsMixin
from .services.ssh_serialization import _serialized_wire_call


_PARAMIKO = None
_PARAMIKO_IMPORT_ERROR = None
_PARAMIKO_IMPORT_ATTEMPTED = False


def prepare_ssh_runtime():
    """Import Paramiko before GUI toolkits create thread-affine objects.

    Importing Paramiko for the first time allocates enough objects to trigger
    Python's cyclic garbage collector. If that first import happens in the SSH
    login worker, GC may finalize a Tcl object previously created on the main
    thread and abort the process with ``Tcl_AsyncDelete``. The controller calls
    this function on the main thread before constructing the view.
    """
    global _PARAMIKO, _PARAMIKO_IMPORT_ERROR, _PARAMIKO_IMPORT_ATTEMPTED
    if _PARAMIKO_IMPORT_ATTEMPTED:
        return _PARAMIKO
    _PARAMIKO_IMPORT_ATTEMPTED = True
    try:
        import paramiko
    except Exception as exc:
        _PARAMIKO_IMPORT_ERROR = str(exc)
        _PARAMIKO = None
    else:
        # Every SFTP read/write block is a separate protocol request. The
        # larger block size materially improves upload throughput while staying
        # below the request size accepted by current OpenSSH servers.
        try:
            paramiko.SFTPFile.MAX_REQUEST_SIZE = (
                SSHServerModel.SFTP_REQUEST_SIZE)
        except (AttributeError, NameError):
            pass
        _PARAMIKO = paramiko
        _PARAMIKO_IMPORT_ERROR = None
    return _PARAMIKO


class _SharedTransportClient:
    """Small SSHClient-compatible view over WinUx's single Transport.

    Long-running services still receive a client-like object, but opening an
    exec channel is multiplexed over the already-authenticated control
    transport.  No TCP socket, SSH handshake or authentication is created.
    """

    def __init__(self, model, transport):
        self._model = model
        self._transport = transport

    def get_transport(self):
        return self._transport

    def exec_command(self, command, bufsize=-1, timeout=None, get_pty=False,
                     environment=None):
        channel = self._model._open_transport_session(self._transport)
        if timeout is not None:
            channel.settimeout(timeout)
        if get_pty:
            channel.get_pty()
        if environment:
            try:
                channel.update_environment(environment)
            except AttributeError:
                pass
        channel.exec_command(command)
        stdin = channel.makefile_stdin("wb", bufsize)
        stdout = channel.makefile("rb", bufsize)
        stderr = channel.makefile_stderr("rb", bufsize)
        return stdin, stdout, stderr

    def close(self):
        # Ownership belongs to SSHServerModel. Closing a service-local view
        # must never tear down the application's one authenticated session.
        return None




class SSHServerModel(RemoteJobsMixin, RemoteFilesystemMixin, RemoteODBMixin, RemoteTransferMixin, ServerTextMixin):
    """SSH/SFTP connection and read-only server directory browsing."""

    MAX_SHELL_TRANSCRIPT_CHARS = 1_000_000
    TEXT_EDITOR_MAX_BYTES = 8 * 1024 * 1024
    TEXT_EDITOR_PROBE_SIZE = 64 * 1024
    TEXT_EDITOR_READ_CHUNK_SIZE = 1024 * 1024

    ODB_SNAPSHOT_RETRIES = 3
    ODB_CHECK_TIMEOUT_SECONDS = 600.0
    ABAQUS_PROBE_TIMEOUT_SECONDS = 45.0
    ABAQUS_FALLBACK_COMMANDS = tuple(
        ["abq{}".format(year) for year in range(2026, 2017, -1)]
        + ["abaqus"]
    )

    # Hot Download uses a continuous SSH stdout stream instead of SFTP's
    # request/response loop. These settings affect Hot Download only; normal
    # upload/download behavior and tuning remain unchanged.
    HOT_DOWNLOAD_WINDOW_SIZE = 128 * 1024 * 1024
    HOT_DOWNLOAD_PACKET_SIZE = 1024 * 1024
    HOT_DOWNLOAD_READ_SIZE = 8 * 1024 * 1024
    HOT_DOWNLOAD_CHANNEL_TIMEOUT = 2.0
    # Prevent firewalls/NAT devices from expiring an otherwise idle SSH
    # session. Paramiko sends an SSH-level keepalive request at this interval.
    SSH_KEEPALIVE_INTERVAL = 30
    # WinUx deliberately owns exactly one authenticated SSH transport per
    # login. Plot/ODB/transfer work is multiplexed as independent SSH channels
    # on that transport, avoiding extra TCP handshakes and sshd login bursts.
    # /var/tmp survives normal Linux reboots, unlike /tmp, and is still
    # suitable for shared temporary application state.
    SCHEDULE_FILE_NAME = ".winux-schedules.json"

    def __init__(self):
        self.client = None
        self.sftp = None
        self.home = PurePosixPath("/")
        self.host = ""
        self._port = 22
        self.username = ""
        self._password = None
        self.shell = None
        self._shell_output = BoundedTextBuffer(
            self.MAX_SHELL_TRANSCRIPT_CHARS)
        # Keep a second, display-only transcript. Internal shell housekeeping
        # (for example synchronising the interactive cwd with Server Files) is
        # filtered before it reaches the UI, while the raw PTY transcript stays
        # untouched. This avoids rewriting a transcript that the console may be
        # selecting/rendering at the same time.
        self._shell_visible_output = BoundedTextBuffer(
            self.MAX_SHELL_TRANSCRIPT_CHARS)
        # Each hidden echo entry is ``(command, replace_prompt)``.  Keeping
        # prompt replacement on the individual command is important because
        # Server Files can queue several cwd changes before the PTY has echoed
        # the first one.  A single global boolean loses that association and
        # eventually leaves stale/missing prompts.
        self._shell_hidden_echoes = deque()
        self._shell_hidden_partial = ""
        self._shell_directory = None
        self._shell_condition = threading.Condition()
        self._shell_send_lock = threading.Lock()
        self._shell_stop = threading.Event()
        self._remote_tar_supported = None
        self._connection_lock = threading.RLock()
        self._credentials_lock = threading.Lock()
        # Paramiko supports multiple channels on one Transport. Channel creation
        # is serialized because older bundled Paramiko/OpenSSL combinations
        # have proved fragile when several worker threads open channels at the
        # exact same instant. Once opened, channels can run concurrently.
        self._channel_open_lock = threading.RLock()
        # Remember the last release that successfully opened each remote ODB.
        # The entry is only a priority hint: every new analysis session probes
        # it again before use so a recreated ODB can safely change release.
        self._odb_abaqus_command_cache = {}
        self._odb_abaqus_command_cache_lock = threading.RLock()

    def request_shutdown(self):
        """Abort transport I/O without waiting for ``_connection_lock``.

        Every normal SSH/SFTP operation owns ``_connection_lock`` for its full
        duration. Calling ``close()`` from the render thread while a transfer is
        active therefore waits for that transfer (or a network timeout) and
        makes the WinUX window appear frozen. Application shutdown instead
        detaches the live objects, closes the underlying socket immediately to
        wake blocked Paramiko calls, and lets graceful ``close()`` methods run
        on a daemon cleanup thread.
        """
        self._remote_tar_supported = None
        self._shell_stop.set()

        # Detach first so new background work observes a disconnected model.
        # Existing workers retain their local channel/SFTP objects and unwind
        # naturally once the transport socket is closed below.
        shell, self.shell = self.shell, None
        sftp, self.sftp = self.sftp, None
        client, self.client = self.client, None
        auxiliary_clients = ()
        # Shutdown is a one-way operation. Never wait for credential mutation
        # (for example a concurrent reconnect/login) on the UI close path.
        acquired_credentials = False
        try:
            acquired_credentials = self._credentials_lock.acquire(False)
            if acquired_credentials:
                self._password = None
        except Exception:
            pass
        finally:
            if acquired_credentials:
                try:
                    self._credentials_lock.release()
                except Exception:
                    pass

        def break_client_socket(value):
            if value is None:
                return
            try:
                transport = value.get_transport()
            except Exception:
                transport = None
            # Do not call Transport.close() here: Paramiko's close path may
            # join its transport thread. Closing the raw socket is sufficient
            # to wake blocked recv/send on every channel of the one transport.
            raw_socket = getattr(transport, "sock", None) if transport else None
            if raw_socket is not None:
                try:
                    raw_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    raw_socket.close()
                except Exception:
                    pass

        break_client_socket(client)

        def cleanup():
            for resource in (shell, sftp, client) + auxiliary_clients:
                if resource is None:
                    continue
                try:
                    resource.close()
                except Exception:
                    pass

        threading.Thread(
            target=cleanup,
            name="winux-ssh-shutdown",
            daemon=True,
        ).start()

    @staticmethod
    def _transport_usable(transport):
        if transport is None:
            return False
        try:
            if not transport.is_active():
                return False
            authenticated = getattr(transport, "is_authenticated", None)
            if callable(authenticated) and not authenticated():
                return False
        except Exception:
            return False
        return True

    @staticmethod
    def _sftp_usable(sftp):
        if sftp is None:
            return False
        get_channel = getattr(sftp, "get_channel", None)
        if not callable(get_channel):
            # Compatibility for SFTP-like wrappers used by integrations/tests.
            return True
        try:
            channel = get_channel()
        except Exception:
            return False
        if channel is None or bool(getattr(channel, "closed", False)):
            return False
        if hasattr(channel, "active") and not bool(channel.active):
            return False
        return True

    @staticmethod
    def _shell_usable(shell):
        if shell is None:
            return False
        try:
            if bool(getattr(shell, "closed", False)):
                return False
            if hasattr(shell, "active") and not bool(shell.active):
                return False
        except Exception:
            return False
        return True

    @property
    def connected(self):
        """Return whether the single control session is fully usable."""
        if self.client is None:
            return False
        try:
            transport = self.client.get_transport()
        except Exception:
            return False
        return (self._transport_usable(transport)
                and self._sftp_usable(self.sftp)
                and self._shell_usable(self.shell))


    @staticmethod
    def _ssh_auth_discovery_options(password):
        """Avoid unnecessary key/agent attempts when a password is supplied.

        Repeated auxiliary/reconnect sessions used to try agent keys and local
        key files *before* password authentication.  On servers with a small
        ``MaxAuthTries`` this can terminate a perfectly valid login and also
        creates more authentication work than necessary.  Key/agent discovery
        remains enabled when no password was supplied.
        """
        has_password = password is not None and str(password) != ""
        return {
            "look_for_keys": not has_password,
            "allow_agent": not has_password,
        }

    @_serialized_wire_call
    def connect(self, host, port, username, password):
        paramiko = prepare_ssh_runtime()
        if paramiko is None:
            raise RuntimeError(
                "Missing or incompatible SSH library: {}. Copy Paramiko and "
                "all of its dependencies into the plug-in vendor folder."
                .format(_PARAMIKO_IMPORT_ERROR or "unknown import error"))
        with self._connection_lock:
            # A reconnect may fail before authentication (for example errno 111).
            # Preserve the previous credentials across that failed attempt so
            # the next retry is still able to authenticate.
            self.close(clear_credentials=False)
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            try:
                auth_options = self._ssh_auth_discovery_options(password)
                client.connect(hostname=host, port=int(port), username=username,
                               password=password, timeout=12, auth_timeout=12,
                               banner_timeout=12, compress=False,
                               **auth_options)
                transport = client.get_transport()
                self._tune_transport(transport)
                transport.set_keepalive(self.SSH_KEEPALIVE_INTERVAL)
                sftp = self._open_sftp_channel(transport, paramiko)
                home = sftp.normalize(".")
            except Exception:
                client.close()
                raise
            self.client, self.sftp = client, sftp
            self.home = PurePosixPath(home)
            self.host = host
            self._port = int(port)
            self.username = username
            with self._credentials_lock:
                self._password = password
            self._open_shell()
            return self.home

    @_serialized_wire_call
    def reconnect(self):
        """Repair the current session first; create a new login only if dead.

        A broken browser SFTP channel does not justify destroying a healthy SSH
        transport (and every Plot/transfer channel multiplexed on it). Only a
        genuinely dead/unauthenticated Transport causes a new TCP/SSH login.
        """
        if not self.host or not self.username:
            raise RuntimeError("No previous SSH login is available")

        transport = None
        try:
            transport = self.client.get_transport() if self.client else None
        except Exception:
            transport = None

        if self._transport_usable(transport):
            try:
                if not self._sftp_usable(self.sftp):
                    stale = self.sftp
                    self.sftp = self._open_shared_sftp_channel(transport)
                    try:
                        if stale is not None:
                            stale.close()
                    except Exception:
                        pass
                if not self._shell_usable(self.shell):
                    self._open_shell()
                try:
                    home = self.sftp.normalize(".")
                    self.home = PurePosixPath(home)
                except Exception:
                    pass
                return self.home
            except Exception:
                # If channel repair itself proves the transport unusable, fall
                # through to one clean full reconnect below.
                if self._transport_usable(transport):
                    raise

        with self._credentials_lock:
            password = self._password
        return self.connect(self.host, self._port, self.username, password)

    @_serialized_wire_call
    def read_schedule_manifest(self):
        """Read the shared JSON schedule manifest from the Linux server."""
        import json
        try:
            path = self.home / self.SCHEDULE_FILE_NAME
            with self.sftp.open(str(path), "rb") as stream:
                text = stream.read().decode("utf-8", "replace")
            value = json.loads(text or "[]")
            return value if isinstance(value, list) else []
        except OSError as exc:
            if getattr(exc, "errno", None) == 2:
                return []
            raise RuntimeError("Could not read schedule manifest: {}".format(exc))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Could not read schedule manifest: {}".format(exc))

    @_serialized_wire_call
    def write_schedule_manifest(self, schedules):
        """Atomically publish the shared schedule manifest on Linux."""
        import json
        path = self.home / self.SCHEDULE_FILE_NAME
        payload = json.dumps(schedules, ensure_ascii=True, indent=2)
        with self.sftp.open(str(path), "wb") as stream:
            stream.write(payload.encode("utf-8"))
        with self.sftp.open(str(path), "rb") as stream:
            if stream.read().decode("utf-8", "replace") != payload:
                raise RuntimeError("Schedule manifest verification failed")

    @_serialized_wire_call
    def ensure_schedule_storage(self):
        """Create the user-writable shared schedule directory."""
        probe = self.home / ".winux-write-test-{}".format(uuid.uuid4().hex)
        with self.sftp.open(str(probe), "wb") as stream:
            stream.write(b"ok")
        self.sftp.remove(str(probe))

    @classmethod
    def _tune_transport(cls, transport):
        """Increase operating-system socket buffers for the SSH stream."""
        if transport is None:
            raise RuntimeError("SSH transport is unavailable")
        sock = getattr(transport, "sock", None)
        if sock is None:
            return
        try:
            import socket
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_SNDBUF, cls.SOCKET_BUFFER_SIZE)
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, cls.SOCKET_BUFFER_SIZE)
        except (AttributeError, OSError):
            # The channel window/request tuning below still applies when the
            # operating system refuses a custom socket buffer size.
            pass

    @classmethod
    def _open_sftp_channel(cls, transport, paramiko=None):
        """Open an SFTP channel configured for high-throughput transfers."""
        paramiko = paramiko or prepare_ssh_runtime()
        if paramiko is None:
            raise RuntimeError("Paramiko is unavailable")
        try:
            client = paramiko.SFTPClient.from_transport(
                transport,
                window_size=cls.SFTP_WINDOW_SIZE,
                max_packet_size=cls.SFTP_PACKET_SIZE,
            )
        except TypeError:
            # Compatibility fallback for old Paramiko releases.
            client = paramiko.SFTPClient.from_transport(transport)
        try:
            client.get_channel().settimeout(cls.SFTP_REQUEST_TIMEOUT_SECONDS)
        except Exception:
            pass
        return client

    def _active_transport(self):
        """Return the one authenticated transport or raise a clean error."""
        client = self.client
        if client is None:
            raise RuntimeError("Not connected to an SSH server")
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")
        authenticated = getattr(transport, "is_authenticated", None)
        if callable(authenticated) and not authenticated():
            raise RuntimeError("SSH transport is not authenticated")
        return transport

    def _open_transport_session(self, transport=None, window_size=None,
                                max_packet_size=None):
        """Open one channel on the existing transport, never a new login."""
        transport = transport or self._active_transport()
        with self._channel_open_lock:
            try:
                if window_size is not None or max_packet_size is not None:
                    return transport.open_session(
                        window_size=window_size,
                        max_packet_size=max_packet_size,
                    )
            except TypeError:
                pass
            return transport.open_session()

    def _open_shared_sftp_channel(self, transport=None):
        transport = transport or self._active_transport()
        with self._channel_open_lock:
            return self._open_sftp_channel(transport)

    def _exec_command_streams(self, command, timeout=None):
        """Open one exec channel through the serialized channel gate."""
        client = _SharedTransportClient(self, self._active_transport())
        return client.exec_command(command, timeout=timeout)

    @contextmanager
    def _auxiliary_session(self):
        """Create service-local channels on WinUx's single SSH transport.

        The historical method name is retained to avoid touching every caller.
        It no longer creates an auxiliary SSHClient/TCP connection.  The
        returned client-like object opens exec channels on the already
        authenticated Transport, while the dedicated SFTP channel isolates
        long-running file work from the browser SFTP channel.
        """
        transport = self._active_transport()
        sftp = self._open_shared_sftp_channel(transport)
        client = _SharedTransportClient(self, transport)
        try:
            yield client, sftp
        finally:
            try:
                sftp.close()
            except Exception:
                pass

    @staticmethod
    def _exec_client(client, command, timeout=None):
        """Execute *command* on a specific SSH client with a hard timeout."""
        timeout = (SSHServerModel.ODB_CHECK_TIMEOUT_SECONDS
                   if timeout is None else max(1.0, float(timeout)))
        try:
            _stdin, stdout, stderr = client.exec_command(
                command, timeout=timeout)
            try:
                stdout.channel.settimeout(timeout)
            except Exception:
                pass
            output = stdout.read().decode("utf-8", "replace").strip()
            error = stderr.read().decode("utf-8", "replace").strip()
            status = stdout.channel.recv_exit_status()
            return status, output, error
        except socket.timeout:
            raise RuntimeError(
                "Remote command timed out after {:.0f}s".format(timeout))

    @classmethod
    def _abaqus_candidate_commands(cls, abaqus_commands=None):
        configured = [
            str(value).strip() for value in (abaqus_commands or [])
            if re.match(r"^[A-Za-z0-9._/+:-]+$", str(value).strip())
        ]
        configured.extend(cls.ABAQUS_FALLBACK_COMMANDS)
        unique = []
        seen = set()
        for value in configured:
            if value and value not in seen:
                seen.add(value)
                unique.append(value)
        return unique

    @classmethod
    def _login_shell_command(cls, script):
        """Run one command through the user's Linux login environment.

        Abaqus launchers such as ``abq2026`` are frequently added by
        /etc/profile, ~/.bash_profile, environment modules, or a site wrapper.
        A plain Paramiko exec channel does not necessarily inherit that PATH.
        """
        return "bash -lc {}".format(cls._shell_quote(script))

    @classmethod
    def _resolve_abaqus_executable_on(cls, client, abaqus_commands=None):
        """Return the first *usable* Abaqus Python command in priority order.

        Merely finding a launcher is insufficient: the selected installation
        must also be able to import ``odbAccess``.  The preferred command is
        supplied first by ``AbaqusVersionPreferences`` (abq2026 by default),
        then WinUx falls back through older releases and finally ``abaqus``.
        """
        candidates = cls._abaqus_candidate_commands(abaqus_commands)
        attempted = []
        marker = "__WINUX_ABAQUS_PYTHON_OK__"
        probe_code = (
            "from odbAccess import openOdb; "
            "print(%r)" % marker
        )
        for candidate in candidates:
            probe = "{} python -c {}".format(
                candidate, cls._shell_quote(probe_code))
            command = cls._login_shell_command(probe)
            try:
                status, output, error = cls._exec_client(
                    client, command, timeout=cls.ABAQUS_PROBE_TIMEOUT_SECONDS)
            except Exception as exc:
                attempted.append("{} ({})".format(candidate, exc))
                continue
            if status == 0 and marker in output:
                return candidate
            detail = (error or output or "exit {}".format(status)).strip()
            if detail:
                detail = detail.splitlines()[-1][:120]
                attempted.append("{} ({})".format(candidate, detail))
            else:
                attempted.append(candidate)

        tried = ", ".join(candidates) or "(none)"
        details = "; ".join(attempted[:4])
        message = (
            "No usable Abaqus Python command was found on the server. "
            "Tried: {}. Set the preferred command in Settings > Abaqus "
            "Versions > Default command.".format(tried)
        )
        if details:
            message += " Probe results: {}".format(details)
        raise RuntimeError(message)


    @contextmanager
    def _transfer_sftp(self):
        """Use a dedicated channel so file browsing cannot throttle transfer."""
        if not self.client:
            raise RuntimeError("Not connected to an SSH server")
        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")
        sftp = self._open_shared_sftp_channel(transport)
        try:
            yield sftp
        finally:
            try:
                sftp.close()
            except Exception:
                pass

    def _open_shell(self):
        """Open the shared interactive shell on the one SSH transport."""
        transport = self._active_transport()
        channel = self._open_transport_session(transport)
        channel.get_pty(term="xterm", width=120, height=40)
        channel.invoke_shell()
        stop_event = threading.Event()
        self.shell = channel
        with self._shell_condition:
            self._shell_output.clear()
            self._shell_visible_output.clear()
            self._shell_hidden_echoes.clear()
            self._shell_hidden_partial = ""
            self._shell_directory = None
        self._shell_stop = stop_event

        def reader():
            while not stop_event.is_set():
                try:
                    if channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", "replace")
                        with self._shell_condition:
                            self._shell_output.append(chunk)
                            self._append_visible_shell_chunk_locked(chunk)
                            self._shell_condition.notify_all()
                    elif channel.closed:
                        break
                    else:
                        stop_event.wait(0.04)
                except Exception:
                    break

        threading.Thread(target=reader, name="winux-ssh-shell-reader",
                         daemon=True).start()

    _SHELL_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

    @classmethod
    def _shell_echo_compact(cls, value):
        """Return PTY text suitable for matching an echoed input command.

        Interactive shells may visually wrap a long command at the terminal
        width. Paramiko can then deliver the echo as several physical lines
        (CR/LF plus ANSI cursor sequences), even though the user entered one
        logical command. Matching one line at a time therefore leaks command
        tails such as ``14 studs/Batch-3'`` into the console.
        """
        text = cls._SHELL_ANSI_RE.sub("", str(value))
        return text.replace("\r", "").replace("\n", "")

    @classmethod
    def _shell_echo_matches(cls, value, command):
        logical = cls._shell_echo_compact(value)
        wanted = cls._shell_echo_compact(command)
        return bool(wanted) and wanted in logical

    @classmethod
    def _shell_echo_span(cls, value, command):
        """Return ``(raw_start, raw_end)`` for an echoed logical command.

        CR/LF introduced by terminal wrapping and ANSI control sequences are
        ignored for matching, while raw source offsets are retained.
        """
        text = str(value)
        wanted = cls._shell_echo_compact(command)
        if not wanted:
            return None

        logical = []
        starts = []
        ends = []
        i = 0
        n = len(text)
        while i < n:
            match = cls._SHELL_ANSI_RE.match(text, i)
            if match is not None:
                i = match.end()
                continue
            raw_start = i
            ch = text[i]
            i += 1
            if ch in "\r\n":
                continue
            logical.append(ch)
            starts.append(raw_start)
            ends.append(i)

        compact = "".join(logical)
        pos = compact.find(wanted)
        if pos < 0:
            return None
        last = pos + len(wanted) - 1
        if last >= len(ends):
            return None
        return starts[pos], ends[last]

    @classmethod
    def _shell_echo_end_index(cls, value, command):
        span = cls._shell_echo_span(value, command)
        return None if span is None else span[1]

    @classmethod
    def _shell_echo_partial_start_index(cls, value, commands):
        """Return raw index of a trailing possible hidden-echo fragment.

        Older revisions buffered *all* PTY output while a hidden ``cd`` echo
        was pending.  If another command/job was running, that could hold the
        terminal indefinitely and make folder sync appear to stop after a few
        navigations.  We now retain only the shortest tail that can still grow
        into one of the pending hidden commands; unrelated output is released
        immediately.
        """
        text = str(value)
        logical = []
        starts = []
        i = 0
        n = len(text)
        while i < n:
            match = cls._SHELL_ANSI_RE.match(text, i)
            if match is not None:
                i = match.end()
                continue
            raw_start = i
            ch = text[i]
            i += 1
            if ch in "\r\n":
                continue
            logical.append(ch)
            starts.append(raw_start)

        compact = "".join(logical)
        if not compact:
            return 0 if text else None

        best = 0
        for command in commands:
            wanted = cls._shell_echo_compact(command)
            if not wanted:
                continue
            max_len = min(len(compact), max(0, len(wanted) - 1))
            for length in range(max_len, 0, -1):
                if compact.endswith(wanted[:length]):
                    best = max(best, length)
                    break
        if best <= 0:
            return None
        return starts[len(compact) - best]

    @staticmethod
    def _hidden_echo_parts(entry):
        if isinstance(entry, tuple):
            command = entry[0]
            replace_prompt = bool(entry[1]) if len(entry) > 1 else False
            return command, replace_prompt
        return entry, False

    def _append_visible_shell_chunk_locked(self, chunk):
        if not self._shell_hidden_echoes:
            if self._shell_hidden_partial:
                self._shell_visible_output.append(self._shell_hidden_partial)
                self._shell_hidden_partial = ""
            self._shell_visible_output.append(chunk)
            return

        data = self._shell_hidden_partial + chunk
        self._shell_hidden_partial = ""

        while self._shell_hidden_echoes and data:
            # Search every queued hidden command, not only queue[0].  This lets
            # the stream recover if one PTY echo was lost while a later cwd
            # sync did echo normally.  Commands are still sent in order; any
            # skipped earlier entries are stale by definition once a later one
            # is observed.
            found = None
            for idx, entry in enumerate(self._shell_hidden_echoes):
                command, replace_prompt = self._hidden_echo_parts(entry)
                span = self._shell_echo_span(data, command)
                if span is None:
                    continue
                candidate = (span[0], idx, span[1], replace_prompt)
                if found is None or candidate[:2] < found[:2]:
                    found = candidate

            if found is not None:
                raw_start, idx, raw_end, replace_prompt = found
                prefix = data[:raw_start]
                if prefix:
                    self._shell_visible_output.append(prefix)

                # Discard the matched entry and any older stale entries.
                for _ in range(idx + 1):
                    self._shell_hidden_echoes.popleft()

                if replace_prompt:
                    self._drop_trailing_visible_prompt_locked()

                data = data[raw_end:]
                while data.startswith(("\r", "\n")):
                    data = data[1:]
                continue

            # No complete hidden echo is present.  Release unrelated output
            # immediately and retain only a trailing fragment that could be
            # the beginning of any pending command.  This is what prevents a
            # long-running job or user command from starving cwd updates.
            commands = [self._hidden_echo_parts(e)[0]
                        for e in self._shell_hidden_echoes]
            partial_start = self._shell_echo_partial_start_index(data, commands)
            if partial_start is None:
                self._shell_visible_output.append(data)
                data = ""
            else:
                if partial_start > 0:
                    self._shell_visible_output.append(data[:partial_start])
                self._shell_hidden_partial = data[partial_start:]
                data = ""

        if data:
            self._shell_visible_output.append(data)

    def shell_output(self):
        with self._shell_condition:
            return self._shell_visible_output.snapshot()

    def send_shell_command(self, command, *, show_echo=True, replace_prompt=False):
        if not self.shell or self.shell.closed:
            raise RuntimeError("Not connected to an SSH server")
        command = str(command).rstrip("\r\n")
        if not command:
            return
        if not show_echo:
            with self._shell_condition:
                self._shell_hidden_echoes.append((command, bool(replace_prompt)))
        with self._shell_send_lock:
            self.shell.send(command + "\n")

    def interrupt_shell(self):
        """Send terminal ETX, matching Ctrl+C in an interactive SSH client."""
        if not self.shell or self.shell.closed:
            raise RuntimeError("Not connected to an SSH server")
        with self._shell_send_lock:
            self.shell.send("\x03")

    def invalidate_shell_directory(self):
        """Forget the cached cwd after a user-entered shell command."""
        self._shell_directory = None

    _SHELL_PROMPT_LINE_RE = re.compile(
        r"^\[[^]\r\n]+@[^]\r\n]+(?:\s+[^]\r\n]*)?\][#$]\s*$"
    )

    def _drop_trailing_visible_prompt_locked(self):
        """Remove only the currently displayed shell prompt.

        Automatic Server Files cwd synchronisation sends an internal ``cd``.
        The old prompt has already been appended to the display transcript,
        while the new prompt arrives after the hidden command echo. Keeping
        both makes the terminal render two bracketed prompts side-by-side.
        This display-only rewrite is done under ``_shell_condition`` and never
        touches the raw PTY transcript used by shell/job logic.
        """
        text = self._shell_visible_output.snapshot()
        if not text:
            return False
        start = max(text.rfind("\n"), text.rfind("\r")) + 1
        tail = text[start:]
        plain = self._SHELL_ANSI_RE.sub("", tail)
        if not self._SHELL_PROMPT_LINE_RE.match(plain):
            return False
        prefix = text[:start]
        self._shell_visible_output.clear()
        if prefix:
            self._shell_visible_output.append(prefix)
        return True

    def set_shell_directory(self, folder):
        """Keep the shared shell aligned with Server Files without console noise."""
        target = self.normalize(folder)
        if self._shell_directory == target:
            return False
        command = "cd {}".format(self._shell_quote(target))
        # Prompt replacement belongs to this exact hidden command rather than
        # a global flag. Multiple rapid navigations can be in flight at once.
        self.send_shell_command(
            command, show_echo=False, replace_prompt=True)
        self._shell_directory = target
        return True





























    @_serialized_wire_call
    def _validate_remote_odb(self, path, abaqus_commands=None):
        """Serialized compatibility wrapper for remote ODB validation."""
        return self._validate_remote_odb_impl(
            path, abaqus_commands=abaqus_commands)






















    @_serialized_wire_call
    def close(self, clear_credentials=True):
        self._remote_tar_supported = None
        self._shell_stop.set()
        if self.shell:
            try:
                self.shell.close()
            except Exception:
                pass
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.shell = self.sftp = self.client = None
        if clear_credentials:
            with self._credentials_lock:
                self._password = None
