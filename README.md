# WinUx for Abaqus/CAE

WinUx is a Windows desktop plug-in that brings local and remote file management,
SSH access, and Abaqus job tools into one workspace.

Current stable release: **1.1.7**. Product version comes from `VERSION`;
DearUIQt and other bundled libraries use independent internal versions.

## Features

- Browse local and remote folders and transfer files over SFTP.
- Connect to remote servers through SSH and use an integrated console.
- Submit, schedule, and monitor Abaqus jobs.
- Edit remote text files with Server Notepad.
- Inspect ODB results and plot history output.
- Check for updates from GitHub Releases.

## Quick start

### Requirements

- Windows and Abaqus/CAE with Python 3.10 (the bundled native dependencies target
  64-bit Windows / Python 3.10).
- An SSH account on your server to use remote features.

### Install

1. Download the **FULL ZIP** from [Releases](https://github.com/thang199801666/WinUX_Abaqus_Plugin/releases).
2. The 1.1.7 FULL ZIP contains a `WinUx/` folder. Extract that folder into
   `%USERPROFILE%\abaqus_plugins\` so the installation is:

   ```text
   %USERPROFILE%\abaqus_plugins\WinUx
   ```

   `WinUx_plugin.py`, `run_winux.py`, `vendor`, and the `WinUx` package should
   sit directly inside that folder (avoid an extra nested `WinUx\WinUx` installation).
3. Restart Abaqus/CAE, then select **Plug-ins > WinUx**.
4. Connect to your SSH server to browse files, transfer input files, and manage jobs.

You can also launch WinUx from a terminal:

```bat
abaqus python "%USERPROFILE%\abaqus_plugins\WinUx\run_winux.py"
```

If your Abaqus installation uses a versioned command, set it before launching:

```bat
set WINUX_ABAQUS_COMMAND=abq2026
```

### Updates

Open **Settings > Updates** and use **Check for Updates**, then **Update Now**
when a newer release is available.

The 1.1.7 release consolidates higher-numbered development builds. If you are
running one of those builds, install FULL manually; the updater intentionally
does not bypass downgrade protection. Changes-only archives require the exact
baseline specified in their release notes.

## Feedback

Report bugs or request features through [GitHub Issues](https://github.com/thang199801666/WinUX_Abaqus_Plugin/issues).
Use sample data and remove credentials, server addresses, and private paths from
logs or screenshots before sharing them.
