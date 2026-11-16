"""Refresh the main deployment manifest without publishing/installing a release.

Usage: abaqus python tools/build_update_manifest.py --revision 2
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from winux_runtime.update.manifest import build_manifest, source_descriptor, write_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', type=int, required=True)
    args = parser.parse_args()
    if args.revision < 1:
        parser.error('revision must be positive')
    manifest = build_manifest(str(ROOT), package_revision=args.revision)
    write_manifest(str(ROOT), manifest=manifest)
    source_descriptor(str(ROOT), verify_hashes=True)
    print('VERIFIED: {} revision {} | {} files | {}'.format(
        manifest['version'], manifest['package_revision'], manifest['file_count'], ROOT))


if __name__ == '__main__':
    main()
