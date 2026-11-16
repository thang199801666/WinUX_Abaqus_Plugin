# Changelog

## 1.1.7 - 2026-11-16

- Consolidate the current source under product version 1.1.7 (package revision 103).
- Restore the 1.1.12 DearUIQt owned-dialog host and fix interrupted message content construction.
- Preserve native dialog teardown and serialized session-tab presentation.
- Synchronize spreadsheet current cells on repeated range selection without requesting scrolling.
- Validate scroll retention across seven control types and real-controller Local/Server panes.
- Verify 21 native dialog types in normal/PiP modes, physical Login/OK/Cancel/X, 63 dialog unit tests and 42 item-view unit tests.
- Release smoke suite: 98 passed. Verify FULL and merged 1.1.6 + CHANGES-ONLY manifests, legacy bootstrap compatibility and SHA-256 checksums.
- Higher-numbered development installations require manual FULL installation; downgrade protection is unchanged.

## 1.1.5 - 2026-10-20

### Improved
- Shared Qt/Fusion-style comboboxes across Login, Settings, Job Manager, Site Manager, ODB, Reference Chart, Plot Digitizer and file selectors.
- Direct editing and history selection for Login Host and Username.
- Consistent button, line-edit, checkbox, spin-box and tab styling, with crisp borders and no inherited border shadows.
- Reduced folder-switch flicker by reusing row primitives and deferring visibility until positioning completes.

### Fixed
- Explorer-style rename: Enter and outside clicks commit; Escape cancels.
- Rename completion after creating a new file, and pointer capture cleanup.
- File selection state updates and Transfer Center resizing.
- Combo callbacks preserve their argument counts and user data.
- Popup keyboard routing and Enter handling prevent accidental Save or Run activation.

### Release packaging
- Fresh per-file integrity manifest, release metadata and SHA-256 checksum.
- Exclude development reports, examples, caches and temporary files from the installation ZIP.
