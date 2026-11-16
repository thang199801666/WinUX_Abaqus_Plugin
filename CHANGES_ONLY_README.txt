WinUx 1.1.7 - changes-only package

Close WinUx before installing. Prefer the FULL archive or the built-in updater.
For a changes-only archive, merge its files into the matching baseline and
apply DELETE_THESE_PATHS.txt. Do not use it as a standalone installation.

This release restores the DearUIQt owned dialog host, fixes message content
construction and spreadsheet current-cell synchronization, and includes
regression coverage for dialog focus and item-view scroll continuity.

See README_CHANGES.txt for validation details. VERSION and update_manifest.json
are the authoritative release identity; internal library versions are separate.
