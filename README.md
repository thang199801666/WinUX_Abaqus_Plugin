# WinUx for Abaqus/CAE

WinUx is a Windows desktop plug-in that brings local and remote file management,
SSH access, and Abaqus job tools into one workspace.

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
2. Extract the complete package into:

   ```text
   %USERPROFILE%\abaqus_plugins\WinUx
   ```

   `WinUx_plugin.py`, `run_winux.py`, `vendor`, and the `WinUx` package should
   sit directly inside that folder.
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

## Feedback

Report bugs or request features through [GitHub Issues](https://github.com/thang199801666/WinUX_Abaqus_Plugin/issues).
Use sample data and remove credentials, server addresses, and private paths from
logs or screenshots before sharing them.
