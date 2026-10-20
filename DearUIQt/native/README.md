# In-process native windows (experimental)

This is a **custom Dear PyGui backend**, not a Qt/PySide binding and not a
process pool. It enables Dear ImGui's docking-branch platform viewports on
Win32/D3D11. Windows share a context, resource registry and GUI thread.

## Implemented

- Native top-level HWND per opted-in window; no subprocess or IPC.
- `QGuiRuntime.enableNativeWindows()` and `QNativeWindow`.
- Existing `QtDialog` forms use native top-levels when this mode is enabled.
- Native owner relationships, owner-specific modality and cyclic-owner checks.
- Retained widget trees on hide/show; native caption close follows the QWidget
  close-event contract for `QNativeWindow`.
- Native secondary windows move only through the Win32 title bar; Dear ImGui
  client-area dragging is disabled so dialog content never becomes a move handle.
- Explicit capability detection; stock DPG never silently pretends to support
  independent native windows.
- Build and real-window acceptance test under Abaqus Python 3.10 x64.

When an ABI-matched runtime is installed beside DearUIQt, WinUx now enables it
automatically. Reference Chart and Plot Digitizer are constructed hidden during
main-window startup; their real menu actions show the same retained native forms
without acquiring a worker or waiting for IPC. WinUx application QDialogs now
use the same in-process route by default; the process-host adapters remain only as
an explicit compatibility fallback.

## Build

Required: Git, CMake supporting the installed MSVC generator, MSVC x64/Windows
SDK, and the Python headers/import library matching `abaqus python`.

Clone Dear PyGui `v2.3.1` with its pinned submodules into a build workspace:

```powershell
git clone --depth 1 --branch v2.3.1 --recurse-submodules --shallow-submodules https://github.com/hoffstadt/DearPyGui.git <source>
abaqus python tools/build_dearuiqt_native.py --source <source> --output <isolated-runtime> --cmake "<cmake.exe>"
```

The script checks upstream commit `719d068967ace64eb9ff4171f2052a0799fd6c35`,
applies the checked-in extension, and builds against the running Abaqus Python.
Specify `--generator` if not using Visual Studio 18 2026. It never replaces
production `vendor/`. Output includes the compatible Python wrapper, compiled
extension, license notices and build identity/hash.

Run the native acceptance checks:

```powershell
abaqus python tools/check_dearuiqt_native_windows.py --native-deps <isolated-runtime>
abaqus python tools/check_dearuiqt_native_windows.py --native-deps <isolated-runtime> --winux-forms
```

Append `--hold-seconds 60` to keep the verified forms open for manual inspection.

Install the verified build for normal WinUx launches, then test the actual menu
routes without a test-only backend override:

```powershell
abaqus python tools/install_dearuiqt_native_runtime.py --runtime <isolated-runtime>
abaqus python tools/check_winux_native_dialogs.py
```

The runtime is installed under `DearUIQt/native/runtime/cp310-win_amd64/`, not in
the original `vendor/`. Close/reopen WinUx to load it. Set
`WINUX_NATIVE_WINDOWS=0` before launch to explicitly select the old runtime/hosts.
Do not change backends inside a process that already imported the old extension.

These checks verify independent visible HWNDs in the same process **and GUI
thread**, native modality/ownership, hide/show and OS-close/reopen. Process
creation is prohibited during dialog construction/interaction. A success marker
is printed only after renderer teardown completes.

## Library usage

Preload the isolated backend before importing any module that selects production
vendor packages. Then:

```python
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.widgets import QMainWindow, QNativeWindow, QLabel

runtime = QGuiRuntime()
runtime.createContext()
runtime.enableNativeWindows()  # Before viewport show; fails on stock DPG.
main = QMainWindow("Application")
runtime.createViewport(title="Application", width=960, height=640)
runtime.setPrimaryWindow(main, True)
runtime.setup()
runtime.show()

tool = QNativeWindow("Tool", owner=main, width=420, height=280)
QLabel("Same process, separate native window", parent=tool)
# The host drains the Python UI/callback queues and renders one shared frame.
```

## Remaining migration and hardening

- Retire the legacy process-host compatibility adapters after the native
  multi-window backend has sufficient production soak coverage. Public WinUx
  QDialog APIs already route through the shared-process implementations.
- Audit screen vs viewport-local coordinates throughout pointer routing,
  custom menus, tooltips, painting and dock drag/drop.
- Add interactive native keyboard/mouse/IME, DPI/multi-monitor, minimized-owner,
  modal-stack and long-running resource/renderer stress coverage.
- Promote native window policy/lifetime from the compatibility `QtDialog` forms
  into the canonical widget/application contracts.
- Package and deploy the new ABI with an explicit rollback path.

Do not remove the existing production fallback until these checks pass. A native
HWND may be recreated across hide/show by ImGui; the retained widget/resource
tree, not an immutable HWND value, is the current lifetime guarantee.
