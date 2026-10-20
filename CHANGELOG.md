# Changelog

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
