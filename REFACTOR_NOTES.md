## 1.6.43 - Dear ImGui startup compatibility hotfix

- Removed post-creation `configure_item(..., color/fill=...)` calls on Dear PyGui draw-triangle commands used by ComboBox and SpinBox arrows. Dear PyGui 2.3.1 on Windows can surface these as `<built-in function configure_item> returned a result with an exception set` during startup.
- Arrow indicators remain geometry-only (no font/Unicode symbol regression). Disabled interaction remains enforced by the retained control state and callbacks.
- Added a regression guard so future visual work cannot reintroduce draw-command `configure_item` calls.

# Refactor pass 1: SSH console runtime

## 1.6.42 — Dear ImGui Legacy Visual Fidelity Phase 15

- Restored the main File/Bookmarks/Commands/View/Help menu spacing explicitly instead of inheriting the compact application-wide Dear ImGui item spacing. Root menus now use a roomy shared QMenu-like theme while command rows retain the proven 190 px pre-migration geometry.
- Restored the file-toolbar metrics from the older WinUx line: 38 px navigation strip, 36 px search strip, 30x28 navigation controls, a 28 px path surface and the former 16 px semibold path font.
- Added a dedicated `Job Viewer` list-view theme based on the pre-migration scheduler table instead of reusing the post-migration generic `Explorer` theme. Job headers are centered again, use the old pale header palette and keep the sort triangle inline with the header label rather than against the next divider.
- Added a direct Job Viewer right-click fallback bound to the body surface. The existing global Explorer pointer dispatcher remains primary; the fallback waits one frame and opens the context menu only when the normal route did not, restoring Check Job/Edit/Cancel/ODB/Plots/Refresh context actions without duplicate menus.
- Removed the remaining font-dependent combo/spin arrow labels (`v`/`^`). ComboBox and SpinBox arrows are now Dear PyGui triangle geometry, eliminating the black-diamond/replacement-symbol artefacts seen with Windows font fallback.
- Restored SSH Login to the older compact flat form geometry (420 px wide, direct Host/Port/Username/Password rows, compact footer) while keeping the current retained Dear ImGui controls, focus behavior, validation and process-isolated dialog host.
- Main WinUx remains Dear ImGui/Dear PyGui only; Server Notepad remains the explicit ttk exception.
- Portable regression sweep: **853 passed, 11 skipped and 28 subtests passed**; `compileall` passes.

## 1.6.41 — Dear ImGui Legacy Visual Restore Phase 14

- Restored Job Viewer to the pre-migration `ExplorerListView` details renderer while keeping Dear ImGui/Dear PyGui as the UI backend. This restores the mature row hit-testing, right-click context menu, column-resize behavior and WinSCP/Explorer-style header used by the 1.5.x line.
- Restored the main File/Bookmarks/Commands/View/Help menu density used before the retained Qt-like menu styling: native Dear PyGui menu roots, 6 px icon spacing and 190 px command rows; the compact retained QMenu theme is no longer forced onto the application menu bar.
- Replaced font-dependent decorative Unicode glyphs in the primary Dear ImGui UI path. Context-menu checks/submenu arrows and Explorer sort indicators are now drawn as geometry; remaining arrow/close indicators use ASCII-safe labels.
- Reworked Explorer header sort markers as draw triangles rather than Unicode text, preserving left-aligned labels and thin column dividers at any Windows font/DPI configuration.
- Preserved Job Viewer ODB Quick Check, Extract Data, Plots check-state, ownership-sensitive enablement, status-row colouring and single-selection behavior while restoring the original renderer.
- Added Phase-14 regression coverage for the pre-migration menu contract, Job Viewer renderer/context-menu contract, geometric header indicators and the no-decorative-Unicode rule.
- Main WinUx remains Dear ImGui/Dear PyGui only; Server Notepad remains the explicit ttk exception.
- Portable regression sweep: **846 passed, 11 skipped and 28 subtests passed**; `compileall` passes.

## 1.6.40 — Dear ImGui Qt-style Form Controls Phase 13

- Added `ImGuiRadioButtonGroup` / `QRadioButtonGroup`, a retained wrapper over
  Dear PyGui's native radio primitive with current-text/current-index APIs,
  activation/change signals, enabled/focus styling and worker-update
  coalescing. Dear ImGui remains the sole pointer/keyboard owner.
- Added a Fusion-like native radio theme and kept the radio indicator/hit area
  native rather than introducing a custom overlay.
- Extended `QtDialog` with retained `checkbox()`, `radio_group()` and
  `progress_bar()` factories so production dialogs can use one control registry
  for enabled/disabled state and visual refresh.
- Migrated Job Edit deletion mode from raw `dpg.add_radio_button()` to the
  retained radio group without changing the schedule/value contract.
- Migrated Job Manager Run/Overwrite cells from raw checkboxes to retained
  checkboxes; native tag IDs are still returned so existing `dpg.get_value()`
  submission logic remains intact.
- Migrated Transfer Center row progress/action controls to the shared retained
  progress/button layer. Action enabled-state changes now flow through
  `set_control_enabled()` so disabled visuals and behavior remain synchronized.
- Added Phase-13 source-architecture gates and behavioral tests for native radio
  value/index/activation semantics and queued worker-update invalidation.
- Main WinUx remains Dear ImGui/Dear PyGui only; Server Notepad remains the
  explicit ttk exception.
- Portable regression sweep: **842 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. Four native Dear PyGui dialog suites remain unavailable
  in this Linux validation runtime because the bundled Windows DPG extension
  cannot be loaded here.

## 1.6.39 — Dear ImGui Qt-style Form Controls Phase 12

- Added passive focus-state theming to `ImGuiLineEdit`: the direct Dear ImGui `mvInputText` now changes only its 1 px frame from Fusion gray to focus blue while Dear ImGui keeps exclusive ownership of mouse activation, insertion point, text selection and caret blinking.
- Added retained checked/focus theming to `ImGuiCheckBox`; checked indicators now use the Fusion blue fill with a white checkmark, inactive/disabled states use neutral palette roles, and no custom hit target replaces the native Dear ImGui checkbox.
- Expanded `ImGuiPushButton` with explicit default/focus state, `isDefault()`, centered button text, and focus/default border rendering. Dialog action buttons are registered in the shared retained-control registry so enabled/disabled changes refresh their visual state consistently.
- Centered ComboBox and SpinBox arrow glyph sub-controls and suppressed nested navigation rectangles so the outer control owns the focus frame.
- Login busy-state handling now disables retained line edits, buttons and the Remember checkbox through their wrapper APIs, preserving disabled styling instead of only flipping the Dear PyGui enabled bit.
- Settings now uses the canonical `ImGuiCheckBox` name instead of the legacy `QCheckBox` compatibility alias.
- Added Phase-12 regression gates for focus/caret ownership, checkbox checked rendering, button default/focus semantics, Login busy-state styling and the Dear ImGui-only backend boundary.
- Main WinUx remains Dear ImGui/Dear PyGui only; Server Notepad remains the explicit ttk exception.


## 1.6.38 — Dear ImGui Qt-style Form Controls Phase 11

- Refined `ImGuiComboBox` popup geometry: viewport clamping, above/below placement, hidden staging before reveal, current-item scrolling, and `setMaxVisibleItems()` contract.
- Added QComboBox-like popup keyboard behavior: Up/Down move popup highlight; Enter commits; Escape closes without changing the editor.
- Tightened SpinBox sub-controls to a 17 px arrow strip with zero vertical ImGui spacing so the two arrow buttons fit the 24 px control height exactly.
- Improved QFormLayout-like label/editor alignment with a shared vertical label inset.
- Tightened checkbox label/indicator spacing while retaining native Dear ImGui checkbox ownership.
- Main WinUx UI remains Dear ImGui/Dear PyGui only; Server Notepad remains the explicit ttk exception.


Completed on 2026-10-03 for WinUx 1.6.10.

## Changes

- `BoundedTextBuffer` stores bounded 4 KiB chunks instead of copying the entire
  transcript on every SSH read. Small reads share chunks to limit allocation
  overhead. Full snapshots are assembled lazily and cached until the next write.
- Cursor reads scan backward through only the requested suffix. Eviction and
  clear retain the existing monotonic cursor contract.
- `TerminalBuffer` caches styled transcript rows while the editable command
  changes. Output, ANSI color changes and column changes invalidate the cache.
  Returned row lists remain independent of cached storage.

## Measurements

Run `python tools/benchmark_console.py` with the same interpreter before and
after a change. The script takes the median of three runs. Raw results are
stored in `tools/console_baseline_before.json` and
`tools/console_baseline_after.json`.

| Workload | Before | After | Ratio |
| --- | ---: | ---: | ---: |
| 10,000 appends, 1 million retained characters | 1.197 s | 0.047 s | 25.6x |
| 100 draft edits with 5,000 transcript lines | 4.346 s | 0.271 s | 16.0x |

These are local microbenchmarks, not end-to-end application speedups. Timings
vary between runs, and reading a complete changed snapshot still requires
assembling the retained text.

## Validation and limits

- 42 targeted unittest tests passed across text retention, terminal behavior
  and runtime optimization suites; changed Python sources compiled successfully.
- Before changes, unittest discovery ran 373 tests with 15 failures and 13
  errors. After the first six added tests, discovery ran 379 tests with the same
  failure/error counts, all outside the changed modules. One further chunk
  boundary test passed in the final targeted run.
- Existing failures include native-dialog architecture assertions. Existing
  errors include Dear PyGui DLL loading and updater test imports.
- The available bundled Python has no pytest installation. Unittest discovery
  does not execute standalone pytest test functions. Native GUI behavior and a
  live SSH session have not been verified in this environment.
- This workspace has no Git metadata; no commit or branch was created.

## Next candidates

The baseline tool reports 168 application Python modules and 49,532 lines before
this pass. The largest modules are `controller.py` (2,921 lines),
`explorer_list_view.py` (2,773 lines), and `server_notepad_process.py` (2,185 lines).
Future passes should profile actual navigation and file loading, then extract
specific responsibilities from these modules. Resolve the existing test failures
before using a clean full-suite run as a refactor gate.

# Refactor pass 2: directory synchronization preview

Completed on 2026-10-03.

- Extracted comparison, asynchronous scanning and transfer routing into
  `WinUx/controllers/sync_preview.py`. Historical controller methods and
  signatures remain as delegates. `controller.py` decreased from 2,921 to
  2,805 lines.
- Named items now have their metadata extracted once instead of twice. Local
  and remote root paths are constructed once per comparison.
- A scan generation prevents older scans and queued errors from overwriting
  the latest preview. Superseded workers skip further directory reads where
  possible. Publication also checks active directories, SSH connection
  generation, connectivity and window/shutdown state.
- Existing upload/download confirmations and transfer routing remain in use.
  Scans already inside a filesystem/SFTP operation may finish that operation;
  invalid results are discarded when they return.

Validation: 12 new behavioral tests and 10 existing phase-3 tests passed. Four
standalone feature-integrity checks passed, including the historical callable
surface contract. Changed sources compiled successfully. Full unittest
discovery ran 392 tests with the same 15 failures and 13 errors as the 380-test
baseline at the start of this pass; no new failing/error test IDs appeared.
The comparison reports are in `tools/refactor_pass2_before.json` and
`tools/refactor_pass2_after.json`. Native GUI and live SSH remain unverified.

Separately invoking the 12 standalone controller-component test functions gave
11 passes and one failure in the unchanged schedule-manifest test: it expects
`Path("/scratch/demo.inp")` to serialize with POSIX separators on Windows.
This function is not collected by unittest discovery; its failure is additional
to the full-discovery counts above.

# Refactor pass: Server Notepad command/IPC + Explorer transfer interaction

Completed on 2026-10-03 for WinUx 1.6.10.

## Server Notepad

- Extracted keyboard shortcut adapters and parent-process command routing into
  `services/server_notepad_commands.py` via `ServerNotepadCommandMixin`.
- Extracted JSON-lines reader/writer threads, bounded IPC queues, snapshot
  decompression, large-save compression and Tk pump routing into
  `services/server_notepad_ipc.py` via `ServerNotepadProcessBridge`.
- Preserved the historical `ServerNotepadWindow` callable surface through mixin
  composition and kept `_ProcessBridge` as a bootstrap alias for compatibility.
- `services/server_notepad_process.py` decreased from 1069 to 760 lines while
  retaining the same window construction, load/save/search/highlight lifecycle.
- Added portable behavior tests for shortcuts, focus/lifecycle command routing,
  streamed snapshot routing and zlib+base64 save/read paths.

## Explorer transfer interaction

- Extracted drag-session state, Windows Explorer shell handoff, external local
  copy queueing, external server upload queueing, drag-motion target caching and
  release-time drop routing into
  `controllers/explorer_transfer_interaction.py`.
- `TransferController` still owns conflict detection, overwrite confirmation,
  progress/cancel behavior and actual transfer execution; the extracted mixin
  only owns interaction/orchestration boundaries.
- Preserved the cached highlighted destination fallback used when native mouse
  capture invalidates release coordinates.
- `controller.py` decreased from 1545 to 1288 lines with the v1.6.3 callable
  feature surface preserved through mixin composition.

## Regression repair and validation

- Fixed `ExplorerNativeHook._uninstall_native_cursor_hook()` so teardown logic
  remains portable/testable when Win32 APIs are supplied by a harness; real
  installation is still Windows-only. This restores the shared drop-owner
  teardown contract and prevents a stale owner from keeping shell drops enabled.
- Full pytest regression: **733 passed, 11 skipped and 28 subtests passed**.
  Skips are native Windows/Tk-display cases unavailable in this Linux runner.
- `python -m compileall -q WinUx` passed.
- Current structural baseline: 204 Python files, 51,865 Python lines,
  87 test modules and zero duplicate-tree files.

## WinUx 1.6.17 - compositor-clean dialog open/close transaction (2026-10-03)

- Removed the black close frame from process-isolated Dear PyGui dialogs. The
  inner DPG form is no longer hidden/deleted while its native viewport is still
  visible; its last fully rendered pixels are preserved until after `SW_HIDE`,
  and only then is the DPG item/context torn down.
- Removed the old 50 ms pre-hide cleanup window. Foreground/modal hand-off now
  happens while the final dialog frame remains intact, then the native HWND is
  hidden immediately. Slower cleanup happens entirely off-screen.
- Dialog opening is now a staged compositor transaction. The HWND is mapped with
  `SW_SHOWNOACTIVATE` while still DWM-cloaked, pending DPG resize/layout callbacks
  are drained, final frames are rendered into the mapped swap chain, and DWM is
  flushed before the cloak is removed.
- Initial native owner-disable was moved later in the transaction. The child is
  first mapped/rendered and pre-activated while cloaked; only after the child
  reports `staged` does the parent disable the WinUx owner and acknowledge
  `publish_commit`. This prevents Windows from activating another desktop window
  during the gap between disabling WinUx and showing its modal replacement.
- The first visible dialog frame is therefore already laid out, rendered and
  active. Deferred activation remains fallback-only when Win32 rejects the
  pre-activation. No TOPMOST mode or owner hide/show cycle is introduced.
- Added source-level regressions for staged map/render/uncloak ordering, delayed
  native owner acquisition, preserved close pixels, and the absence of pre-hide
  cleanup sleeps.
- Portable regression: **755 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. Native DWM visual verification remains a Windows smoke
  test.

## WinUx 1.6.11 - Login owner visibility/focus regression (2026-10-03)

- Successful SSH Login now closes through an explicit return-to-owner path.
- Generic dialog close keeps the existing no-focus-steal/no-reveal behavior.
- The explicit path is armed only when the Login/Main WinUx HWND still owns foreground focus at completion, so a user Alt-Tab during a slow SSH connection is respected.
- If Windows/GLFW unexpectedly leaves the main WinUx HWND hidden during that explicit modal transition, the owner is revealed without an intermediate activation and then focused once after the child dialog disappears.
- Added regressions for successful-login focus return and hidden-owner recovery.

## WinUx 1.6.12 - orphan helper/taskbar shutdown cleanup (2026-10-03)

- Added a toolkit-independent registry for WinUx-owned helper UI processes.
  Floating dialog workers, dialog prewarm workers, Server Notepad and the local
  folder chooser register their child `Popen` handles until those processes
  have actually exited.
- Standalone Exit now hides every visible top-level HWND owned by registered
  helpers before the WinUx owner process disappears. This prevents Windows from
  briefly promoting an orphaned DPG/Tk helper to a generic grey taskbar item.
- Helper close remains graceful first. After a bounded 120 ms grace interval,
  any survivor is terminated as a Windows process tree (`taskkill /T /F`) with
  a bounded 250 ms cleanup window. This covers the `cmd.exe -> abaqus python`
  wrapper used by floating dialogs without waiting on SSH or other worker locks.
- The main viewport is hidden before the bounded helper cleanup, preserving the
  existing fast-close behavior and avoiding a visible shutdown stall.
- Added regression coverage for helper process registration/pruning and the
  shutdown ordering `request UI -> hide helper HWNDs -> stop server -> reap
  helpers -> os._exit`.
- Portable regression: **737 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. Win32 taskbar behavior still requires the production
  Windows smoke test because this runner cannot instantiate the native UI.

## WinUx 1.6.13 - dialog parent visibility/focus lifecycle (2026-10-03)

- Every process-isolated dialog now records whether its fixed native owner was
  visible when the dialog was shown. If Windows/GLFW hides that owner during
  teardown, WinUx repairs only the lost visibility after the child HWND is no
  longer visible. The repair uses the existing non-activating show path, so it
  does not recreate the previous hide/show flicker.
- Parent-driven result close now captures whether the child dialog owns the
  foreground *before* issuing `SW_HIDE`. This closes the race where OK/Cancel,
  input, confirm, and result dialogs lost their focus-return information before
  the child process could send its final close event.
- Child-driven close (caption X / Escape / normal runtime exit) reports the
  foreground-ownership state in the final IPC event. Both close directions
  therefore use the same focus-return policy.
- If a dialog really owned foreground focus at close, its fixed parent is
  re-enabled and focused after the child disappears. Background/programmatic
  closes do not activate WinUx. A parent that was already hidden before the
  dialog opened is never revealed by dialog teardown.
- Shutdown still suppresses all deferred focus repair, preserving the 1.6.12
  orphan-window cleanup and preventing WinUx from reappearing during Exit.
- Added regressions for hidden-owner repair, deliberately hidden owners,
  foreground-owned close, external-focus preservation, and the pre-hide focus
  capture/child close handshake.
- Portable regression: **743 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. Native Win32 focus/Z-order behavior still requires the
  production Windows smoke test.
## WinUx 1.6.14 - dialog foreground/Z-order hand-off (2026-10-03)

- Split ordinary keyboard-focus restoration from a stronger dialog-to-owner
  foreground hand-off. Closing a dialog that actually owned the foreground now
  performs one non-TOPMOST `BringWindowToTop` after the child HWND is gone, then
  restores foreground/active/keyboard focus to the captured parent.
- The hand-off never changes WinUx visibility, position, size, normal/maximized
  placement, or permanent topmost state. This fixes the case where WinUx stayed
  visible but fell behind other open desktop windows after a dialog closed.
- Process-isolated DPG dialogs preserve the existing pre-hide foreground capture,
  so OK/Cancel/X/Escape all use the same Z-order return semantics. Background or
  programmatic closes still do not steal foreground from another application.
- Shared native Tk/QDialog-style dialogs now capture foreground ownership before
  native destruction and request the stronger hand-off only for a genuine
  foreground close. Hidden/background teardown only releases modality.
- Added regression coverage for delayed hand-off until the child is hidden,
  non-TOPMOST raising, and foreground-aware native close behavior.
- Portable regression: **745 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. Native Win32 Z-order behavior still requires the
  production Windows smoke test.


## WinUx 1.6.15 - seamless dialog close foreground hand-off (2026-10-03)

- Removed the normal two-stage close path where the foreground dialog first
  disappeared while WinUx was still disabled and a later UI tick raised WinUx
  again. That sequence allowed Windows to activate another desktop window for
  one frame and was the visible flash reported after dialog close.
- Foreground modal dialogs now re-enable only their native Win32 owner
  immediately before `withdraw`/`SW_HIDE`/native destruction. The separate DPG
  modal-input gate remains held until the child is actually hidden, preserving
  modality and preventing click-through.
- Because the owner is activation-eligible at the instant the owned child
  disappears, Windows can perform its normal dialog-to-owner foreground/Z-order
  transfer in one native transition. No TOPMOST flag, hide/show cycle, window
  relocation, or resize is used.
- Deferred `BringWindowToTop`/`SetForegroundWindow` is now recovery-only. If the
  owner is already foreground after the native hand-off, the focus queue exits
  without issuing a second activation. Background/programmatic closes still do
  not steal focus.
- Child-driven process-isolated closes (caption X, Escape, and form self-close)
  use a short IPC handshake: the child reports `closing` while its HWND is still
  foreground, the parent balances the native modal-owner disable count, and only
  after `owner_handoff_ready` does the child execute `SW_HIDE`. This closes the
  last path that could still produce the old one-frame Z-order flash.

## WinUx 1.6.16 - framework-style modal close hand-off (2026-10-03)

- Reworked dialog close ordering to match native Qt/WinForms/WPF semantics:
  foreground ownership is transferred back to the captured owner while the
  owned dialog HWND is still visible, then the dialog is hidden/destroyed.
  Windows therefore never needs to activate an unrelated desktop window for an
  intermediate composition frame.
- Added `handoff_owner_before_close(...)`, a guarded pre-close activation path.
  It refuses to run if another application already owns foreground, never uses
  TOPMOST, never ShowWindow/reshows the parent, and does not alter placement or
  size. Deferred `BringWindowToTop` remains failure recovery only.
- Process-isolated Dear PyGui dialog workers now perform the final foreground
  hand-off themselves immediately before `SW_HIDE`. This is important because
  the child process is the foreground process and can transfer activation in
  the same native transition instead of relying on a later parent callback.
- Parent-side forced/result teardown also performs the hand-off before hiding a
  still-visible foreign HWND, covering Login/progress/programmatic close paths.
- Result dialogs no longer issue a second parent-side close when the child has
  already emitted a result and started its own close lifecycle. The parent only
  records the result; callbacks are delivered after the child native close has
  finalized. This removes the result -> parent SW_HIDE -> child SW_HIDE race.
- Shared native Tk/QDialog-style windows use the same ordering before
  `withdraw()` and `destroy()`, so every dialog backend now follows one close
  contract.
- Added regressions for pre-hide foreground transfer, child-side hand-off
  ordering, native Toplevel ordering, no-TOPMOST/no-ShowWindow behavior, and
  child-result ownership of native close.
- Portable regression: **752 passed, 11 skipped and 28 subtests passed**;
  `compileall` passes. The remaining visual verification is the native Windows
  compositor smoke test on the production desktop.

## 1.6.19 — Confirm Exit result delivery / hard-close regression
- Fixed the root cause of the main-window Close command appearing to do nothing after the floating-dialog lifecycle refactor.
- Root floating forms were scheduling their result callback *after* `destroy()`. `destroy()` marks the root form closed, causing the child runtime loop to terminate before the delayed callback could be drained; `Confirm Close App` therefore never delivered `True` to `WinUXController._close_confirmation_finished()`.
- Blocking/Job Edit/ODB Extract/Server Folder child forms now publish semantic results synchronously before marking the root form closed. The parent adapter still waits for the native `closed` event before dispatching application callbacks, preserving clean visual teardown and avoiding a second HWND close.
- Production shutdown keeps the bounded child-process cleanup + hard process exit contract; explicit standalone launch intent overrides the test-harness safety opt-out.
- Regression: full suite 756 passed, 11 skipped, 28 subtests.

## 1.6.21 - Qt control fidelity pass

- Reworked dialog text fields to use a shared QLineEdit-like visual contract with compact padding, square Fusion-style frames, and a blue focus border.
- Added shared QComboBox styling/focus helpers and routed dialog combo creation through `QtDialog.combo()` so Settings, Site Manager, Job Manager and ODB dialogs no longer use inconsistent raw Dear PyGui combo styling.
- Improved editable Login combo boxes: 26 px arrow sub-control, shared focus state across editor/arrow, Qt/Fusion popup palette, and distinct normal/focus/disabled themes.
- Fixed the editable combo theme-cache aliases where normal and disabled states previously resolved to the same theme tag.
- Routed standard dialog text fields through `QtDialog.line_edit()`; Blocking/Input, Diagnostics, Job Manager time fields, Login and other form fields now share one control style.
- Added architecture regression tests for the shared line-edit/combo style contract.

## 1.6.23 - Qt editor/combo fidelity

- Reworked single-line dialog editors so the visual focus border lives on a stable outer shell instead of rebinding the active Dear ImGui InputText theme. This preserves native text-edit state and caret rendering.
- Added deferred editor-focus repair on the next rendered frames, matching the proven toolbar-search behaviour, while preserving a mouse-selected insertion point when the editor is already active.
- Refined editable QComboBox geometry: one outer frame, 23 px drop-down sub-control, subtle separator, white integrated arrow face at rest, and Qt/Fusion-style hover/pressed fills.
- Login initial focus now targets the actual editor path used by the control wrappers.

## 1.6.25 - reusable Qt item views
- Added `WinUx.widgets.QtDataGridView` / `QTableView` with stable row keys,
  current/anchor selection state, extended selection, keyboard navigation,
  sortable/resizable Qt/Fusion-styled headers, alternating rows and activation
  signals.
- Added `WinUx.widgets.QtListView` / `QListView` using the same selection model
  and Qt/Fusion row/focus metrics instead of Dear PyGui's listbox contract.
- `dialogs.QtTable` is now a compatibility adapter over `QtDataGridView`, so
  ODB, Bookmarks and Sync result tables share the reusable implementation.
- Settings > Abaqus Versions and Server Folder suggestions now use `QtListView`.
- ExplorerListView remains specialized to preserve Shell icons, inline rename,
  drag/drop, rubber-band selection and native Explorer hooks.


## 1.6.26 - Qt item-view infrastructure / shared Explorer selection
- Extended `QtDataGridView` with `QtGridRow`, opaque row metadata, optional row
  background roles, column-width APIs, and a data-driven QMenu-like context-menu
  contract with checked/enabled state. These APIs prepare specialized grids for
  migration without coupling them to filesystem-specific view code.
- Explorer file panels keep their optimized draw-list/Shell backend, but click,
  keyboard, public selection, drag-start selection, rename/reload selection and
  right-click current-index behavior now share `QtItemViewState` semantics with
  `QtDataGridView`/`QtListView`.
- Aligned Explorer header/row metrics with shared Qt Fusion metrics instead of
  maintaining separate magic numbers.
- Kept Job Viewer on its current Explorer-rendered grid for this pass because its
  context menu still depends on icon-rich nested menu rendering; migration is
  deferred until the generic Qt menu layer reaches icon/hover parity, avoiding a
  visual/behavior regression.
- Regression: 767 passed, 11 skipped, 28 subtests.

## 1.6.27 — Dear ImGui UI backend convergence

- Restored SSH Login to the shared process-isolated Dear PyGui runtime; removed the temporary native/Tk login backend.
- Rebuilt the editable login combo as a Dear ImGui composite (`mvInputText` + arrow sub-control + DPG popup) while leaving mouse activation to InputText so caret placement remains owned by ImGui.
- Registered the custom combo popup with the global pointer-surface gate to prevent Explorer/splitter click-through.
- Replaced the process-isolated Tk folder picker with a Dear PyGui floating Local Folder dialog using the shared item-view model and async `os.scandir` enumeration.
- Added backend-explicit `ImGuiComboBox`, `ImGuiDataGridView`, `ImGuiListView`, and `ImGuiItemViewState` names; existing Qt* names remain compatibility/style aliases only.
- Added an architecture gate that prevents new Tk imports outside the explicitly tracked Server Notepad legacy migration island.
- Remaining secondary-toolkit UI is now isolated to Server Notepad legacy modules and their compatibility helpers; that is the next migration target.

## 1.6.28 - Dear ImGui Qt-style foundation

- Added a Dear ImGui-only Qt/Fusion style foundation under `WinUx/widgets/imgui_qt_style.py`.
- Added canonical `ImGui*` retained controls while keeping historical `Q*` names as compatibility aliases.
- Expanded the retained widget contract with QWidget-like object names, dynamic properties, enabled/visible queries, geometry helpers, tooltips and focus helpers.
- Single-line dialog fields now use one direct `mvInputText` instead of a child-window frame wrapper so Dear ImGui owns mouse selection and caret activation directly.
- Dialog buttons now share the same retained ImGui button style contract outside and inside dialogs.
- Editable combo arrow sub-control no longer paints its own full border; the outer combo shell is the only frame, reducing the "textbox + button" appearance.
- Login now imports backend-explicit `ImGuiComboBox` and `ImGuiCheckBox` names.
- No Qt/PyQt/PySide/Tk backend was introduced. Server Notepad remains the intentionally retained ttk exception.

## 1.6.29 - Dear ImGui Qt-style controls phase 2

- Added retained `ImGuiSpinBox` / `ImGuiDoubleSpinBox` controls. They keep a real Dear ImGui scalar editor as the text/caret owner and compose Qt/Fusion-like integrated up/down sub-controls inside one outer focus frame.
- Added reusable `ImGuiGroupBox`; `QtDialog.section()` now uses this shared Dear ImGui container contract instead of rebuilding group chrome per dialog.
- Expanded editable `ImGuiComboBox` with a single-frame editor/arrow layout, a 1 px separator, and QComboBox-like signals/properties (`currentTextChanged`, `currentIndexChanged`, `activated`, `editTextChanged`, current/set index/text, editable, popup API).
- Migrated Settings numeric inputs and Job Manager CPU input to the retained spin-box layer so numeric fields no longer use raw `dpg.add_input_int/float` styling.
- Added `QtDialog.set_control_enabled()` so composite controls enable/disable as one unit rather than leaving spin buttons active while only the editor is disabled.
- Main WinUx UI remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.

## 1.6.30 - Dear ImGui Qt-style item views / tabs / menus phase 3

- Added `ImGuiTabWidget` / `QTabWidget` compatibility wrapper over native Dear PyGui tabs with retained page ownership, current-index APIs and `currentChanged` signaling.
- Added reusable `ImGuiMenu` / `QMenu` data-driven popup menus with nested actions, enabled/check state and Qt/Fusion popup styling; no Qt/Tk backend is used.
- `ImGuiDataGridView` now routes its context-menu contract through the shared `ImGuiMenu` instead of rebuilding private menu windows per grid.
- Added strong focused-selection rendering for reusable data-grid/list-view rows: selected rows use the application highlight blue with white text, disabled selections use the inactive palette, and hover/pressed states remain Qt/Fusion-like.
- `QtGridRow.enabled` is now respected by `ImGuiDataGridView` and survives sorting/model refreshes.
- Main WinUx UI remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.
- Regression: 784 passed, 11 skipped, 28 subtests.
## 1.6.31 - Dear ImGui Qt-style Job Viewer / menu phase 4

- Rebuilt `ImGuiMenu` as an icon-capable Dear PyGui popup renderer instead of relying on native Dear ImGui `menu_item` rows. Menu rows now preserve WinUx texture icons, a dedicated check slot, disabled text state and a Qt/Fusion hover surface.
- Nested menus now open from row hover and remain fully Dear ImGui/Dear PyGui. Added keyboard navigation for Up/Down, Enter, Escape and Left/Right submenu traversal.
- Migrated PBS Job Viewer from the specialized `ExplorerListView` renderer to `ImGuiDataGridView`; file Explorer panes remain on their specialized shell/drag renderer.
- Job Viewer preserves stable job-id selection across qstat refreshes, Running/Queued row tinting, sortable/resizable headers, Plots check state, owner-sensitive command enablement and the Check ODB / Extract Data submenu.
- The Job Viewer Name column now stretches natively while the remaining columns retain fixed widths, eliminating the old manual column-fit bookkeeping.
- Main WinUx remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.


## 1.6.32 - Dear ImGui Qt-style item-view visual fidelity phase 5

- Added retained `ImGuiHeaderView` / `QHeaderView` facade over Dear PyGui table columns with Qt-like section visibility, resize mode, movable/clickable sections, stretch-last-section and explicit section sizing APIs.
- `ImGuiDataGridView` and `ImGuiListView` now distinguish selected rows from the current index and active/inactive view focus. The current index uses a one-pixel focus rectangle while inactive selections fall back to the neutral Qt/Fusion palette.
- Added view-level focus tracking without pointer capture so selection rendering changes correctly when the user clicks into or away from an item view.
- Applied the shared WinUx Qt-like scrollbar skin to reusable grids/lists and tightened table cell/header geometry.
- `ImGuiDataGridView` now recolors every display cell on selection, not only the first selectable cell, so active blue selections use white text across the complete row.
- Grid/list model refreshes preserve horizontal/vertical scroll offsets, preventing qstat/ODB refreshes from jumping Job Viewer back to the origin.
- Added QTableView/QListView-style visual properties (`setAlternatingRowColors`, `setShowGrid`, `setHeaderVisible`, `setSortingEnabled`, selection mode/current-key APIs) while keeping the backend fully Dear ImGui/Dear PyGui.
- Main WinUx remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentionally retained ttk exception.
- Regression: 795 passed, 11 skipped, 28 subtests.

## 1.6.33 - Dear ImGui Qt-style Explorer item views phase 6

- Moved both local/server file panels from the WinSCP-specific preset to the
  shared Qt/Fusion item-view palette used by ImGuiDataGridView and Job Viewer.
- Added `ExplorerHeaderView`, a QHeaderView-like facade for the specialized
  draw-list Explorer renderer. It exposes section clickability, interactive /
  fixed / stretch resize modes, section sizing and visibility without replacing
  Explorer's Shell-icon, virtualization, drag/drop or inline-rename backend.
- ExplorerListView now exposes QAbstractItemView-like visual properties:
  `horizontalHeader`, alternating-row colors, grid visibility, header
  visibility, selection mode and current-index accessors.
- Active selection is now a flat full-row accent fill with white text; inactive
  selections use the neutral Fusion selection role. Only the current index owns
  the one-pixel focus rectangle. Hover rows no longer render card-like borders.
- File-panel geometry now matches the shared item-view metrics (24 px rows,
  28 px header). The Name section is the stretch section while other columns
  retain interactive resize behavior.
- Row selection rectangles occupy the full row height/width instead of leaving
  one-pixel card margins, while drop-target outlines remain explicit.
- Preserved the old WinSCP theme as an optional registered theme for compatibility;
  production file panels no longer force it.
- Regression: 800 passed, 11 skipped, 28 subtests; compileall passed.

## 1.6.34 - Dear ImGui Qt-style FilePanel chrome phase 7

- Reworked both Local/Server navigation toolbars to a compact QToolBar-like Dear PyGui surface (34 px collapsed height, 20 px icon buttons, flat hover/pressed states, no card-like borders).
- Changed the path selector from a large bold button treatment to a compact left-aligned read-only QLineEdit-like surface using the normal Windows UI font and shared Fusion border/focus roles.
- Tightened the inline search strip to 32 px, kept its editor as a direct Dear ImGui InputText (`auto_select_all=False`), and aligned its padding/background with the toolbar surface.
- Added shared `tool_bar_theme`, `tool_button_theme`, `path_bar_theme`, `status_bar_theme` and `status_text_theme` primitives to the Dear ImGui Qt-style foundation.
- File-panel status strips now use a QStatusBar-like 22 px neutral surface with explicit separator and muted secondary selection text; the shared Local/Server status region uses the same contract.
- Added QToolBar-like retained properties to `FileToolbar` (`setIconSize`, movable/floatable properties) without introducing Qt/Tk backends.
- Main WinUx remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.
- Regression: 804 passed, 11 skipped, 28 subtests; compileall passed.

## 1.6.35 - Dear ImGui Qt-style command chrome / global focus phase 8

- Added an application-wide Dear ImGui Qt/Fusion theme so unstyled controls share one focus/hover/pressed/disabled palette instead of falling back to stock Dear ImGui visuals.
- Added reusable `menu_bar_theme` and `command_button_theme` primitives for QMenuBar/QMenu/QToolButton-like command chrome.
- Main File/Bookmarks/Commands/View/Help menus now bind the shared menu theme and use tighter 22 px command rows with aligned 16 px icon slots.
- DockWidget float/close controls and dock action popup now consume the shared command/menu style foundation rather than maintaining private hover/pressed themes.
- Job Plots toolbar, filter editor and Fit/All/None buttons now use the shared QToolBar/QLineEdit/QToolButton-inspired Dear ImGui themes.
- Main WinUx remains Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.
- Regression: 809 passed, 11 skipped, 28 subtests; compileall passed.

## 1.6.36 - Dear ImGui Qt-style dock / splitter / tooltip phase 9

- Added shared `panel_surface_theme`, `dock_frame_theme`, `dock_title_theme`, `dock_content_theme`, `dock_control_theme`, `splitter_theme` and `splitter_hitbox_theme` primitives to the Dear ImGui Qt/Fusion foundation.
- DockWidget now consumes the shared shell styles instead of private frame/title/control palettes. Its title strip is 24 px, float/close hit areas are 20 px, and the close control uses a Windows/Qt-like red hover/pressed surface with a white vector X while hovered.
- Dock float/close tooltips now use the shared QToolTip-like surface; tabified dock titles and dynamic Job Plots history tooltips use the same tooltip contract.
- All four workspace splitter families (Local/Server, File/Job, Job/Plots and Console) now share one 1 px painted-handle contract, a separate transparent grab gutter, and the same active focus-color feedback without changing layout thickness.
- Job Plots list/plot panes now consume the shared QFrame-like panel surface and shared checkbox styling instead of private per-panel chrome.
- Added phase-9 architecture regression coverage to keep dock/splitter/panel/tooltip shell code on Dear ImGui/Dear PyGui only. Server Notepad remains the intentional ttk exception.
- Regression: 814 passed, 11 skipped, 28 subtests; compileall passed.

## 1.6.37 - Dear ImGui Qt/Fusion form controls phase 10

- Explicitly set Dear ImGui `InputTextCursor` color for line edits, editable combo editors,
  scalar editors, and dialog legacy input themes so the insertion caret remains visible on
  the light Fusion surface.
- Kept all single-line editors as direct Dear ImGui input hit targets; no mouse overlay or
  click-to-refocus shim was added.
- Tightened form-row geometry with one shared `form_row_theme()` and zero internal VBox
  spacing, eliminating accumulated per-cell padding from the QFormLayout-like rows.
- Editable `ImGuiComboBox` now keeps its popup selection synchronized with the current text
  and uses the same compact 24 px field geometry as the rest of the form-control layer.
- Added dedicated regression coverage for cursor visibility roles, combo popup current-index
  state, compact form rows, and the Dear ImGui-only backend boundary.
