"""Generate WinUx update_manifest.json after a release is fully published.

Flat deployment example:
    abaqus python tools/build_update_manifest.py .

Versioned release example:
    python tools/build_update_manifest.py releases/1.4.0 \
        --manifest-root . --release-path releases/1.4.0 --revision 12
"""
from __future__ import print_function

import argparse
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from winux_update_manifest import build_manifest, write_manifest  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a WinUx update manifest.")
    parser.add_argument("release_dir", nargs="?", default=".")
    parser.add_argument("--manifest-root", default=None)
    parser.add_argument("--release-path", default=".")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--released", default=None)
    args = parser.parse_args(argv)

    release_dir = os.path.abspath(args.release_dir)
    manifest_root = os.path.abspath(args.manifest_root or release_dir)
    manifest = build_manifest(
        release_dir,
        release_path=args.release_path,
        package_revision=args.revision,
        released=args.released,
    )
    if not os.path.isdir(manifest_root):
        os.makedirs(manifest_root)
    path = write_manifest(manifest_root, manifest=manifest)
    print("WinUx update manifest written: {}".format(path))
    print("Version: {}".format(manifest["version"]))
    print("Files: {}".format(manifest["file_count"]))
    print("Package SHA-256: {}".format(manifest["package_sha256"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
