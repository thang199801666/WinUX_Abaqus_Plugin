# WinUx Abaqus/CAE plug-in

## Latest changes

- **Single-session SSH recovery**: WinUx now authenticates one SSH Transport per login and multiplexes SFTP, Console, qstat, transfers and ODB work through channels on that Transport. A single connection supervisor repairs stale channels in place, performs clean reconnect with backoff only when the Transport is actually dead, and keeps overdue schedules pending for catch-up. Schedule manifest mutations are journaled locally so temporary outages do not discard scheduled work.
- **Shared DPG scroller**: Rounded Qt-like track with two interactive end buttons. The scrollbar smoothly expands on hover and collapses when the pointer leaves, without shifting content. Supports button press-and-hold, track page clicks and thumb dragging on both axes.

WinUx adds **Plug-ins > WinUx** to Abaqus/CAE. The local plug-in directory is a
complete self-contained deployment and is always the copy that runs. The shared
S: deployment is used only as an update source.

Default shared deployment:

```text
S:\Division1\CAE\1. FEA\6. Tools\17.WinUx\WinUX_Abaqus_Plugin
```

## Startup / update flow

When **Plug-ins > WinUx** is selected:

1. A fresh bootstrap child is started **every time the menu command is selected**, even when WinUx is already running. The bootstrap always performs the version/source check before deciding whether to launch a new application instance.
2. The launcher resolves the configured update source.
3. If the configured folder cannot be found or is not a complete WinUx
   deployment, a native **WinUx Update Source** dialog is shown with a textbox.
   Enter the replacement folder and choose **Save Path**. The path is stored as
   `update_source` in the user's WinUX `settings.json`. Choose **Use Local** to
   skip the network check and start the current local version.
4. The bootstrap reads the shared `VERSION` directly on every launch. A stale
   or missing manifest cannot hide the fact that a newer version exists. A valid
   `update_manifest.json` remains the preferred integrity/publish record and
   contains the release file list, sizes and SHA-256 checksums.
5. If the shared `VERSION` is newer than the local `VERSION`, a native
   **WinUx Update** dialog is shown with **Update Now** and **Cancel**.
6. **Cancel** leaves the local deployment untouched and starts that current
   version immediately.
7. **Update Now** opens an **Updating WinUx** dialog, acquires a deployment
   update lock, copies only manifest-declared files to a sibling staging
   directory, verifies every SHA-256 checksum, atomically swaps the staged
   release into the local path, runs a post-install health check, and only then
   removes the backup and starts WinUx.
8. If copy/checksum/install/health-check fails, the known-good local deployment
   is retained or restored and WinUx starts from the old version after a warning.

The runtime command therefore always uses the **local** runner, for example:

```text
abaqus python "%USERPROFILE%\abaqus_plugins\WinUx\run_winux.py"
```

## Persisted update source

The updater stores its source path in the same per-user settings document used
by WinUx:

```text
%APPDATA%\WinUX\settings.json
```

(`%LOCALAPPDATA%` is used as a fallback.) Existing settings keys are preserved.
The entry looks like:

```json
{
  "update_source": "S:\\Division1\\CAE\\1. FEA\\6. Tools\\17.WinUx\\WinUX_Abaqus_Plugin"
}
```

The update-source resolution order is:

1. explicit development/test override;
2. `WINUX_UPDATE_SOURCE` environment variable;
3. the canonical S: deployment above, probed on every plug-in launch;
4. saved `update_source` setting only when the canonical S: path is unavailable.

For troubleshooting, `WINUX_SKIP_UPDATE=1` disables all update checks and update
UI for that launch.

## Versioned deployment

Both local and shared deployments use a root-level `VERSION` file. Published
shared releases also use `update_manifest.json`. A shared release is considered
newer only when its semantic version is greater than the local version. Do not
use file timestamps as the release version.

`update_manifest.json` contains a package digest and one SHA-256/size record per
file. Publish this manifest **last** after all release files have been copied to
the S: drive. That prevents clients from consuming a half-published release.
The manifest also supports `release_path`, so the update source can later point
at immutable folders such as `releases\1.4.0` without changing the client.

A complete deployment contains:

```text
<deployment>
|-- VERSION
|-- update_manifest.json
|-- WinUx_plugin.py
|-- winux_launcher.py
|-- winux_updater.py
|-- winux_update_ui.py
|-- winux_update_manifest.py
|-- winux_update_lock.py
|-- winux_update_installer.py
|-- run_winux.py
|-- install.py
|-- WinUx.png
|-- vendor\
`-- WinUx\
```

The local copy normally lives at:

```text
%USERPROFILE%\abaqus_plugins\WinUx
```

The shared copy normally lives at:

```text
S:\Division1\CAE\1. FEA\6. Tools\17.WinUx\WinUX_Abaqus_Plugin
```

After the initial local installation, future releases require publishing a new
complete shared package with a higher `VERSION` and a matching manifest. The
manifest must be generated after the package is complete and copied to the
update-source root last.

For a flat shared deployment, generate the publish marker with:

```text
python tools\build_update_manifest.py .
```

Run this only after the S: deployment has finished copying.

A deployment-scoped lock is stored under `%LOCALAPPDATA%\WinUx\locks`. This
prevents two Abaqus/CAE instances from swapping the same local installation at
the same time. Stale locks are recovered automatically.


## Server Notepad

The Server file list includes **Edit in WinUx Notepad** for one selected server
file up to 8 MiB. The editor is a process-isolated Tkinter desktop window with
its own `tk.Tk()`/mainloop, while SSH/SFTP stays in the main WinUx process. A
Tk/editor failure therefore cannot terminate WinUx or Abaqus. No local working
copy is created.

The UI follows a Notepad++-style layout: menu bar, compact icon toolbar,
multi-file tabs with a close `x` hit area, line-number/bookmark gutter, dockable
**Document List**, optional **Function List**, current-line highlight, editor
context menu, Find/Replace, Go To Line, word wrap, zoom, encoding/EOL controls,
and a segmented status bar with load progress, length/line/column, format,
language and zoom information. `Ctrl+Tab` / `Ctrl+Shift+Tab` switch documents;
`Ctrl+F2`, `F2`, and `Shift+F2` manage bookmarks. Basic syntax highlighting is
included for Abaqus INP, Python, JSON, XML/HTML, C/C++, Fortran, Shell and YAML.

Opening is sequential like a desktop multi-document editor: tabs are queued and
only one server file is read at a time. The current pipeline starts showing text
while SFTP is still reading: **SFTP prefetch -> incremental decoder -> bounded/compressed
256 KiB IPC frames -> background decompression -> time-sliced Tk rendering**. The child IPC queue is bounded,
so a fast server cannot flood the editor with unbounded data. Tk rendering now
adapts between 16 and 256 KiB per slice to target only a few milliseconds of
Tcl insertion time, yielding between slices,
which keeps expose, move, scroll, and close events responsive while a file is
opening. Files at or above 2 MiB automatically enter **Performance mode**:
undo bookkeeping is disabled during load while an immutable Python-side line/function
index is built on a worker thread. Find All and Function List can therefore operate
off the Tk/Tcl rope for an unmodified large document. Visible-region syntax
highlighting remains enabled because it only lexes the viewport plus a margin.
Progress/status UI is throttled, and dirty-state tracking no longer copies the
entire text buffer after every keystroke.

Save is transactional: WinUx checks the SHA-256 signature captured when the file
was opened, writes the edited text to a sibling temporary file, verifies the
staged bytes, preserves the original Unix permission bits, then publishes the
file with an atomic rename. If another process/user changed the server file
after it was opened, normal **Save** is rejected. Use **Reload from Server** to
inspect the server copy or **Force Save** only when intentionally overwriting
that change.

Supported text encodings are UTF-8, UTF-8 BOM, UTF-16 LE/BE with BOM, and a
lossless Latin-1 fallback for legacy text. EOL conversion supports Windows
CRLF, Unix LF and classic Mac CR. Files containing binary NUL bytes are rejected
instead of being corrupted by the editor. Common shortcuts include **Ctrl+S**,
**Ctrl+Shift+S**, **Ctrl+F**, **Ctrl+H**, **Ctrl+G**, **Ctrl+R**, **Ctrl+W**,
**F3** and **Shift+F3**.

## Abaqus command

If the site uses a versioned Abaqus command, set for example:

```text
WINUX_ABAQUS_COMMAND=abq2026
```

The launcher still accepts the legacy `WIXUX_APP_DIR`,
`WIXUX_ABAQUS_COMMAND`, and `WIXUX_LAUNCH_LOG` names for migration.

## Logs

Launcher output:

```text
%LOCALAPPDATA%\WinUx\logs\winux_abaqus_launcher.log
```

Update checks and copy/swap operations:

```text
%LOCALAPPDATA%\WinUx\logs\winux_update.log
```

## Abaqus-safe updater lifecycle

The Abaqus plug-in only spawns the independent `abaqus python run_winux.py` child and immediately returns control to Abaqus/CAE. Version checking, Update Now/Cancel dialogs, update-source selection, progress UI, staging, rollback, and WinUx itself all run in that child process. This prevents updater dialog close/application shutdown from disabling or blocking the Abaqus main window.

The launcher also starts the child with the deployment **parent** as its working directory. The child temporarily changes to `%TEMP%` before replacing the local deployment, avoiding Windows directory locks during the atomic staging/swap.

## v1.4.2 — Process-isolated Server Notepad

- Server Notepad now runs as a standalone Tkinter window in its own child process.
- Server files are queued and loaded one-at-a-time through the existing WinUx SFTP backend.
- Large editor buffers are inserted incrementally to keep the window responsive.
- A Notepad crash is isolated from the main WinUx/Abaqus process; diagnostics are written to the WinUx temp log folder.

## v1.4.3 — Faster Notepad++-style Server Notepad

- Added dockable Document List and optional Function List panels.
- Added current-line highlighting, editor context menu, Window/Settings menus, Ctrl+Tab document switching, and richer status information.
- Remote editor reads now use pipelined/prefetched SFTP reads and reuse the initial lstat as the stable before-state to reduce server round trips.
- Large snapshots are streamed to the Tk child process in 256 KiB IPC chunks instead of one large JSON message.
- Syntax highlighting now lexes the visible viewport plus a margin instead of rescanning a large fixed prefix after every edit/scroll.
- Dirty tracking uses the editor modification save point instead of copying the full Tk buffer on each key event.
- Load completion reports transfer size, elapsed time and effective MB/s in the status bar.

## v1.4.4 — Responsive streaming Server Notepad

- Server files now stream directly from the prefetched SFTP reader into the editor instead of waiting for a complete in-memory snapshot.
- Parent/child IPC uses bounded 128 KiB frames and a bounded queue to provide backpressure.
- Tk rendering is time-sliced into 64 KiB inserts with a per-frame budget so opening a file cannot monopolize the UI loop.
- Files >= 2 MiB automatically use Performance mode: undo history is disabled during initial population and syntax/function scanning is deferred.
- Added Notepad++-style tab close hit areas, clickable gutter bookmarks, Ctrl+F2/F2/Shift+F2 navigation, compact resource-backed toolbar icons, and an opening progress indicator.
- Status reporting separates server-read progress from editor-buffer rendering and still reports final MB/s.


## v1.4.5 — Notepad++-style UI + lower-latency server loading

- Toolbar is now compact/icon-first and uses WinUx-owned transparent PNG editor icons generated for Open Server Path, Save, Save All, Reload, Find, Replace, Go To Line and Bookmark.
- Added **Open Server Path (Ctrl+O)** inside the editor so additional remote files enter the same sequential tab/load queue without returning to the main Server List View.
- Added a docked **Search Results** panel and time-sliced **Find All in Current Document** so a large search does not monopolize the Tk event loop.
- Initial SFTP encoding probe is reduced to 64 KiB so the first visible text can arrive sooner; subsequent reads use 1 MiB blocks while Paramiko prefetch keeps up to 64 requests in flight.
- Parent-to-editor IPC frames increased to 256 KiB and compress source/code text with zlib level 1 when beneficial. Decompression runs on the child reader thread, not the Tk mainloop.
- Child IPC queue is bounded to 24 frames and the UI consumes at most four messages per pump cycle, maintaining backpressure while reducing repaint bursts.
- Load progress/status updates are throttled to roughly 12.5 Hz. Large-file visible-region syntax highlighting remains available while expensive whole-document Function List extraction stays deferred.
- Generated icon masters were background-removed and downsampled to 64x64 transparent PNG resources; the toolbar subsamples them at runtime for high-DPI clarity.

## v1.4.6 — Server Notepad mixed-version compatibility fix

- `ServerNotepadDialog` now accepts both the current sequential-load constructor contract and the legacy eager-snapshot contract used by v1.4.0/v1.4.1.
- Prevents `ServerNotepadDialog.__init__() missing ... on_load` when a changed-files-only patch is applied over an older local WinUx installation.
- Legacy snapshots are converted into the same bounded IPC stream used by the current editor instead of reopening the file through a second code path.
- Missing callbacks are guarded so a mixed installation reports a restart/update error instead of crashing.
- Changed-files packages now include `view.py` and `controller.py` together with the dialog facade so constructor/call-site contracts stay synchronized.



## v1.4.7 — Responsive large-file indexing + compact Notepad++ chrome

- Toolbar spacing and icon size were reduced again to a dense desktop-editor layout; the redundant right-side `Direct server editor` label was removed.
- Status-bar length and line count are separate fixed sections, preventing the truncated `length / lines` field seen with large INP files. The load progress bar is visible only while a file is actually opening/reloading.
- The line-number gutter automatically grows with document line count instead of permanently reserving a wide fixed margin.
- Added per-user editor state under `%LOCALAPPDATA%\WinUx\server_notepad_state.json`: window geometry, zoom/font size, view toggles and up to 10 **Recent Server Files**.
- Added Notepad++-style tab context actions: **Close Other Tabs**, **Close Tabs to the Right**, and **Copy Full Server Path**.
- Added **Duplicate Current Line (Ctrl+D)** and **Delete Current Line (Ctrl+L)**.
- Large-file rendering now uses an adaptive 16–256 KiB insert batch that grows on fast machines and shrinks on slower/RDP sessions based on measured Tcl insertion latency.
- Streaming load simultaneously builds a Python-side immutable snapshot. A worker thread constructs line offsets and Function List entries after load without scanning the Tk widget.
- **Find All** on an unmodified indexed document runs in a worker thread with O(log n) offset-to-line mapping, then posts results back to the Search Results dock in short UI batches.
- Save preparation no longer calls one giant `Text.get()` on the Tk thread. The editor extracts 256 KiB slices, joins them off-thread, and the child IPC writer performs zlib/base64 + JSON serialization off the Tk mainloop. The parent decodes the payload on its reader thread before invoking the existing atomic SFTP save path.
- Closing the editor releases large snapshot/index buffers immediately.
## WinUx 1.5.2 - Modern dialogs and WinSCP-style keyboard workflow

This release introduces a shared native Tk dialog framework for confirmations,
errors, overwrite prompts and transfer actions. Dialog footers use deterministic
pixel-sized action slots so primary/secondary buttons remain aligned across
Windows DPI and Abaqus embedded-Python themes. Permanent delete and application
exit prompts now use explicit **Delete** / **Exit** actions instead of generic OK.

The Local/Server file panes also support a first WinSCP-style keyboard set:
**F4 Edit**, **F5 Transfer to the opposite pane**, **F7 New Folder**,
**Ctrl+R Refresh**, **Alt+Up Parent**, together with the existing **F2 Rename**
and **Delete** shortcuts. These shortcuts reuse the same controller pipelines as
context-menu operations, including overwrite/conflict handling.


## v1.5.11 — Side-by-side Job Viewer / Plots workspace

- Docked **Plots** now shares the lower workspace horizontally with **Job Viewer** instead of consuming a second row underneath it.
- Job Viewer and Plots open at an equal **50/50 width** by default and keep the same height/alignment.
- Added a thin **vertical splitter** with an expanded invisible grab zone and native ResizeEW cursor; dragging it resizes both panes live while preserving sensible minimum widths.
- The chosen split ratio is retained while the tool is open. **Undock** expands Job Viewer back to the full lower width; **Dock Back** restores the previous Job Viewer/Plots split without restarting the realtime ODB monitor.
- Reduced the History Output list width inside the plot tool so the chart canvas remains useful when Plots occupies half of the lower workspace.


## v1.5.12 — Qt-like dock widget chrome for Job Plots

- Added a reusable **DockWidget** component that reproduces the compact desktop behavior of a Qt `QDockWidget` without adding a Qt runtime dependency.
- Docked **Plots** now has a framed title bar with the title on the left and compact **Float** / **Close** controls on the right, replacing the large text buttons in the plot toolbar.
- Dragging the dock title bar still tears the live plot out into a floating tool window. When floating, the embedded dock title bar is hidden so the detached window uses a single top-level title bar instead of duplicated chrome.
- Dragging a moved floating Plot window back over the **Job Viewer** workspace and releasing it docks the same live component back into the 50/50 lower split, similar to Qt dock-widget drag-back behavior.
- The dock title controls remain right-aligned during splitter dragging, viewport resize and DPI/layout updates.

## v1.5.18 — QDockWidget behavior polish

- `DockWidget` now exposes Qt-style **Closable / Movable / Floatable** feature flags so future WinUx tool docks can share one behavior contract instead of hard-coding title controls per panel.
- Right-clicking the dock title area opens a compact desktop-style **Float / Close** menu, and long dock titles are elided before they can overlap the title-bar controls.
- Drag tear-off now preserves the exact mouse grab point and inherits the current dock size, eliminating the visible jump that occurred when a dock became a floating window.
- Floating geometry is remembered for the current session. Re-floating via the title button/menu restores the previous detached size and position instead of resetting to a fixed 900x500 window.
- Pressing **Esc** during an active floating-dock move cancels the gesture and returns the panel to its previous dock area.
- Existing double-click dock/float behavior, dock-target preview, input shielding and splitter isolation remain intact.

## v1.5.19 — Qt dock areas and directional snap preview

- `DockWidget` now exposes Qt-style **Left / Right / Top / Bottom** dock-area flags in addition to Closable / Movable / Floatable features.
- The dock title menu now provides **Dock Left, Dock Right, Dock Top, Dock Bottom** commands and reflects the current dock area.
- Dragging a floating Plot over the Job Viewer workspace selects the **nearest dock edge** and shows a translucent preview for the exact target area before release.
- **Left/Right** docking uses a vertical ResizeEW splitter; **Top/Bottom** docking automatically switches to a horizontal ResizeNS splitter.
- Each dock area remembers its own split ratio, so returning from Bottom to Right restores the previous Right-side width instead of reusing a height ratio.
- Top/Bottom docking reserves a larger minimum lower workspace and constrains the main horizontal splitter so Job Viewer and Plots do not collapse into unusably short panes.
- Double-clicking a floating title bar and pressing **Esc** during a dock drag still return the panel to its previous dock area. Realtime ODB plotting continues without restarting during all reparenting operations.


## v1.5.20 — QMainWindow-style DockManager and tabified Job Plots

- Added a reusable **DockManager** above `DockWidget`, separating single-panel chrome from main-window dock orchestration and making future WinUx tool docks share one Qt-like docking model.
- Several Job Viewer **Plots** docks can now stay open at the same time. Docked jobs are automatically **tabified** instead of closing the previously opened Plot panel.
- The shared Plot dock area gets a compact Qt/Fusion-style tab strip. Clicking a tab raises that live dock without restarting its ODB monitor; inactive docks remain registered but hidden until selected.
- Each Job row keeps its own **Plots** checkmark while its plot is open, including floating windows and inactive tabs.
- Floating one tab no longer collapses the whole Plot dock area. Remaining docked tabs stay visible and the next available tab becomes active automatically.
- Docking a floating Plot back into Left/Right/Top/Bottom rejoins the same tab group. Moving a tabified dock group to another area keeps the group's orientation-aware splitter and per-area split ratio.
- `DockManager` exposes reusable Qt-like operations including `add_dock_widget`, `remove_dock_widget`, `tabify_dock_widget`, `raise_dock_widget`, `set_dock_area`, `set_floating`, `save_state`, and `restore_state`.
- Plot dock layout is now flush to its host region with zero parent padding so the title chrome, client area and tab strip align consistently with the surrounding splitter edges.


## v1.5.21 — QTabBar drag, reorder, tear-off and center tabify

- Tabified dock groups now support **drag-to-reorder** with a thin live insertion marker, matching the interaction model of Qt `QTabBar::moveTab`.
- Dragging a dock tab outside the tab strip tears **only that dock** into a floating tool window; sibling tabs remain docked and keep their live ODB monitors running.
- Tear-off is gesture-continuous: the newly created floating window follows the same held mouse press even though the press started on an embedded tab/title bar, avoiding the stop-and-regrab behavior of earlier Dear PyGui reparenting.
- While a tab is being reordered or torn off, the dock manager takes exclusive pointer ownership so Explorer selection, rubber-band selection and splitters underneath cannot react to the same drag.
- A floating dock dropped over the **center of an existing Plot dock group** now tabifies into that group. Dropping near the outer workspace edges still selects Left/Right/Top/Bottom docking.
- `DockManager` adds reusable `tab_order`, `reorder_dock_widget` / `move_tab`, `update_interaction`, tab-tearoff callback and order-change callback APIs for future docked tools.
- Existing double-click dock/float behavior, Esc cancellation, floating geometry memory, input shielding and per-area split ratios remain intact.

## v1.5.22 — Precise splitter gesture ownership

- Explorer/Job Viewer mouse gestures now use **owner-aware pointer capture**. Once a press is accepted by a list/header, every unrelated global mouse poller is blocked until that physical gesture ends, matching Qt mouse-grab semantics.
- Dragging a **Job Viewer column header or column separator** can no longer move the main top/bottom splitter or the Job Viewer/Plots dock splitter underneath it, even if the pointer crosses a splitter while the button remains held.
- Header drags are locked to the header. A drag that starts on a sortable header cell no longer falls through into body rubber-band/item dragging.
- Main horizontal splitter acquisition is now strict: it can start only from the real Dear PyGui splitter hitbox on the initial press. The previous mixed screen/local-coordinate fallback is retained only for diagnostics and no longer starts a resize, eliminating false splitter captures on mixed-DPI layouts.
- Existing dock/tab drag ownership, floating-dialog shielding, splitter orientation, and realtime Plot behavior remain unchanged.

## v1.5.23 — Windows 11 floating dock chrome and four-corner resize

- Floating Plot docks now use **8 px rounded outer corners** and a thin neutral border, bringing their detached appearance closer to Qt on Windows 11.
- Removed Dear ImGui's visible **lower-right triangular resize grip**. Detached docks are created with native DPG resizing disabled and use WinUx border hit-testing instead.
- Added reusable `FloatingWindowResizer`, supporting all **four corners plus four edges** with the correct diagonal/horizontal/vertical resize cursors.
- Resize gestures use exclusive pointer ownership before application splitters poll mouse state, so resizing a floating dock cannot drag Job Viewer/File View splitters underneath it.
- North/west corner resizing may move the floating window origin; dock drag-back detection explicitly ignores that geometry movement while a resize is active.
- The existing minimum floating Plot size, geometry memory, title-bar drag, double-click dock-back, tab tear-off and realtime ODB behavior remain unchanged.

## v1.5.27 - Qt widget behavior pass

This release continues the Qt/Fusion migration at the interaction level rather
than only matching colors and spacing:

- Explorer/ListView now tracks a Qt-like current index independently from the
  selection, including inactive-selection and keyboard-focus rendering.
- Up/Down/Home/End/PageUp/PageDown, Shift range selection, Ctrl current-index
  movement and Ctrl+Space selection toggling follow QAbstractItemView-style
  behavior.
- Header sections now expose hover and pressed states closer to QHeaderView.
- Context menus use compact QMenu styling and support Up/Down/Left/Right,
  Enter and Escape navigation, including submenus.
- QtComboBox now supports outside-click dismissal, Escape/F4/Alt+Arrow and
  Up/Down/Enter keyboard operation, disabled-state styling and compatibility
  with both newer and older Dear PyGui focus-state APIs.

## v1.5.28 - Qt dialog semantics and QHeaderView precision

- Native Tk dialogs now share a reusable **QDialog-style action contract**. Primary `FixedActionButton` controls register as the default action, while Cancel/Close-style actions register as the reject action. Enter activates the default action unless the focused editor/item view owns Enter; Escape activates the reject action unless a dialog has an explicit override.
- `FixedActionButton` now exposes deterministic `invoke()` and default-button focus framing, so dialog keyboard behavior no longer depends on the active Windows/Abaqus ttk theme.
- Standard native widgets were tightened toward Qt/Fusion: generic `TButton`, radio buttons, spin boxes, scrollbars and progress bars now use the shared palette, while classic Tk Text/Listbox/Menu controls inherit the same selection/focus colors through the option database.
- Added reusable **QTreeView-style behavior** for native result/bookmark tables: focus-current-row handling, Ctrl+A extended selection, Ctrl+Space toggling, and optional Enter/F2/Delete actions. Bookmarks, ODB extraction/result tables, ODB check results and synchronization preview now use the common behavior.
- Native Tk popup menus used by ODB tools now use the same compact Qt/Fusion menu palette instead of the host Tk theme.
- Explorer/Job Viewer headers now behave more like **QHeaderView**: sorting is committed on mouse release over the same section rather than on mouse-down, so pressing or dragging a header cannot accidentally change sort order.
- Column separator resize now changes **only the grabbed section**, instead of silently consuming width from the neighboring column. This removes the imprecise coupled-resize feel and allows the horizontal extent to grow naturally.
- Double-clicking a column separator performs **resize-to-contents**, with filename/icon allowance and a practical maximum width for very long remote paths.

## v1.5.47 - Qt top-level window state and tool-window semantics

- Native dialog geometry now uses the Win32 **normal window placement** while a window is maximized, matching `QWidget::saveGeometry()` more closely. Restoring from a maximized session no longer persists the maximized desktop rectangle as the future normal size.
- Minimized/iconic geometry is treated as transient and is never allowed to overwrite the last valid normal/maximized placement.
- `NativeDialogController` now centralizes **minimize, maximize, restore and toggle-maximize** commands in addition to show/activate/focus/hide, giving native top-levels one Qt-like lifecycle/state API.
- Hidden long-lived windows save their current geometry before `withdraw()` and reload the last normal size/state before they are shown again. Parent-centering is retained for WinUx dialogs without corrupting maximized restore geometry.
- The native chrome layer now supports explicit `dialog`, `tool` and standalone `window` roles. `Qt::Tool`-style windows use `WS_EX_TOOLWINDOW`, stay owned by WinUx, stay out of the taskbar and do not expose independent minimize/maximize controls.
- **Transfer Center** now uses the tool-window role, and its native title-bar close button routes through `owner.hide` rather than bypassing the shared lifecycle with a raw Tk `withdraw()` call.

## v1.5.48 - Native dialog button/input hotfix

- Fixed a regression from v1.5.47 where normal Tk/QDialog-style windows had their extended Win32 style rewritten after creation. Ordinary dialogs now preserve Tk's native extended wrapper style; only explicit `Qt::Tool` windows receive `WS_EX_TOOLWINDOW` changes.
- Native modal dialogs now explicitly keep their own HWND enabled before and after mapping while only the owner window is disabled. This restores reliable mouse activation/click delivery to dialog controls in embedded Tcl/Tk/Abaqus hosts.
- SSH Login now sizes its fixed client area from the layout's requested size instead of capping it at the historical 420x236 nominal rectangle. `Connect` and `Cancel` therefore remain visible at different DPI/font metrics.
- Added regression coverage for dialog HWND interactivity, extended-style preservation and Login button-box clipping.

## Dear PyGui Qt-like dialog migration

The main WinUx dialog API uses `FloatingDialogController` with independent native
viewports. Client areas use `WinUx/dialogs/qt_dialog.py`. `QtDialog` supplies a scrollable body, a pinned
right-aligned button box, minimum sizing that keeps action buttons visible,
default-action Enter, Escape rejection, and UI-queue-safe lifetime management.
`QtTable` supplies stable row selection and current-index/range keyboard actions.

Migrated dialogs: SSH Login, messages/confirmations/text input, Server Folder,
Progress, Bookmarks, Site Manager, Synchronization Preview, Diagnostics, Settings,
Job Manager, Job Schedule, Job Edit, ODB Check, ODB History Extract/XY Results,
SSH Console and Transfer Center. Public constructor/callback/progress-handle APIs
are retained. The console's historical `tk_console_dialog` import path now
exports the Dear PyGui implementation.

These dialogs are owned native top-level windows with their own Windows HWNDs.
Modal dialogs shield the owner; background results are delivered
via `view.after` and discarded after close. Transfer Center can be hidden while
its task handles continue running, and high-frequency progress updates remain
coalesced. Existing scheduling/submission/transfer helpers are reused from the
`legacy_*` modules; their Tk window implementations are not instantiated by the
new dialog API.

The process-isolated Server Notepad editor and its child-process prompts continue
to use their standalone editor backend. `dialogs/modern.py` remains available to
that process and native integrations.

Migration coverage uses real Dear PyGui widgets with Tk root creation blocked:

```text
abaqus python -m unittest discover -s tests -p test_dpg_dialog_migration.py -v
```

Use the bundled `vendor` directory on `PYTHONPATH` when running outside the WinUx
launcher.

## Fast application startup

The bootstrap still checks shared `VERSION` on every plug-in launch. It now uses
a per-launch discovery snapshot: source normalization, source availability and
version comparison share a single read of the remote marker. If the local version
is already current, startup does not load the shared manifest or stat the release
file list. Manifest-only immutable sources remain supported, and a newer version
still follows manifest validation, confirmation, update lock, staged checksum
verification and rollback. The version is read again after acquiring the lock;
there is no cache carried between launches.

`get_update_status()` exposes `manifest_checked`: `False` means manifest validation
was unnecessary for a current version, rather than declaring the manifest invalid.
The main view resolves dialog constructors only when a dialog is opened, so its
startup import does not initialize dialog forms or legacy Tk helper modules.

Launcher timings include per-stage and total elapsed seconds. Update diagnostics
include check duration and whether the manifest was examined. This separates slow
SMB/source checks from interpreter, module-import and viewport initialization time.

## Shared floating Qt-like dialog host

SSH Login now uses `FloatingDialogController` and an independent Dear PyGui
viewport in a child started by `abaqus python`. Its Win32 HWND is an **owned
top-level window**, never `WS_CHILD`: the native title bar can be dragged outside
WinUx and between monitors without viewport clipping. WinUx is disabled only
while the modal Login is open; success, cancel, child failure and startup timeout
release the owner/input gate. SSH and preference saving remain in the main process.

The form uses editable `QtComboBox` controls for Host and Username: each history
arrow belongs to the same field rather than occupying an extra empty row. The
native window has one title bar, a compact client area and a pinned button box.
Communication uses bounded JSON messages over authenticated localhost IPC because
Abaqus launchers can redirect child stdio. Startup diagnostics are written to
`%TEMP%\WinUx\logs\floating_dialog_login.log`.

All 17 main modal/modeless dialog types now use the shared floating host. Public
modules export application-side adapters from `floating_adapters.py`; the
`*_form.py` modules contain client-area widgets, selected by `floating_forms.py`.
Each dialog has its own native title bar, border resize and independent desktop
position. Native X and Escape share one close/reject policy. Closing Transfer
Center hides it without stopping its tasks; showing it restores the same window.
Modeless dialogs do not disable WinUx, and nested prompts are owned by their
calling dialog. Closing or hiding an active dialog returns keyboard/foreground
focus to that captured parent after the child HWND disappears. Background closes
preserve another dialog's focus, and a parent blocked by another modal is never
reactivated. Application shutdown suppresses focus return while closing every
registered floating dialog.

SSH, server-folder searches, job submission, schedules and transfer task models
remain in the main application. Commands and large payload serialization use a
bounded background writer; transfer progress is coalesced before IPC. The
protocol preserves Path/PurePosixPath values, datetime schedules, and path-keyed
CPU suggestions, and accepts ODB payloads up to 32 MiB. Result delivery completes
before the child closes, including Cancel/Close results.

### Responsive dialog opening

After the main window's first frames, WinUx asynchronously prepares a bounded
pool of two idle dialog workers. Each has already started through `abaqus python`,
loaded the form modules/fonts and initialized a cloaked, hidden graphics viewport.
Opening a dialog leases a ready worker without waiting on preparation or a pool
lock, then builds/centers/reveals the real form. This applies to Exit warnings,
confirmations, Login and the other floating dialog types.

Workers are leased once, so modal state, callbacks and large document data do not
carry over to another dialog. Consumed slots refill in the background; when no
worker is ready, the existing cold-start path remains available. Idle workers
never acquire application modality/pointer ownership, and application shutdown
retires both idle workers and active dialog processes. Invisible layout frames
run without vsync, while normal rendering restores vsync. IPC uses TCP_NODELAY
for small interactive messages.

The application log records each dialog's cold/warm source and click-to-ready
duration. Test the pool and Exit warning response with:

```text
abaqus python -m unittest discover -s tests -p test_dialog_prewarm.py -v
```

Dialog captions and editor fallback controls use ASCII text instead of special
Unicode arrows, checkmarks, multiplication signs and bullet separators. Server
Notepad already uses a standalone native modeless window; it now declares the
same floatable contract and participates in HWND pointer-input shielding.

Run regression and real Win32 floating-window checks with:

```text
abaqus python -m unittest discover -s tests -p test_all_floating_dialogs.py -v
abaqus python -m unittest discover -s tests -p test_floating_login.py -v
abaqus python -m unittest discover -s tests -p test_dpg_dialog_migration.py -v
```

### Modern client areas and first-frame placement

The Dear ImGui client areas now share the modern Tk-era layout vocabulary:
Segoe UI headings, white framed sections, aligned label/editor rows, 82x28 action
buttons and a pinned footer. Login uses a Connection card; Job Edit has separate
summary/schedule cards; Job Manager separates Estimate from Run/Cancel; Settings
uses General/Abaqus Versions/Saved Login pages with a navigation rail. These
controls are Dear PyGui widgets; no Tk window is created for these dialog forms.

Startup is now `build -> cloak -> configure -> warm up -> center -> reveal`.
A current-thread Win32 creation hook cloaks the viewport before its first
ShowWindow. Fonts, initial data, native owner/chrome and content sizing settle
while cloaked; the actual outer HWND rectangle is centered on the captured
parent before a single compositor reveal. Initially hidden tool windows stay
hidden, and subsequent activation does not show or recenter an already-visible
window. Centering supports negative monitor coordinates and work-area bounds.

The implementation is separated into:

- `services/floating_dialog_process.py`: Abaqus entry point and authenticated connection;
- `dialogs/floating_runtime.py`: child UI queue, prepare/publish lifecycle and command dispatch;
- `platform/floating_viewport.py`: invisible HWND creation, chrome, geometry and native close;
- `platform/dialog_focus.py`: deferred owner activation and focus queries;
- `dialogs/qt_dialog.py` / `dialogs/theme.py`: shared Dear ImGui layout and styling.

Native integration tests inspect DWM cloak state during initial ShowWindow and
compare the prepared and first-published rectangles for every dialog type.

### Compact dialog sizing

Shared dialogs use 10 px body margins, 5 px row spacing, 28 px action buttons and
a 48 px pinned footer. Login, messages/input prompts, bookmarks, Job Edit, Site
Manager, Server Folder and progress windows provide compact initial size hints.
The size hints are applied while the native window is cloaked, before centering.

Job Manager sizes its initial height from the selected input-file count, showing
at most seven rows before scrolling. One input file opens in an approximately
230 px high native window rather than reserving a tall empty table. Only the
filename column stretches; checkbox, CPU, version, precision and schedule columns
have compact widths, while the date/time editor keeps enough space for a full
timestamp. Hovering a filename shows its full path.

## v1.5.53 - CMD-style inline SSH console

- Reworked SSH Console as a single protected terminal transcript with the editable command rendered inline immediately after the remote SSH prompt; there is no detached command textbox.
- Added command-line editing expected from a Windows command window: Left/Right, Ctrl+Left/Ctrl+Right word jumps, Home/End, Delete/Backspace, Up/Down history, Ctrl+V single-line paste and Ctrl+C interrupt.
- Updated the terminal presentation to classic CMD/conhost styling with a pure black client area, Consolas terminal font when available, neutral gray text, compact padding, square scrollbars and a low blinking caret.
- Improved terminal stream cleanup so ANSI formatting is removed, CRLF remains a newline and bare carriage-return progress redraws no longer concatenate stale text.
- Added headless regression coverage for inline prompt layout, cursor edits, history/draft restoration, paste normalization, tab/caret positioning and carriage-return cleanup.

## v1.5.54 - SSH console prewarm crash fix

- Fixed the SSH Console failing to open during floating-dialog prewarm with ``<built-in function draw_text> returned a result with an exception set``.
- Dear PyGui ``draw_text`` is now created only with supported native arguments; Consolas is applied afterward through ``bind_item_font`` instead of being forwarded as an unsupported ``font`` keyword.
- Font application is fail-safe: if a Dear PyGui build rejects per-draw-item font binding, the console still opens using the globally bound font rather than aborting the dialog process.
- Added regression coverage that prevents reintroducing the unsupported ``draw_text(font=...)`` path.

## v1.5.55 - SSH console child-window click handler fix

- Fixed SSH Console prewarm failing with Dear PyGui Error 1000 when ``mvClickedHandler`` was bound to the terminal ``mvChildWindow``.
- Removed the child-window ``item_handler_registry`` click binding entirely. The console now uses a normal global mouse-click handler and focuses the terminal only when the terminal child/drawlist is hovered, which is compatible with Dear PyGui 2.3.1 floating dialogs.
- Console focus now targets the dialog window so Qt-style keyboard shortcut dispatch and native ``WM_CHAR`` input remain aligned with the inline terminal editor.
- Preserved the CMD-style inline prompt, protected transcript, caret editing, command history, paste and Ctrl+C interrupt behavior from v1.5.53/v1.5.54.
- Added a regression guard that rejects any future ``bind_item_handler_registry(self.content, ...)`` / ``mvClickedHandler`` path in the SSH console.
