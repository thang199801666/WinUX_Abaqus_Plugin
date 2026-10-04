"""Bounded JSON-lines protocol independent of Abaqus launcher stdio routing."""
import json
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


def _pack(value):
    if isinstance(value, datetime):
        return {"__winux_type": "datetime", "value": value.isoformat()}
    if isinstance(value, PurePath):
        kind = "path" if isinstance(value, Path) else "posix" if isinstance(value, PurePosixPath) else "windows"
        return {"__winux_type": kind, "value": str(value)}
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            return {key: _pack(item) for key, item in value.items()}
        return {"__winux_type": "mapping", "items": [[_pack(key), _pack(item)] for key, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [_pack(item) for item in value]
    return value


def _unpack(value):
    kind = value.get("__winux_type")
    if set(value) == {"__winux_type", "value"}:
        if kind == "datetime":
            return datetime.fromisoformat(value["value"])
        constructors = {"path": Path, "posix": PurePosixPath, "windows": PureWindowsPath}
        if kind in constructors:
            return constructors[kind](value["value"])
    if kind == "mapping" and set(value) == {"__winux_type", "items"}:
        return dict(value["items"])
    return value


def encode_message(message):
    encoded = (json.dumps(_pack(message), ensure_ascii=True) + "\n").encode("utf-8")
    if len(encoded) - 1 > MAX_MESSAGE_BYTES:
        raise ValueError("Floating dialog message is too large.")
    return encoded


def read_messages(connection):
    pending = b""
    while True:
        data = connection.recv(4096)
        if not data:
            if pending:
                raise ValueError("Truncated floating dialog message.")
            return
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > MAX_MESSAGE_BYTES:
                raise ValueError("Floating dialog message is too large.")
            message = json.loads(line.decode("utf-8"), object_hook=_unpack)
            if not isinstance(message, dict):
                raise ValueError("Floating dialog message must be an object.")
            yield message
        if len(pending) > MAX_MESSAGE_BYTES:
            raise ValueError("Floating dialog message is too large.")
