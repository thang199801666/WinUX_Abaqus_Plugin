"""Build a complete, verified GitHub update package from a source deployment."""
from __future__ import print_function

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from winux_update_manifest import read_version, source_descriptor, write_manifest
from tools.build_github_release_metadata import write_metadata


def build_release(source_dir, output_dir, expected_tag=None):
    source_dir = os.path.abspath(source_dir)
    output_dir = os.path.abspath(output_dir)
    # Keep output outside the source to avoid recursively packaging old artifacts.
    if output_dir == source_dir or output_dir.startswith(source_dir + os.sep):
        raise ValueError("Release output directory must be outside the source deployment.")
    version = read_version(source_dir)
    if not version:
        raise ValueError("Source deployment has no VERSION.")
    if expected_tag and expected_tag != "v" + version:
        raise ValueError("Release tag {} does not match VERSION v{}.".format(expected_tag, version))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    temporary = tempfile.mkdtemp(prefix="winux_release_")
    try:
        stage = os.path.join(temporary, "deployment")
        shutil.copytree(source_dir, stage, ignore=shutil.ignore_patterns(
            ".git", ".github", ".pytest_cache", ".mypy_cache", "__pycache__",
            "*.pyc", "*.pyo", "tests", "tools", "*.zip", "*.partial",
            "*.log", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
            "id_rsa*", "id_ed25519*", "settings.json", "known_hosts",
            "OPTIMIZATION_GOAL.md", "REFACTOR_NOTES.md",
        ))
        # Never publish the working tree's potentially stale manifest.
        write_manifest(stage)
        descriptor = source_descriptor(stage, verify_hashes=True)
        package = os.path.join(output_dir, "WinUx_{}_FULL.zip".format(version))
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            paths = [entry["path"] for entry in descriptor["manifest"]["files"]]
            paths.append("update_manifest.json")
            for relative in sorted(paths):
                archive.write(os.path.join(stage, relative), relative.replace("\\", "/"))
        channel = "beta" if "-" in version else "stable"
        metadata, checksum = write_metadata(package, channel=channel)
        return package, metadata, checksum
    finally:
        shutil.rmtree(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=PROJECT_DIR)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", default=None)
    args = parser.parse_args(argv)
    for path in build_release(args.source, args.output_dir, expected_tag=args.tag):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
