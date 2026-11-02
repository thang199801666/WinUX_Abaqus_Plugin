# Changelog

## 1.1.7 - 2026-11-02

### Improved
- Faster Plot Digitizer tick recognition with bounded caches and cancellable raster verification.
- Recognition of blurred decimal labels, faint ticks, rotated year labels and irregular date spacing without forcing numerical sequences.
- Manual endpoint calibration preserves recognized axes and confirms complete pairs together.
- Home and Data ribbon workflow, with compact canvas-local Fit Image, Actual Size and zoom controls.
- Larger overlay artwork, transparent idle backgrounds and explicit hover/pressed feedback.
- Direct Plot Digitizer launcher and reorganized runtime bootstrap package.

### Fixed
- Disabled overlay buttons no longer inherit oversized padding or clip the last icon.
- Pointer routing avoids duplicate button activation and double zoom.
- Extract stays disabled until a curve color is selected.
- Undo/Redo cancels pending background work; Smart Region and its OCR results share one history entry.
- Internal plot-box seeds are not treated as confirmed axis calibration.

### Validation and limitations
- Overlay geometry, rendered hover/press pixels, extraction pointer routing, ribbon and calibration checks passed with Abaqus Python.
- No claim is made that unreadable or fully covered axis labels can be recovered.
- An existing statusbar resize/layout regression remains unresolved.

### Installation
- Download `WinUx_1.1.7_FULL.zip` and extract into the WinUx plugin directory, or use the stable updater.
- Close WinUx and finish active transfers before replacing files.
- Includes per-file integrity checks, release metadata and a SHA-256 checksum.
- Preserves the previous public release's flat bootstrap modules for older updater compatibility.
- Development tests, documentation, tools, caches and private settings are excluded from the installation ZIP.

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
