from __future__ import annotations

"""Direct server text read/stream/write service used by Server Notepad."""

import codecs
import functools
import hashlib
import io
import stat
import uuid


class RemoteTextConflictError(RuntimeError):
    """Raised when a server file changed after the editor opened it."""

    def __init__(self, message, current_signature=None):
        super().__init__(message)
        self.current_signature = dict(current_signature or {})


def _server_text_wire_call(method):
    """Serialize direct-text operations over the model's shared SSH session."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._connection_lock:
            return method(self, *args, **kwargs)
    return wrapper


class ServerTextMixin:
    @_server_text_wire_call
    def read_text(self, path):
        """Read a remote text file without staging it on the local machine."""
        if not self.connected:
            raise OSError("Not connected to a server")
        with self.sftp.open(str(path), "rb") as stream:
            data = stream.read()
        return data.decode("utf-8", "replace")

    @staticmethod
    def _decode_remote_text(data):
        """Decode editable server text while preserving a round-trip encoding."""
        data = bytes(data or b"")
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig"), "utf-8-sig"
        if data.startswith(codecs.BOM_UTF16_LE):
            return data[len(codecs.BOM_UTF16_LE):].decode("utf-16-le"), "utf-16-le-bom"
        if data.startswith(codecs.BOM_UTF16_BE):
            return data[len(codecs.BOM_UTF16_BE):].decode("utf-16-be"), "utf-16-be-bom"
        if b"\x00" in data:
            raise ValueError("The selected server file appears to be binary")
        try:
            return data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            # Latin-1 is a lossless byte-to-text fallback.  It keeps legacy
            # solver/config files editable without silently replacing bytes.
            return data.decode("latin-1"), "latin-1"

    @staticmethod
    def _encode_remote_text(text, encoding):
        text = str(text or "")
        encoding = str(encoding or "utf-8").casefold()
        if encoding == "utf-16-le-bom":
            return codecs.BOM_UTF16_LE + text.encode("utf-16-le")
        if encoding == "utf-16-be-bom":
            return codecs.BOM_UTF16_BE + text.encode("utf-16-be")
        if encoding == "utf-8-sig":
            return text.encode("utf-8-sig")
        if encoding == "latin-1":
            try:
                return text.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    "This file uses Latin-1 and the edited text contains "
                    "characters that cannot be saved in that encoding") from exc
        return text.encode("utf-8")

    @staticmethod
    def _remote_text_signature(attributes, data):
        return {
            "size": int(getattr(attributes, "st_size", len(data)) or 0),
            "mtime": int(getattr(attributes, "st_mtime", 0) or 0),
            "sha256": hashlib.sha256(bytes(data)).hexdigest(),
        }

    def _read_text_payload_prefetched(self, path, size, limit):
        """Read a small editable text file with SFTP request pipelining.

        Paramiko's plain ``SFTPFile.read()`` can become latency-bound because it
        waits for many 32/128 KiB request-response cycles.  ``getfo`` and
        ``prefetch`` keep several requests in flight at once, which is much
        closer to Notepad++'s perceived open speed on a remote share while
        still keeping the data in memory (no local working copy).
        """
        size = int(size or 0)
        if size > int(limit):
            raise ValueError(
                "Server Notepad supports files up to {:.1f} MB".format(
                    int(limit) / (1024.0 * 1024.0)))

        getfo = getattr(self.sftp, "getfo", None)
        if callable(getfo):
            buffer = io.BytesIO()
            try:
                getfo(
                    str(path), buffer, prefetch=True,
                    max_concurrent_prefetch_requests=(
                        self.DOWNLOAD_PREFETCH_REQUESTS),
                )
            except TypeError:
                # Paramiko < 3.3 supports prefetch but not the explicit request
                # limit.  Older releases may expose only the two-argument form.
                try:
                    getfo(str(path), buffer, prefetch=True)
                except TypeError:
                    getfo(str(path), buffer)
            data = buffer.getvalue()
        else:
            chunks = []
            total = 0
            with self.sftp.open(str(path), "rb") as stream:
                prefetch = getattr(stream, "prefetch", None)
                if callable(prefetch):
                    try:
                        prefetch(
                            file_size=size,
                            max_concurrent_requests=(
                                self.DOWNLOAD_PREFETCH_REQUESTS),
                        )
                    except (AttributeError, TypeError, OSError):
                        pass
                while True:
                    chunk = stream.read(self.TEXT_EDITOR_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > int(limit):
                        raise ValueError(
                            "Server Notepad supports files up to {:.1f} MB".format(
                                int(limit) / (1024.0 * 1024.0)))
                    chunks.append(chunk)
            data = b"".join(chunks)

        if len(data) > int(limit):
            raise ValueError(
                "Server Notepad supports files up to {:.1f} MB".format(
                    int(limit) / (1024.0 * 1024.0)))
        return data

    @_server_text_wire_call
    def read_text_snapshot(self, path, max_bytes=None):
        """Return text plus an integrity signature for direct server editing.

        The editor performs a stable lstat/read/stat snapshot and pipelines the
        SFTP read.  Reusing the initial ``lstat`` result as the before-state
        removes one network round trip per attempt while still rejecting
        symlinks and detecting files that changed during the read.
        """
        if not self.connected:
            raise OSError("Not connected to a server")
        path = self.normalize(path)
        limit = int(max_bytes or self.TEXT_EDITOR_MAX_BYTES)
        if limit < 1:
            raise ValueError("Invalid server editor size limit")

        lstat = getattr(self.sftp, "lstat", None)
        for _attempt in range(3):
            if callable(lstat):
                before = lstat(str(path))
                if stat.S_ISLNK(before.st_mode):
                    raise ValueError(
                        "Server Notepad does not edit symbolic links directly")
            else:
                before = self.sftp.stat(str(path))
            if stat.S_ISDIR(before.st_mode):
                raise ValueError("Server Notepad requires a file, not a folder")
            size = int(before.st_size or 0)
            if size > limit:
                raise ValueError(
                    "Server Notepad supports files up to {:.1f} MB; this file is {:.1f} MB".format(
                        limit / (1024.0 * 1024.0), size / (1024.0 * 1024.0)))

            data = self._read_text_payload_prefetched(path, size, limit)
            after = self.sftp.stat(str(path))
            stable = (
                int(before.st_size or 0) == int(after.st_size or 0)
                and int(before.st_mtime or 0) == int(after.st_mtime or 0)
                and len(data) == int(after.st_size or 0)
            )
            if stable:
                text, encoding = self._decode_remote_text(data)
                return {
                    "path": str(path),
                    "text": text,
                    "encoding": encoding,
                    "size": len(data),
                    "signature": self._remote_text_signature(after, data),
                }
        raise RuntimeError(
            "The server file changed while it was being opened; try again")

    @_server_text_wire_call
    def stream_text_snapshot(
            self, path, on_begin, on_chunk, on_end, max_bytes=None):
        """Stream one editable server file without buffering the whole file.

        This is the preferred Server Notepad open path.  SFTP prefetch keeps
        multiple reads in flight while decoded text is forwarded immediately to
        the standalone Tk process.  The callback chain provides natural pipe
        backpressure: if Tk is temporarily busy, the network reader slows down
        instead of accumulating an unbounded in-memory snapshot.

        ``on_begin`` receives preliminary metadata after encoding detection,
        ``on_chunk`` receives ``(text, source_byte_count)``, and ``on_end``
        receives the final stable SHA-256 signature.  UTF-8 that proves invalid
        after the first block is retried once as Latin-1; an unstable server
        file is retried up to three times.  The child resets its buffer on each
        new begin event, so retries never expose a mixed snapshot.
        """
        if not self.connected:
            raise OSError("Not connected to a server")
        path = self.normalize(path)
        limit = int(max_bytes or self.TEXT_EDITOR_MAX_BYTES)
        if limit < 1:
            raise ValueError("Invalid server editor size limit")
        if not callable(on_begin) or not callable(on_chunk) or not callable(on_end):
            raise TypeError("Server Notepad stream callbacks are required")

        class _RetryLatin1(Exception):
            pass

        lstat = getattr(self.sftp, "lstat", None)
        forced_encoding = None
        for attempt in range(3):
            if callable(lstat):
                before = lstat(str(path))
                if stat.S_ISLNK(before.st_mode):
                    raise ValueError(
                        "Server Notepad does not edit symbolic links directly")
            else:
                before = self.sftp.stat(str(path))
            if stat.S_ISDIR(before.st_mode):
                raise ValueError("Server Notepad requires a file, not a folder")
            size = int(before.st_size or 0)
            if size > limit:
                raise ValueError(
                    "Server Notepad supports files up to {:.1f} MB; this file is {:.1f} MB".format(
                        limit / (1024.0 * 1024.0), size / (1024.0 * 1024.0)))

            try:
                with self.sftp.open(str(path), "rb") as stream:
                    prefetch = getattr(stream, "prefetch", None)
                    if callable(prefetch):
                        try:
                            prefetch(
                                file_size=size,
                                max_concurrent_requests=self.DOWNLOAD_PREFETCH_REQUESTS,
                            )
                        except (AttributeError, TypeError, OSError):
                            try:
                                prefetch(file_size=size)
                            except (AttributeError, TypeError, OSError):
                                pass

                    first = stream.read(min(self.TEXT_EDITOR_PROBE_SIZE, max(1, size)))
                    first = bytes(first or b"")
                    if len(first) > limit:
                        raise ValueError("The server file is too large to edit safely")

                    bom_len = 0
                    encoding = forced_encoding
                    codec_name = None
                    if encoding is None:
                        if first.startswith(codecs.BOM_UTF8):
                            encoding = "utf-8-sig"
                            codec_name = "utf-8"
                            bom_len = len(codecs.BOM_UTF8)
                        elif first.startswith(codecs.BOM_UTF16_LE):
                            encoding = "utf-16-le-bom"
                            codec_name = "utf-16-le"
                            bom_len = len(codecs.BOM_UTF16_LE)
                        elif first.startswith(codecs.BOM_UTF16_BE):
                            encoding = "utf-16-be-bom"
                            codec_name = "utf-16-be"
                            bom_len = len(codecs.BOM_UTF16_BE)
                        else:
                            if b"\x00" in first:
                                raise ValueError(
                                    "The selected server file appears to be binary")
                            try:
                                first.decode("utf-8")
                            except UnicodeDecodeError:
                                encoding = "latin-1"
                                codec_name = "latin-1"
                            else:
                                encoding = "utf-8"
                                codec_name = "utf-8"
                    else:
                        codec_name = "latin-1" if encoding == "latin-1" else encoding

                    decoder = codecs.getincrementaldecoder(codec_name)(errors="strict")
                    begin = {
                        "path": str(path),
                        "encoding": encoding,
                        "size": size,
                        "bytes_total": size,
                        "attempt": attempt + 1,
                    }
                    on_begin(begin)

                    digest = hashlib.sha256()
                    total = 0
                    crlf = lf = cr = 0
                    previous_cr = False

                    def emit(data, skip=0):
                        nonlocal total, crlf, lf, cr, previous_cr
                        data = bytes(data or b"")
                        if not data:
                            return
                        digest.update(data)
                        total += len(data)
                        payload = data[int(skip or 0):]
                        if encoding not in ("utf-16-le-bom", "utf-16-be-bom") and b"\x00" in payload:
                            raise ValueError(
                                "The selected server file appears to be binary")
                        try:
                            text = decoder.decode(payload, final=False)
                        except UnicodeDecodeError as exc:
                            if encoding == "utf-8" and forced_encoding is None:
                                raise _RetryLatin1() from exc
                            raise
                        if text:
                            # Count EOLs across callback boundaries without
                            # retaining the entire text buffer.
                            idx = 0
                            if previous_cr:
                                if text.startswith("\n"):
                                    crlf += 1
                                    idx = 1
                                else:
                                    cr += 1
                                previous_cr = False
                            sample = text[idx:]
                            pairs = sample.count("\r\n")
                            crlf += pairs
                            remainder = sample.replace("\r\n", "")
                            lf += remainder.count("\n")
                            cr += remainder.count("\r")
                            if text.endswith("\r"):
                                cr = max(0, cr - 1)
                                previous_cr = True
                            on_chunk(text, len(data))

                    if first:
                        emit(first, bom_len)
                    while total < size:
                        data = stream.read(self.TEXT_EDITOR_READ_CHUNK_SIZE)
                        if not data:
                            break
                        emit(data, 0)
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        on_chunk(tail, 0)
                    if previous_cr:
                        cr += 1

                after = self.sftp.stat(str(path))
                stable = (
                    int(before.st_size or 0) == int(after.st_size or 0)
                    and int(before.st_mtime or 0) == int(after.st_mtime or 0)
                    and total == int(after.st_size or 0)
                )
                if not stable:
                    forced_encoding = None
                    continue
                if crlf >= lf and crlf >= cr and crlf:
                    eol = "\r\n"
                elif cr > lf and cr:
                    eol = "\r"
                else:
                    eol = "\n"
                final = {
                    "path": str(path),
                    "encoding": encoding,
                    "size": total,
                    "eol": eol,
                    "signature": {
                        "size": int(after.st_size or 0),
                        "mtime": int(after.st_mtime or 0),
                        "sha256": digest.hexdigest(),
                    },
                }
                on_end(final)
                return final
            except _RetryLatin1:
                # Reset the child on the next begin and replay the remote file
                # losslessly. This is rare and keeps the fast UTF-8 path fast.
                forced_encoding = "latin-1"
                continue

        raise RuntimeError(
            "The server file changed while it was being opened; try again")

    @_server_text_wire_call
    def write_text_snapshot(
            self, path, text, expected_signature, encoding="utf-8",
            force=False, max_bytes=None):
        """Atomically replace one remote text file after conflict checking."""
        if not self.connected:
            raise OSError("Not connected to a server")
        path = self.normalize(path)
        limit = int(max_bytes or self.TEXT_EDITOR_MAX_BYTES)
        lstat = getattr(self.sftp, "lstat", None)
        if callable(lstat):
            link_attr = lstat(str(path))
            if stat.S_ISLNK(link_attr.st_mode):
                raise ValueError(
                    "Server Notepad does not edit symbolic links directly")
        current_attr = None
        current_data = None
        for _attempt in range(3):
            before = self.sftp.stat(str(path))
            if stat.S_ISDIR(before.st_mode):
                raise ValueError("Server Notepad requires a file, not a folder")
            current_size = int(before.st_size or 0)
            if current_size > limit:
                raise ValueError("The server file is now too large to edit safely")
            with self.sftp.open(str(path), "rb") as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("The server file is now too large to edit safely")
            after = self.sftp.stat(str(path))
            if (int(before.st_size or 0) == int(after.st_size or 0)
                    and int(before.st_mtime or 0) == int(after.st_mtime or 0)
                    and len(data) == int(after.st_size or 0)):
                current_attr = after
                current_data = data
                break
        if current_attr is None or current_data is None:
            raise RemoteTextConflictError(
                "The server file kept changing while WinUx was preparing to save it.")
        current_signature = self._remote_text_signature(
            current_attr, current_data)

        expected = dict(expected_signature or {})
        expected_hash = str(expected.get("sha256") or "")
        if not force and not expected_hash:
            raise ValueError(
                "Server Notepad is missing the original file signature; reload the file before saving")
        if (not force and
                current_signature.get("sha256") != expected_hash):
            raise RemoteTextConflictError(
                "The server file changed after you opened it.",
                current_signature=current_signature,
            )

        payload = self._encode_remote_text(text, encoding)
        if len(payload) > limit:
            raise ValueError(
                "Edited text exceeds the {:.1f} MB Server Notepad limit".format(
                    limit / (1024.0 * 1024.0)))

        temporary = path.with_name(
            ".{}.winux-edit-{}".format(path.name, uuid.uuid4().hex))
        try:
            with self.sftp.open(str(temporary), "wb") as stream:
                stream.write(payload)
                try:
                    stream.flush()
                except Exception:
                    pass
            try:
                self.sftp.chmod(temporary.as_posix(),
                                stat.S_IMODE(current_attr.st_mode))
            except (AttributeError, IOError, OSError):
                pass

            staged_attr = self.sftp.stat(str(temporary))
            if int(staged_attr.st_size or 0) != len(payload):
                raise RuntimeError("Server Notepad save verification failed")
            with self.sftp.open(str(temporary), "rb") as stream:
                staged_data = stream.read(limit + 1)
            if hashlib.sha256(staged_data).digest() != hashlib.sha256(payload).digest():
                raise RuntimeError("Server Notepad checksum verification failed")

            self._publish_uploaded_file(self.sftp, temporary, path)
            final_attr = self.sftp.stat(str(path))
            final_signature = self._remote_text_signature(final_attr, payload)
            return {
                "path": str(path),
                "text": str(text or ""),
                "encoding": str(encoding or "utf-8"),
                "size": len(payload),
                "signature": final_signature,
            }
        finally:
            try:
                self.sftp.remove(str(temporary))
            except (IOError, OSError):
                pass

