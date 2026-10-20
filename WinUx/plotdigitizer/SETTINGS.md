# Plot Digitizer Settings

Open **Plot Digitizer → Home → Preferences → Settings** (the gear ribbon
button, visible as soon as Plot Digitizer opens). Settings is no longer a
workflow step in the left sidebar. The right panel contains three sections:

- **Canvas & markers**: toggle extracted/manual markers, pointer crosshair and
  magnifier; adjust marker size from 50% to 250%.
- **Navigation**: toggle mouse-wheel zoom and fit-on-open for new images.
- **Defaults**: reset these settings without modifying any open project.

Updates take effect immediately and are persisted per user in
`%APPDATA%/WinUX/plot_digitizer.json` on Windows (falling back to the platform
home/user profile). The file is independent of `settings.json` and `.pdg`
project data; calibration, dataset content, undo history and per-dataset
extraction values remain unchanged. Loaded projects retain their saved camera.

Preferences are deliberately implemented in WinUx (not DearUIQt), and use the
shared `JsonPreferenceStore`; the generic UI widgets stay in DearUIQt.
