"""Portable PDG binary container: versioned header, compressed data and PNG."""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import struct
import tempfile
import zipfile

from PIL import Image


MAGIC = b"WINUXPDG\r\n"
FORMAT_VERSION = 1
_VERSION = struct.Struct("<H")


def write_pdg(path, document, image):
    """Publish one complete file atomically; keep an existing file on failure."""
    path = Path(path).resolve()
    payload = dict(document)
    payload["image_embedded"] = image is not None
    metadata = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    image_bytes = None
    if image is not None:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w+b") as handle:
            handle.write(MAGIC)
            handle.write(_VERSION.pack(FORMAT_VERSION))
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("project.json", metadata)
                if image_bytes is not None:
                    archive.writestr("image.png", image_bytes, compress_type=zipfile.ZIP_STORED)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_pdg(path):
    """Decode in memory; no external image paths or archive extraction needed."""
    try:
        with open(path, "rb") as handle:
            if handle.read(len(MAGIC)) != MAGIC:
                raise ValueError("This is not a Plot Digitizer .pdg file.")
            version = handle.read(_VERSION.size)
            if len(version) != _VERSION.size or _VERSION.unpack(version)[0] != FORMAT_VERSION:
                raise ValueError("Unsupported or incomplete PDG format version.")
            with zipfile.ZipFile(handle) as archive:
                entries = archive.namelist()
                if entries.count("project.json") != 1 or entries.count("image.png") > 1:
                    raise ValueError("PDG project entries are missing or duplicated.")
                document = json.loads(archive.read("project.json").decode("utf-8"))
                if not isinstance(document, dict) or not isinstance(document.get("image_embedded"), bool):
                    raise ValueError("Invalid PDG project metadata.")
                if document["image_embedded"] != ("image.png" in entries):
                    raise ValueError("PDG embedded image declaration does not match its contents.")
                image = None
                if document["image_embedded"]:
                    with Image.open(BytesIO(archive.read("image.png"))) as source:
                        image = source.convert("RGB")
                return document, image
    except (zipfile.BadZipFile, KeyError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PDG project is incomplete or corrupted: {}".format(error)) from error
