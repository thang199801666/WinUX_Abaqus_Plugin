"""Build GitHub Release integrity metadata for a WinUx FULL package.

Usage:
    python tools/build_github_release_metadata.py WinUx_1.1.0_FULL.zip

Writes ``winux-release.json`` and ``<package>.sha256`` beside the package.
The script is intentionally standard-library only so it can run in simple
release pipelines without installing WinUx dependencies.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import zipfile

PRODUCT_ID = "com.winux.desktop"
SCHEMA_VERSION = 2


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_zip_version(package_path):
    with zipfile.ZipFile(package_path, "r") as archive:
        names = archive.namelist()
        candidates = [name for name in names if name.replace("\\", "/").rstrip("/").endswith("/VERSION")]
        if "VERSION" in names:
            candidates.insert(0, "VERSION")
        # Prefer the shallowest VERSION when the package has a top-level folder.
        candidates = sorted(set(candidates), key=lambda item: (item.count("/"), len(item)))
        if not candidates:
            raise RuntimeError("FULL package does not contain VERSION")
        raw = archive.read(candidates[0]).strip()
    try:
        return raw.decode("utf-8").strip()
    except AttributeError:
        return str(raw).strip()


def build_metadata(package_path, version=None, channel="stable"):
    package_path = os.path.abspath(package_path)
    if not os.path.isfile(package_path):
        raise RuntimeError("Package not found: {}".format(package_path))
    if not zipfile.is_zipfile(package_path):
        raise RuntimeError("Package is not a ZIP archive: {}".format(package_path))
    version = version or _read_zip_version(package_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "product_id": PRODUCT_ID,
        "version": version,
        "channel": channel,
        "package": {
            "asset": os.path.basename(package_path),
            "size": int(os.path.getsize(package_path)),
            "sha256": sha256_file(package_path),
        },
        "bootstrap": {
            "version": version,
            "self_update": True,
        },
    }


def write_metadata(package_path, version=None, metadata_path=None, channel="stable"):
    metadata = build_metadata(package_path, version=version, channel=channel)
    directory = os.path.dirname(os.path.abspath(package_path))
    metadata_path = metadata_path or os.path.join(directory, "winux-release.json")
    with open(metadata_path, "w") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    checksum_path = os.path.abspath(package_path) + ".sha256"
    with open(checksum_path, "w") as handle:
        handle.write("{}  {}\n".format(
            metadata["package"]["sha256"], metadata["package"]["asset"]
        ))
    return metadata_path, checksum_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="WinUx FULL zip package")
    parser.add_argument("--version", default=None, help="Override VERSION read from the package")
    parser.add_argument("--output", default=None, help="Output path for winux-release.json")
    parser.add_argument("--channel", choices=("stable", "beta"), default="stable", help="Release channel metadata")
    args = parser.parse_args(argv)
    metadata_path, checksum_path = write_metadata(
        args.package, version=args.version, metadata_path=args.output, channel=args.channel
    )
    print(metadata_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
