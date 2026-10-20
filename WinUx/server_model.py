from __future__ import annotations

import json
import re
import shlex
import socket
import threading
import uuid
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
    # Launcher discovery is intentionally cheap: one login-shell command checks
    # which configured Abaqus commands actually exist before any heavy
    # ``odbAccess/openOdb`` interpreter is started.  Keep a short hard timeout
    # here so a broken profile/login shell cannot make Plots slower than the
    # compatibility probes it is meant to optimize.
    ABAQUS_DISCOVERY_TIMEOUT_SECONDS = 5.0
    ABAQUS_DISCOVERY_CACHE_SECONDS = 300.0
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
        # Best-known cwd used only for local/remote Tab completion. Unlike
        # _shell_directory this value is not invalidated by every user command;
        # simple ``cd`` commands update it directly while ambiguous cwd-changing
        # shell constructs mark it unknown.
        self._shell_completion_directory = None
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
        # Compatibility discovery state is session-local on purpose.  A cached
        # release only changes probe priority; it never bypasses opening the
        # real ODB, so recreated databases remain safe.
        self._odb_abaqus_directory_hint_cache = {}
        self._odb_abaqus_host_hint_cache = {}
        self._abaqus_available_command_cache = {}
        self._odb_abaqus_command_cache_lock = threading.RLock()

    def request_shutdown(self):
        """Abort transport I/O without waiting for ``_connection_lock``.

        Every normal SSH/SFTP operation owns ``_connection_lock`` for its full
        duration. Calling ``close()`` from the render thread while a transfer is
        active therefore waits for that transfer (or a network timeout) and
        makes the WinUX window appear frozen. Application shutdown instead
        detaches the live objects, shuts down the transport socket immediately
        to wake blocked Paramiko calls, and lets final ``close()`` methods run
        on a daemon cleanup thread after Paramiko has observed EOF.
        """
        self._remote_tar_supported = None
        self._shell_stop.set()

        # Detach first so new background work observes a disconnected model.
        # Existing workers retain their local channel/SFTP objects and unwind
        # naturally once the transport socket is shut down below.
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

        def interrupt_client_socket(value):
            if value is None:
                return None, None
            try:
                transport = value.get_transport()
            except Exception:
                transport = None
            raw_socket = getattr(transport, "sock", None) if transport else None
            if raw_socket is not None:
                # Wake Paramiko's blocking recv/send without invalidating the
                # WinSock handle underneath its transport thread.  Calling
                # close() here used to race Paramiko's packetizer on Windows:
                # recv() would then observe WSAENOTSOCK/WinError 10038 and
                # print ``Socket exception: ... not a socket (10038)`` to the
                # console during an otherwise normal WinUx shutdown.
                #
                # shutdown(SHUT_RDWR) is enough to make recv() return EOF. The
                # transport thread can then unwind normally and close its own
                # socket; final object cleanup happens off the render thread.
                try:
                    raw_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            return transport, raw_socket

        transport, raw_socket = interrupt_client_socket(client)

        def cleanup():
            # Give the Paramiko receiver a bounded chance to consume the EOF
            # produced by shutdown() before any object close invalidates the
            # socket handle.  This wait is on a daemon cleanup thread, never on
            # the UI/render path, so application Close remains instantaneous.
            if transport is not None:
                try:
                    is_alive = getattr(transport, "is_alive", None)
                    join = getattr(transport, "join", None)
                    if callable(is_alive) and callable(join) and is_alive():
                        join(0.75)
                except Exception:
                    pass

            for resource in (shell, sftp, client) + auxiliary_clients:
                if resource is None:
                    continue
                try:
                    resource.close()
                except Exception:
                    pass

            # SSHClient.close() normally owns the final socket close.  Keep a
            # best-effort fallback for injected/partial clients used by hosts
            # and tests, but only after Paramiko had the chance to exit.
            if raw_socket is not None:
                try:
                    raw_socket.close()
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
            self._shell_completion_directory = self.home
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
                    if self._shell_completion_directory is None:
                        self._shell_completion_directory = self.home
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
        probes = []
        for candidate in candidates:
            probe = "{} python -c {}".format(
                candidate, cls._shell_quote(probe_code))
            probes.append((candidate, cls._login_shell_command(probe)))
        outcomes, failures = cls._race_abaqus_probe_commands(
            cls._exec_client, client, probes,
            cls.ABAQUS_PROBE_TIMEOUT_SECONDS,
            probe_success=lambda outcome: (
                outcome[0] == 0 and marker in outcome[1]))
        for candidate, _command in probes:
            if candidate in failures:
                attempted.append(
                    "{} ({})".format(candidate, failures[candidate]))
                continue
            status, output, error = outcomes[candidate]
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
            # A freshly opened interactive shell starts in the login home.
            self._shell_completion_directory = self.home
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

    def append_console_message(self, message, *, command=""):
        """Display local help without sending it to the PTY or raw transcript."""
        with self._shell_condition:
            visible = self._shell_visible_output.snapshot()
            tail = visible[max(visible.rfind("\n"), visible.rfind("\r")) + 1:]
            plain = self._SHELL_ANSI_RE.sub("", tail)
            prompt = tail if self._SHELL_PROMPT_LINE_RE.match(plain) else ""
            separator = ""
            if prompt:
                if not prompt[-1].isspace():
                    separator = " "
            elif visible and not visible.endswith(("\n", "\r")):
                separator = "\r\n"
            text = separator + str(command) + "\r\n" + str(message).rstrip()
            self._shell_visible_output.append(text + "\r\n" + prompt)

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
        """Forget the strict cwd cache after a user-entered shell command."""
        self._shell_directory = None

    def note_shell_command(self, command):
        """Keep a best-effort cwd for Tab completion without probing the PTY.

        The interactive terminal keeps its editable line locally, so completion
        runs on auxiliary SSH/SFTP channels instead of injecting characters into
        the live PTY.  Server Files provides an exact cwd through
        :meth:`set_shell_directory`; between navigations we can additionally
        track ordinary ``cd`` commands.  Complex shell expressions are marked
        unknown rather than guessed.
        """
        text = str(command or "").strip()
        if not text:
            return
        try:
            words = shlex.split(text, posix=True)
        except ValueError:
            words = []
        if not words:
            return
        first = words[0]
        if first not in ("cd", "pushd", "popd"):
            return
        # Compound expressions can change cwd conditionally or more than once.
        # Do not claim an exact directory for those cases.
        if re.search(r"(?:&&|\|\||[;`]|\$\(|[()])", text):
            self._shell_completion_directory = None
            return
        if first != "cd" or len(words) > 2:
            self._shell_completion_directory = None
            return
        target = words[1] if len(words) == 2 else "~"
        if target == "-" or target.startswith("~") and target not in ("~",) and not target.startswith("~/"):
            self._shell_completion_directory = None
            return
        if target == "~":
            resolved = self.home
        elif target.startswith("~/"):
            resolved = self.home / target[2:]
        elif target.startswith("/"):
            resolved = PurePosixPath(target)
        else:
            base = self._shell_completion_directory or self._shell_directory or self.home
            resolved = PurePosixPath(base) / target
        self._shell_completion_directory = self.normalize(resolved)

    @staticmethod
    def _completion_word_context(draft, cursor):
        """Return the editable shell word ending at *cursor*.

        This intentionally implements only lexical shell rules required for
        completion: whitespace/separators split words, while quotes and
        backslash escapes keep spaces inside the active token.  It remains
        useful with an unfinished quote, which ``shlex.split`` cannot parse.
        """
        text = str(draft or "")
        cursor = max(0, min(len(text), int(cursor)))
        before = text[:cursor]
        quote = None
        escaped = False
        token_start = 0
        segment_start = 0
        word_index = 0
        in_word = False
        for index, char in enumerate(before):
            if escaped:
                escaped = False
                in_word = True
                continue
            if char == "\\" and quote != "'":
                escaped = True
                in_word = True
                continue
            if quote is not None:
                in_word = True
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"'):
                quote = char
                in_word = True
                continue
            if char in ";|&":
                if in_word:
                    word_index += 1
                in_word = False
                word_index = 0
                token_start = index + 1
                segment_start = index + 1
                continue
            if char in "<>":
                # Redirection starts a new shell token but does not start a
                # new command segment.  Treat the target as an argument/path
                # so constructs such as ``grep foo>res<Tab>`` and ``2>err``
                # complete the filename after the operator.
                if in_word:
                    word_index += 1
                in_word = False
                token_start = index + 1
                continue
            if char.isspace():
                if in_word:
                    word_index += 1
                in_word = False
                token_start = index + 1
                continue
            if not in_word:
                token_start = index
                in_word = True

        raw = before[token_start:] if in_word else ""
        if not in_word:
            token_start = cursor
        opener = raw[0] if raw[:1] in ("'", '"') else None
        payload = raw[1:] if opener else raw
        # If the quote is already closed immediately before the caret, treat
        # the token as complete and avoid synthesizing a second closing quote.
        closed_quote = bool(opener and len(payload) > 0 and payload.endswith(opener) and quote is None)
        if closed_quote:
            payload = payload[:-1]
        if opener == "'":
            decoded = payload
        else:
            decoded_chars = []
            escape = False
            for char in payload:
                if escape:
                    decoded_chars.append(char)
                    escape = False
                elif char == "\\":
                    escape = True
                else:
                    decoded_chars.append(char)
            if escape:
                decoded_chars.append("\\")
            decoded = "".join(decoded_chars)
        # Find the end of the active shell token as well.  The completion
        # prefix is still the text before the caret, but replacing through the
        # lexical token end prevents a mid-token completion from producing
        # duplicated suffixes (``foo<Tab>bar`` -> ``foobarbar``).
        token_end = cursor
        forward_quote = quote
        forward_escaped = False
        for index in range(cursor, len(text)):
            char = text[index]
            if forward_escaped:
                forward_escaped = False
                token_end = index + 1
                continue
            if char == "\\" and forward_quote != "'":
                forward_escaped = True
                token_end = index + 1
                continue
            if forward_quote is not None:
                token_end = index + 1
                if char == forward_quote:
                    forward_quote = None
                continue
            if char in ("'", '"'):
                forward_quote = char
                token_end = index + 1
                continue
            if char.isspace() or char in ";|&<>":
                break
            token_end = index + 1

        return {
            "start": token_start, "end": token_end, "raw": raw,
            "value": decoded, "quote": opener,
            "closed_quote": closed_quote,
            "command_position": word_index == 0,
            "word_index": word_index,
            "segment_start": segment_start,
        }

    @staticmethod
    def _completion_escape(value, quote=None, close_quote=False):
        value = str(value)
        if quote == "'" and "'" not in value:
            return "'" + value + ("'" if close_quote else "")
        if quote == '"':
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
            return '"' + escaped + ('"' if close_quote else "")
        # POSIX-safe inline escaping while retaining slash readability.
        return re.sub(r"([\s\\'\"`$&;|<>()[\]{}*?!])", r"\\\1", value)

    def _path_completion_entries(
            self, token, quote=None, limit=64, directories_only=False):
        """Return insertion/display pairs for remote filename completion.

        Readline inserts shell-escaped text but prints human-readable names in
        its ambiguous-match grid.  Keeping those representations separate
        avoids lists such as ``My\\ Folder/`` while retaining a safe command
        line replacement.
        """
        token = str(token or "")
        if token == "~":
            return [("~/", "~/")]
        if "/" in token:
            head, name_prefix = token.rsplit("/", 1)
            display_head = head + "/"
        else:
            head, name_prefix, display_head = "", token, ""

        cwd = self._shell_completion_directory or self._shell_directory or self.home
        if token.startswith("~/"):
            relative_head = head[2:] if head.startswith("~/") else ""
            folder = self.home / relative_head
        elif quote != "'" and token.startswith("$HOME/"):
            relative_head = head[len("$HOME/"):] if head.startswith("$HOME/") else ""
            folder = self.home / relative_head
        elif quote != "'" and token.startswith("${HOME}/"):
            relative_head = head[len("${HOME}/"):] if head.startswith("${HOME}/") else ""
            folder = self.home / relative_head
        elif quote != "'" and token.startswith("$PWD/"):
            relative_head = head[len("$PWD/"):] if head.startswith("$PWD/") else ""
            folder = PurePosixPath(cwd) / relative_head
        elif quote != "'" and token.startswith("${PWD}/"):
            relative_head = head[len("${PWD}/"):] if head.startswith("${PWD}/") else ""
            folder = PurePosixPath(cwd) / relative_head
        elif token.startswith("/"):
            folder = PurePosixPath(head or "/")
        elif head:
            folder = PurePosixPath(cwd) / head
        else:
            folder = PurePosixPath(cwd)
        folder = self.normalize(folder)

        try:
            items = self.list_directory(folder)
        except Exception:
            return []
        show_hidden = name_prefix.startswith(".")
        entries = []
        for item in items:
            name = str(item.name)
            if name.startswith(".") and not show_hidden:
                continue
            if not name.startswith(name_prefix):
                continue
            if directories_only and not item.is_dir:
                continue
            display = display_head + name + ("/" if item.is_dir else "")
            close_quote = bool(quote and not item.is_dir)
            variable_prefix = next((prefix for prefix in (
                "${HOME}/", "$HOME/", "${PWD}/", "$PWD/")
                if quote != "'" and display.startswith(prefix)), None)
            if variable_prefix is None:
                insert = self._completion_escape(
                    display, quote=quote, close_quote=close_quote)
            else:
                suffix = display[len(variable_prefix):]
                if quote == '"':
                    escaped = (suffix.replace("\\", "\\\\")
                               .replace('"', '\\"')
                               .replace("$", "\\$")
                               .replace("`", "\\`"))
                    insert = '"' + variable_prefix + escaped + ('"' if close_quote else '')
                else:
                    insert = variable_prefix + self._completion_escape(suffix)
            entries.append((insert, display))
            if len(entries) >= max(1, int(limit)):
                break
        return entries

    def _path_completion_candidates(
            self, token, quote=None, limit=64, directories_only=False):
        # Compatibility helper retained for callers/tests that only need the
        # text inserted into the editable command line.
        return [insert for insert, _display in self._path_completion_entries(
            token, quote=quote, limit=limit, directories_only=directories_only)]

    def _command_completion_candidates(self, prefix, limit=64):
        prefix = str(prefix or "")
        if not prefix:
            return []
        script = (
            "compgen -c -- {} 2>/dev/null | LC_ALL=C sort -u | head -n {}"
            .format(self._shell_quote(prefix), max(1, int(limit)))
        )
        client = _SharedTransportClient(self, self._active_transport())
        try:
            _status, output, _error = self._exec_client(
                client, self._login_shell_command(script), timeout=3.0)
        except Exception:
            return []
        values = []
        seen = set()
        for line in str(output or "").splitlines():
            value = line.strip()
            if value and value.startswith(prefix) and value not in seen:
                seen.add(value)
                values.append(self._completion_escape(value))
                if len(values) >= max(1, int(limit)):
                    break
        return values

    _COMPLETION_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

    @classmethod
    def _completion_shell_role(cls, draft, context):
        """Classify the active token using lightweight POSIX shell semantics.

        ``_completion_word_context`` knows lexical word boundaries, but raw
        word indexes are not enough for wrappers such as ``sudo`` or ``env``.
        This scanner consumes the common wrappers/options that occur before an
        executable and reports whether the current token is still a command
        position or an argument of the effective command.  It deliberately
        stays conservative when syntax is incomplete.
        """
        text = str(draft or "")
        try:
            segment_start = max(0, int(context.get("segment_start", 0)))
            token_start = max(segment_start, int(context.get("start", 0)))
        except (TypeError, ValueError):
            return {"role": "argument", "command": ""}
        prefix = text[segment_start:token_start]
        try:
            words = shlex.split(prefix, posix=True)
        except ValueError:
            return {
                "role": "command" if context.get("command_position") else "argument",
                "command": cls._completion_command_name(draft, context),
            }

        index = 0
        while index < len(words) and cls._COMPLETION_ASSIGNMENT_RE.match(words[index]):
            index += 1
        if index >= len(words):
            return {"role": "command", "command": ""}

        while index < len(words):
            wrapper = words[index]
            if wrapper == "sudo":
                index += 1
                value_options = {
                    "-u": "user", "--user": "user",
                    "-g": "group", "--group": "group",
                    "-h": "host", "--host": "host",
                    "-D": "directory", "--chdir": "directory",
                    "-R": "directory", "--chroot": "directory",
                    "-C": "plain", "--close-from": "plain",
                    "-p": "plain", "--prompt": "plain",
                    "-r": "plain", "--role": "plain",
                    "-t": "plain", "--type": "plain",
                }
                while index < len(words):
                    word = words[index]
                    if cls._COMPLETION_ASSIGNMENT_RE.match(word):
                        index += 1
                        continue
                    if word == "--":
                        index += 1
                        break
                    if not word.startswith("-") or word == "-":
                        break
                    if "=" in word and word.startswith("--"):
                        index += 1
                        continue
                    role = value_options.get(word)
                    if role is not None:
                        if index + 1 >= len(words):
                            return {"role": role, "command": "sudo"}
                        index += 2
                        continue
                    # Short options may carry their value in the same token
                    # (for example ``sudo -uroot``).
                    if len(word) > 2 and word[:2] in value_options:
                        index += 1
                        continue
                    index += 1
                if index >= len(words):
                    return {"role": "command", "command": ""}
                continue

            if wrapper == "env":
                index += 1
                while index < len(words):
                    word = words[index]
                    if cls._COMPLETION_ASSIGNMENT_RE.match(word):
                        index += 1
                        continue
                    if word == "--":
                        index += 1
                        break
                    if word in ("-u", "--unset"):
                        if index + 1 >= len(words):
                            return {"role": "variable", "command": "env"}
                        index += 2
                        continue
                    if word in ("-C", "--chdir"):
                        if index + 1 >= len(words):
                            return {"role": "directory", "command": "env"}
                        index += 2
                        continue
                    if word.startswith(("--unset=", "--chdir=", "--argv0=")):
                        index += 1
                        continue
                    if word.startswith("-") and word != "-":
                        index += 1
                        continue
                    break
                if index >= len(words):
                    return {"role": "command", "command": ""}
                continue

            if wrapper in {"command", "builtin", "exec", "nohup", "time"}:
                index += 1
                value_options = {
                    "exec": {"-a"},
                    "time": {"-f", "--format", "-o", "--output"},
                }.get(wrapper, set())
                while index < len(words):
                    word = words[index]
                    if word == "--":
                        index += 1
                        break
                    if not word.startswith("-") or word == "-":
                        break
                    if word in value_options:
                        if index + 1 >= len(words):
                            return {"role": "plain", "command": wrapper}
                        index += 2
                    else:
                        index += 1
                if index >= len(words):
                    return {"role": "command", "command": ""}
                continue

            return {"role": "argument", "command": wrapper}

        return {"role": "command", "command": ""}

    def _shell_name_completion_candidates(self, kind, prefix, limit=64):
        """Complete shell metadata names without touching the interactive PTY."""
        mode = {"variable": "-v", "user": "-u", "group": "-g"}.get(str(kind))
        if mode is None:
            return []
        prefix = str(prefix or "")
        script = (
            "compgen {} -- {} 2>/dev/null | LC_ALL=C sort -u | head -n {}"
            .format(mode, self._shell_quote(prefix), max(1, int(limit)))
        )
        client = _SharedTransportClient(self, self._active_transport())
        try:
            _status, output, _error = self._exec_client(
                client, self._login_shell_command(script), timeout=3.0)
        except Exception:
            return []
        result = []
        seen = set()
        for line in str(output or "").splitlines():
            value = line.strip()
            if value and value.startswith(prefix) and value not in seen:
                seen.add(value)
                result.append(value)
                if len(result) >= max(1, int(limit)):
                    break
        return result

    def _variable_completion_entries(self, token, limit=64):
        token = str(token or "")
        braced = token.startswith("${")
        if braced:
            prefix = token[2:]
        elif token.startswith("$"):
            prefix = token[1:]
        else:
            return []
        if "/" in prefix or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$|^$", prefix):
            return []
        values = self._shell_name_completion_candidates("variable", prefix, limit=limit)
        if braced:
            return [("${" + value + "}", "${" + value + "}") for value in values]
        return [("$" + value, "$" + value) for value in values]

    @staticmethod
    def _completion_common_prefix(values):
        values = [str(value) for value in values if str(value)]
        if not values:
            return ""
        prefix = values[0]
        for value in values[1:]:
            while prefix and not value.startswith(prefix):
                prefix = prefix[:-1]
            if not prefix:
                break
        return prefix

    @staticmethod
    def _format_completion_candidates(values, columns=80):
        """Format candidates in readline-like vertical columns.

        Bash/readline fills columns top-to-bottom, then left-to-right.  Keep
        the formatting backend independent from DearPyGui so detached and
        docked consoles render the same completion list.
        """
        values = [str(value) for value in values if str(value)]
        if not values:
            return ""
        columns = max(20, int(columns or 80))
        widest = max(len(value.expandtabs(8)) for value in values)
        cell = max(2, widest + 2)
        count = max(1, columns // cell)
        rows = (len(values) + count - 1) // count
        lines = []
        for row in range(rows):
            parts = []
            for column in range(count):
                index = row + column * rows
                if index >= len(values):
                    continue
                value = values[index]
                is_last = column == count - 1 or index + rows >= len(values)
                parts.append(value if is_last else value.ljust(cell))
            lines.append("".join(parts).rstrip())
        return "\r\n".join(lines)

    def append_shell_completion_listing(self, draft, candidates, columns=80):
        """Render an ambiguous completion list without writing to the PTY.

        The current prompt already exists in the visible terminal transcript.
        Appending the editable draft, candidate grid and the prompt again
        reproduces readline's double-Tab redraw.  The next real PTY echo then
        naturally continues after that redrawn prompt, so the listing remains
        part of scrollback without sending synthetic keystrokes to the server.
        """
        values = []
        seen = set()
        for value in candidates or ():
            value = str(value)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        listing = self._format_completion_candidates(values, columns=columns)
        if not listing:
            return False
        with self._shell_condition:
            visible = self._shell_visible_output.snapshot()
            tail = visible[max(visible.rfind("\n"), visible.rfind("\r")) + 1:]
            plain = self._SHELL_ANSI_RE.sub("", tail)
            prompt = tail if self._SHELL_PROMPT_LINE_RE.match(plain) else ""
            separator = ""
            if prompt:
                if not prompt[-1].isspace():
                    separator = " "
            elif visible and not visible.endswith(("\n", "\r")):
                separator = "\r\n"
            self._shell_visible_output.append(
                separator + str(draft or "") + "\r\n" + listing +
                "\r\n" + prompt)
        return True

    @staticmethod
    def _completion_command_name(draft, context):
        """Return the command word for the active simple shell segment."""
        if context.get("command_position"):
            return ""
        text = str(draft or "")
        try:
            segment_start = max(0, int(context.get("segment_start", 0)))
            token_start = max(segment_start, int(context.get("start", 0)))
        except (TypeError, ValueError):
            return ""
        prefix = text[segment_start:token_start].strip()
        if not prefix:
            return ""
        try:
            words = shlex.split(prefix, posix=True)
        except ValueError:
            return ""
        return str(words[0]) if words else ""

    def complete_shell_input(self, draft, cursor, limit=64):
        """Return remote shell completion candidates for the active token.

        Completion never writes partial text into the interactive PTY.  It uses
        the existing SFTP channel for filesystem names and an auxiliary exec
        channel for command/metadata names, so stale completion work cannot
        alter the command currently being edited in the Console.
        """
        if not self.connected:
            return {"start": int(cursor), "end": int(cursor), "candidates": []}
        context = self._completion_word_context(draft, cursor)
        value = context["value"]
        role_info = self._completion_shell_role(draft, context)
        role = str(role_info.get("role") or "argument")
        command_name = str(role_info.get("command") or "")

        entries = []
        completion_kind = role

        # Parameter expansion is a first-class readline completion context.
        # Keep the '$' syntax intact instead of escaping it as a filename.
        variable_entries = self._variable_completion_entries(value, limit=limit)
        if variable_entries:
            entries.extend(variable_entries)
            completion_kind = "variable-inline"
        elif role in {"user", "group", "variable"}:
            values = self._shell_name_completion_candidates(role, value, limit=limit)
            entries.extend((item, item) for item in values)
        else:
            path_like = (
                role != "command" or "/" in value
                or value.startswith((".", "~")) or not value
            )
            if role == "command" and not path_like:
                commands = self._command_completion_candidates(value, limit=limit)
                entries.extend((item, item) for item in commands)
            # Shells fall back to filename completion when command-name
            # completion has no useful match; arguments use filesystem
            # completion by default.  Wrapper options such as sudo -D/env -C
            # explicitly constrain the result to directories.
            if role == "directory" or path_like or not entries:
                directories_only = (
                    role == "directory"
                    or (role == "argument" and command_name in {"cd", "pushd"})
                )
                entries.extend(self._path_completion_entries(
                    value, quote=context["quote"], limit=limit,
                    directories_only=directories_only))

        candidates = []
        display_candidates = []
        seen = set()
        for candidate, display in entries:
            candidate = str(candidate)
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
            display_candidates.append(str(display))
            if len(candidates) >= max(1, int(limit)):
                break

        # When the result reaches the transport/UI cap there may be unseen
        # matches with a shorter prefix. Be conservative and avoid extending
        # the editable text in that case.
        common_prefix = ""
        if len(candidates) < max(1, int(limit)):
            common_prefix = self._completion_common_prefix(candidates)

        replacement = ""
        if len(candidates) == 1:
            replacement = candidates[0]
            # Inline variable expansion deliberately remains attached to the
            # surrounding shell word. Commands, account names and regular
            # files terminate with a space; directories retain '/'.
            append_space = completion_kind != "variable-inline"
            if (append_space and not replacement.endswith("/")
                    and int(cursor) >= int(context["end"])):
                replacement += " "
        return {
            "start": context["start"], "end": context["end"],
            "candidates": candidates,
            "display_candidates": display_candidates,
            "common_prefix": common_prefix,
            "replacement": replacement,
            "completion_kind": completion_kind,
        }

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
        self._shell_completion_directory = target
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
