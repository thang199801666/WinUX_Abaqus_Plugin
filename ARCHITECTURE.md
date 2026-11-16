**M30 GUI-thread/native-compatibility rule:** QApplication owns WinUx application/UI state. Worker threads and native compatibility backends may enqueue work but must not mutate retained/native WinUx UI directly. Cross-thread latest-value delivery uses the canonical application dispatcher; feature-local queues are fallback-only. Tk in the main process is a lazy compatibility island, never an application-state owner, and its diagnostics must be bounded/observation-only.


**M28 performance-policy/watchdog rule:** runtime performance policy is an immutable `QPerformancePolicy` value selected explicitly (`interactive`, `idle`, or `release`); no feature may mutate a process-global policy singleton. Category-level sustained regression is diagnostics-only and feeds watchdog hysteresis rather than changing dispatcher order. Dedicated background pools must prefer `QThreadPool.taskLane()` with bounded string `category`/`owner` metadata. Performance-envelope readers may migrate known older schemas but must reject future schemas instead of silently downgrading them.

**M27 performance-policy rule:** performance thresholds are represented by immutable `QPerformancePolicy` values, not duplicated magic numbers in feature code. Dispatcher category comparisons must use non-overlapping recent/baseline windows and remain diagnostics-only. Dedicated background lanes should be created through `QThreadPool.taskLane()` with bounded string category/owner metadata; diagnostics must never retain owner objects or allocate new pools. Persisted performance envelopes are versioned and explicitly migrated before comparison.

**M23 dispatcher/future lifecycle rule:** queue-wait latency (ready/deadline to callback delivery) is measured separately from callback execution and whole-turn latency. Recent-window dispatcher diagnostics must remain bounded and sampler-free. `QFuture` objects are asynchronous infrastructure roots, not user-window orphan roots; worker loops must release completed future/runnable locals before blocking again. Unified performance/crash reports combine frame and dispatcher snapshots only through public read-only APIs.

**M22 dispatcher diagnostics rule:** callback execution latency and whole-dispatcher-turn latency are separate bounded metrics owned by `QEventDispatcher`. Watchdog/performance consumers must read compact/public snapshots only; they must not drain queues, consume dirty regions, activate native windows, or add instrumentation threads. Baseline regression warnings are sample-gated and stateless in `QGuiRuntime`; consecutive breach/recovery hysteresis remains in `UIHangWatchdog`.

**M15 QtCore/GUI physical boundary rule:** `QCoreApplication` must not expose shortcut, pointer, input-backend, focus, popup, modal or active-window APIs. Those methods live on `QApplication`. `QWindowHost` follows an explicit `Alive -> Closing -> Closed` lifecycle, and renderer diagnostics must remain side-effect-free.

**M12 QtCore application-boundary rule:** `QCoreApplication` owns event delivery, scheduling, QObject lifecycle and shutdown only. GUI style/palette policy is initialized by `QApplication`; new core-only code must not import GUI style/palette modules or assume those policies exist. Posted `QEvent` priority is owned by the application queue and compression must preserve the highest retained priority.

**M5f dock-target resolution rule:** guide hit-testing and prospective four-way side geometry belong to DearUIQt `QDockDropTargetResolver`. WinUx docking features may supply guide/site bounds and preferred target extents, but must not implement parallel `DockDropPreview.zone_hit()` loops or renderer-specific semantic target policies.

**M5e dock-move transaction rule:** `QDockWindowLifecycle` owns the logical move transaction and semantic drop target for floating dock gestures. DPG/native hosts may hit-test and paint previews, but they must report begin/update/end into the lifecycle and must clear the semantic target when a gesture ends or is canceled.

**M5d dock lifecycle rule:** Logical dock state is owned by `DearUIQt.docking.QDockWindowLifecycle`: docked/floating/moving/hidden state, visibility and persisted floating geometry must flow through this retained lifecycle. WinUx/native hosts may implement hit-testing, drag/drop, HWND presentation and DWM details, but those adapters must not become a second authoritative dock-state machine.


**M5c native presentation rule:** Existing/native-created top-level HWNDs that are not themselves retained QWidget instances use `DearUIQt.backends.native_windows.NativeTopLevelWindow` for presentation operations (outer geometry, visibility, restore/minimize observation and activation). Feature code may still use Win32 directly for monitor selection, hit testing, DWM chrome, WNDPROC/message-loop behavior and native drag semantics, but must not grow new ad-hoc `GetWindowRect`/`SetWindowPos`/`ShowWindow` presentation paths.

**Application QDialog hosting rule:** Use the DearUIQt owned native dialog host from 1.1.12, sharing the application's renderer context, process and QApplication event loop. Do not substitute embedded ImGui dialogs to mask rendering failures. Keep session-tab mutations serialized behind native dialog presentation/teardown. `WINUX_NATIVE_QDIALOGS=0` is an explicit embedded diagnostic fallback, not the default.

# WinUx source architecture

**M5b window lifecycle rule:** Native top-level geometry/exposure observations flow into DearUIQt retained QWidget state through `syncGeometryFromNative()` / `syncExposureFromNative()`. Native bridges must not echo an OS-originated move/resize/show transition back through SetWindowPos/configure_item in the same synchronization path. Application activation remains owned by QApplication.

The source tree is split by responsibility rather than by screen or historical file location.

- `DearUIQt/` — reusable Qt-style GUI framework. It must never import `WinUx`.
- `WinUx/app/` — application composition and top-level orchestration. Feature-facing controller callback facades live in `app/facades/`; the root controller keeps dependency ownership, task lanes and shutdown lifecycle.
- `WinUx/controllers/` — feature/use-case controllers. Cohesive controller families live in `explorer/`, `jobs/`, `transfer/`, `inp/`, and `odb/`.
- `WinUx/models/` — application data models.
- `WinUx/services/` — domain/integration services. Cohesive feature families live in subpackages: `transfer/`, `odb/`, and `server_notepad/`.
- `WinUx/ui/` — WinUx-specific main window, components, behavior and native hosting. Explorer internals live in `ui/components/explorer/`; reusable application behaviors are grouped under `ui/behaviors/docking/`, `splitter/`, `input/`, and `window/`.
- `WinUx/dialogs/` — application dialog infrastructure. Feature-specific dialogs live in `selectors/`, `jobs/`, `transfer/`, and `odb/`; shared dialog logic remains in `logic/` and host adapters remain in `inprocess/`.
- `WinUx/preferences/` — persistent user/application settings.
- `WinUx/platform/` — OS/resource integration.
- `WinUx/runtime/` — event dispatch, task lifecycle and process/runtime primitives. Terminal emulation lives in `runtime/terminal/`.
- `WinUx/bootstrap/` — startup and bundled dependency bootstrap.
- `WinUx/plotdigitizer/` — self-contained Plot Digitizer feature.
- `winux_runtime/` — launcher/update runtime outside the application package.
  The pre-application update UI is a bootstrap boundary: it must stay standard-library-only and Python-2-compatible because it can execute inside Abaqus before DearUIQt/vendor initialization. Its dedicated Win32 message-pump thread is therefore an intentional exception to the application-owned QThread rule.

Qt ownership/lifecycle rule: terminal deletion of a QWidget/QDialog owner must tear down owned top-level children before the owner object tree is disposed. Child dialogs suppress owner-focus restoration during this cascade; accepted `close()` remains a hide operation unless `WA_DeleteOnClose` requests deferred deletion.

- `tests/` — regression and architecture tests.
- `tools/` — maintenance, manifest and benchmark utilities.

Compatibility modules remain at historical import paths (`WinUx.controller`, `WinUx.view`,
`WinUx.server_model`, `WinUx.inp_reader`, `WinUx.resources`) and alias the canonical modules.
New code must import the canonical package location.


## Feature-package rule

New implementation code must use canonical feature paths instead of the historical flat modules:

- `WinUx.services.transfer.*` for transfer planning/copy/conflicts.
- `WinUx.services.odb.*` for ODB inspection/extraction/history/upgrade.
- `WinUx.runtime.terminal.*` for terminal buffer/stream/VT emulation.
- `WinUx.ui.components.explorer.*` for Explorer list-view behavior.

Historical flat modules remain only as import aliases for plugins/tests built against older WinUx releases.
Compatibility helpers live in `WinUx._compat`; lower-level service/runtime packages must not depend on `WinUx.ui` merely to install aliases.


## Controller feature-package rule

New controller implementation code must use feature namespaces rather than adding more flat modules to `WinUx.controllers`:

- `WinUx.controllers.explorer.*` for navigation, local watching, file clipboard/commands and Explorer transfer interaction.
- `WinUx.controllers.jobs.*` for job actions, polling, plotting, scheduling, submission and schedule manifests.
- `WinUx.controllers.transfer.*` for transfer execution, clipboard transfer and sync preview.
- `WinUx.controllers.inp.*` for INP-specific analysis use cases.
- `WinUx.controllers.odb.*` for ODB-specific analysis use cases.
- `WinUx.controllers.console.*` for SSH-console callback/facade behavior.
- `WinUx.controllers.explorer.saved_navigation` for bookmarks and saved site navigation.

Cross-cutting composition such as `callbacks.py`, connection lifecycle and server-notepad orchestration may remain directly under `WinUx.controllers`. Historical flat controller modules are compatibility aliases only. `WinUx.controllers.transfer` is now a package and preserves the old `TransferController` import through its package API.


## UI behavior-package rule

Application-owned behaviors are grouped by interaction domain:

- `WinUx.ui.behaviors.docking.*` for plot/console docking.
- `WinUx.ui.behaviors.splitter.*` for splitter geometry and pointer behavior.
- `WinUx.ui.behaviors.input.*` for pointer/input routing.
- `WinUx.ui.behaviors.window.*` for native main-window lifecycle and compact Job Viewer/PiP behavior.

Historical flat behavior modules are identity-preserving compatibility aliases. New WinUx implementation code must import the canonical grouped paths; generic behavior that no longer depends on WinUx should instead be promoted into `DearUIQt`.


## Dialog feature-package rule

New dialog implementation code must use feature namespaces instead of adding more flat files to `WinUx.dialogs`:

- `WinUx.dialogs.selectors.*` for local file/folder selection and Explorer browser presentation.
- `WinUx.dialogs.jobs.*` for job edit/manager/schedule presentation.
- `WinUx.dialogs.transfer.*` for transfer center, conflict and sync-preview presentation.
- `WinUx.dialogs.odb.*` for ODB check/extract presentation.
- `WinUx.dialogs.reference.*` for Reference Chart and Plot Digitizer integration dialogs.
- `WinUx.dialogs.settings.*` for application settings presentation.
- `WinUx.dialogs.console.*` for terminal/SSH console presentation.

Historical flat dialog modules are compatibility aliases only. Shared hosting/lifetime infrastructure may remain directly under `WinUx.dialogs`; feature implementations must not move back into the flat namespace.


## Main composition rule

`WinUx.ui.main_window.WinUXView` is the composition root for the application window, not the owner of every platform behavior. Native lifecycle/frame/shutdown logic lives in `WinUx.ui.behaviors.window.lifecycle.ViewLifecycleMixin`; deferred startup/dock-state/native console-host setup lives in `WinUx.ui.behaviors.window.startup_docking.StartupDockingMixin`; application menu/status presentation lives in `WinUx.ui.behaviors.window.application_menu.ApplicationMenuMixin`; dialog ownership and serialized modal entry points live in `WinUx.ui.behaviors.window.dialog_facade.DialogFacadeMixin`; compact Job Viewer/PiP behavior lives in `WinUx.ui.behaviors.window.compact_job_monitor.CompactJobMonitorMixin`. New large window behaviors should follow the same composition pattern rather than growing `main_window.py` back into a god object.

## Multi-session tab ownership

WinUx may keep multiple remote login sessions open at once, but only one session owns the visible remote workspace at a time. Each tab owns a stable logical session ID, one `SSHServerModel` transport, remote Explorer/Job snapshots and a session-scoped task namespace. `WinUXController.server` is an alias to the currently active tab's server; feature controllers must resolve it dynamically and must never retain a bound transport callback across tab changes.

Selecting a tab does not create a new logical session. It advances that session's operation generation, making all callbacks from an older activation stale before its cached UI state is restored. Inactive tabs may keep their transport alive, but they must not mutate the visible Server Explorer, Job Viewer, Console or other active-session UI. Heavy polling/navigation is suspended while inactive. Closing a tab cancels only that tab's task scope and transport; closing the application tears down every tab transport. Local workspace state remains process-owned rather than session-owned.

Session-tab presentation is serialized with native QDialog presentation. A login/session-state publication may update logical session state immediately, but structural tab-strip mutation and root relayout must wait until no modal QDialog is active and no native secondary viewport is pending/retiring. Closing a QDialog must synchronously hide its secondary HWND after modal ownership is released; renderer destruction remains deferred. This prevents session-tab changes from exposing an empty native dialog shell.

`WinUx.app.controller.WinUXController` remains the application orchestration root, but it must not become a second implementation layer for each feature. Application-facing compatibility/callback methods are composed from `WinUx.app.facades`: `ConnectionFacadeMixin` for login/reconnect, `JobsFacadeMixin` for polling/scheduling/plot/submission entry points, `ExplorerFacadeMixin` for navigation/file commands/clipboard/server editor, `TransferFacadeMixin` for sync/copy/drop execution, and `AnalysisFacadeMixin` for INP/ODB entry points. These facades delegate to the canonical controllers under `WinUx.controllers.*`; they do not own duplicate feature state. SSH-console callbacks remain in `WinUx.controllers.console.ConsoleFacadeMixin`, bookmarks/site-profile callbacks remain in `WinUx.controllers.explorer.saved_navigation.SavedNavigationMixin`, and native Explorer drag-session behavior remains in `WinUx.controllers.explorer.transfer_interaction.ExplorerTransferInteractionMixin`. The root controller owns dependency construction, bounded task lanes, component factories, startup, and shutdown only.

## Reference Chart subsystem rule

`WinUx.dialogs.reference.reference_chart_form.ReferenceChartDialog` is a composition root for the Reference Chart feature rather than a container for every editing tool. The regex101-style workbench lives in `dialogs/reference/regex_tester.py`; preview rendering and progressive sample reduction live in `preview.py`; formula editing lives in `formula_authoring.py`; series selection/rename/import/save behavior lives in `series_library.py`; shared formula palette metadata lives in `formula_catalog.py`.

The historical `WinUx.dialogs.reference_chart_form` module remains an identity-preserving compatibility alias. Regex helper names are intentionally re-exported from the canonical Reference Chart module because older plugins/tests import those helpers from the historical path. New implementation code should import the focused subsystem directly. Reference-specific subsystems must not import `ReferenceChartDialog` back from the composition module.



## Plot Digitizer tick-detection subsystem rule

`WinUx.plotdigitizer.core.tick_detection` is the stable compatibility facade for automatic axis/tick calibration; detector implementation must not grow back into that facade. Focused implementation lives in `WinUx.plotdigitizer.core.ticks`: `pixels.py` for binary/glyph kernels, `axis_math.py` for scale-independent fitting/spacing math, `recognition.py` for label geometry/word OCR/scale observation, `source_ocr.py` for source-raster recovery, `sequences.py` for template/sequence repair and completion, and `pipeline.py` for axis/calibration orchestration. Shared result types and cancellation/LUT state live in `types.py` and `shared.py`.

The facade intentionally preserves historical private helper names because detector tests/plugins monkey-patch them. `_TickDetectionFacadeModule` mirrors patched bindings into implementation modules, so new code should import focused modules directly while legacy code may continue to import `core.tick_detection`. New detector logic belongs in the narrowest `ticks/` subsystem; do not add large OCR/geometry implementations back to the facade.

## Release integrity rule

`tools/release.py` is the canonical packaging path for distributable WinUx archives. Publishing must not be performed by manually zipping the source tree after running `clean_project.py` or `build_update_manifest.py` separately. The release command is deliberately fail-closed: it removes generated/cache artifacts, validates every Python source file, builds a provisional manifest, runs the release smoke suite, cleans test artifacts, rebuilds the final manifest, verifies every deployment hash, creates FULL and CHANGES-ONLY archives, extracts the FULL archive into a temporary directory, and verifies the extracted deployment again.

Any source change after manifest generation invalidates the release and requires the release command to be run again with a higher package revision. CHANGES-ONLY packages must include the final `update_manifest.json` and, when files were removed, `DELETE_THESE_PATHS.txt`. `__pycache__`, `.pyc`, `.pyo`, `.pytest_cache`, logs and other generated artifacts are never valid release contents.

## Plot Digitizer detector-cache lifecycle rule

Static font/template caches in `WinUx.plotdigitizer.core.ticks` may remain warm across images. Raster-derived OCR caches must not retain previous chart pixels for the lifetime of the application. `ticks.cache.clear_image_caches()` owns the list of image-dependent caches and is invoked whenever `DigitizerEngine` applies a different image or clears the project. New pixel-byte caches must be registered there; reusable font/template caches must remain outside that registry.

For an exact CHANGES-ONLY package, pass the previous FULL archive (or an extracted previous project) with `--baseline`. The release tool hashes the actual baseline file bytes rather than trusting the previous manifest. This is important when recovering from a stale or externally modified manifest: the merge package then contains only files whose real contents changed, not files that merely disagree with stale metadata.
When a baseline archive contains generated artifacts from an older/manual package, the release tool also writes those cache/log paths to `DELETE_THESE_PATHS.txt`. This makes a CHANGES-ONLY merge converge to the same clean source-tree state as the verified FULL archive.

## Plot Digitizer dialog composition rule

`WinUx.plotdigitizer.ui.dialog.PlotDigitizerDialog` is the UI composition root and remains the sole owner of retained widget/state lifetime. Feature implementation must not accumulate back into the root dialog. Canvas/pointer/camera behavior lives in `WinUx.plotdigitizer.ui.controllers.canvas.CanvasController`; calibration and tick interaction live in `controllers.calibration.CalibrationController`; datasets/extraction/history/editing live in `controllers.data.DataController`; file/project/import/export behavior lives in `controllers.project.ProjectController`.

The dialog keeps thin compatibility methods with the historical signatures so existing callbacks, plugins and tests can continue calling or monkey-patching `PlotDigitizerDialog._...` methods. Controllers receive the dialog as `owner`; they must not duplicate engine/widget state or define their own application lifecycle. Controller lookup is lazy-compatible so lightweight integrations that construct a dialog with `__new__` continue to work, while normal instances eagerly attach all controllers during initialization.


### DearUIQt 1.61.0 — M4e QAction presentation unification

Ribbon commands may now bind directly to a shared `QAction` via `RibbonBar.add_action()` / `RibbonGroup.add_action()`. Text, enabled/visible, checkable/checked, icon and tooltip state remain owned by the QAction, while ribbon clicks delegate to `QAction.trigger()`. QAction shortcuts presented by multiple widgets in the same window are de-duplicated during shortcut arbitration, so menu/toolbar/ribbon views of one command do not become ambiguous.

### DearUIQt 1.62.0 — M4f QMainWindow docking facade

`QMainWindow` now exposes Qt-style docking APIs directly over the retained `DockManager`: `addDockWidget()`, `removeDockWidget()`, `dockWidgetArea()`, `restoreDockWidget()`, `tabifyDockWidget()`, `tabifiedDockWidgets()`, `splitDockWidget()`, `resizeDocks()`, `saveState()` and `restoreState()`. Dock identity remains `QDockWidget.objectName()`, including late-created docks restored after state load. Dock policy APIs (`setDockOptions`, nesting, animation, document mode and tab position) are forwarded through the same facade. The DockManager remains lazy so existing WinUx windows do not change geometry until they deliberately adopt the QMainWindow docking contract.

## Focus ownership rule

Application focus is owned by DearUIQt, not by feature code. Ordinary widgets use `QWidget.setFocus()`; native-child surfaces that own their platform focus operation may synchronize logical focus through public `QApplication.setFocusWidget()`. WinUx code must not call `QApplication._set_focus_widget()` or mutate `_focus_widget`/`_active_window` directly. Reusable dialogs snapshot focus with `QPointer` before activation and restore only a surviving widget that still belongs to the logical owner/fallback window; raw renderer item ids are compatibility fallbacks only.

## Window-state lifecycle rule (M5a)

Top-level presentation state is owned by DearUIQt `QWidget`/`QMainWindow`, not by WinUx feature code. Features should use `showMinimized()`, `showMaximized()`, `showNormal()` and `windowState()` rather than issuing native minimize/maximize/restore commands for retained application windows. Native message-pump integrations may call `syncWindowStateFromNative()` when the user changes state through the OS shell; that path must not echo the same state back to Win32. Platform-specific HWND code remains behind native adapters.


## Dock-preview presentation rule

Dock target semantics belong to `QDockWindowLifecycle` and hit-testing/preview geometry belong to `QDockDropTargetResolver`. Dock overlay presentation (visibility, active guide/scope and prospective result rectangle) belongs to `DearUIQt.docking.QDockPreviewController`. WinUx docking features must provide bounds and feature-specific result extents, but must not call `DockDropPreview.show_zones()` directly or maintain a parallel preview-presentation state machine.


## Signal-driven dock-preview rule (M5h)

Dock-preview presentation is driven from `QDockWindowLifecycle` signals. `QDockPreviewController.bindLifecycle()` owns the connections from move start, semantic target changes and move finish to the overlay renderer. WinUx drag loops and native HWND polling may resolve/update lifecycle targets, but must not independently issue preview-show commands for the same gesture. Feature code supplies only live guide bounds and prospective result geometry.


## Signal-driven dock-drop execution rule (M5i)

Dock gesture loops resolve pointer targets and finish `QDockWindowLifecycle` move transactions only. Semantic completion (`dock`, `float`, or `cancel`) belongs to `DearUIQt.docking.QDockDropController`, which listens to `moveFinished`. WinUx feature adapters may perform the renderer/native handshake required to realize that result, but drag polling, mouse-release handlers and native WNDPROC gesture handlers must not independently schedule a second dock transition. Native hosts attach `source="native"` metadata so the adapter can request final editor/plot state before reparenting without duplicating gesture policy.

## Dock commit transaction rule

Logical dock-state changes must use the unified `DearUIQt.QDockTransition` engine. `QDockTransition.dock(...)` owns `prepare -> reparent -> finalize -> persist -> activate`; `QDockTransition.float(...)` owns `prepare -> create -> present`, pauses at the native first-present boundary when required, then resumes `transfer -> finalize -> persist -> activate`. Both directions share one state/rollback/cancel/diagnostic contract. `QDockCommitTransaction` and `QDockFloatTransaction` remain compatibility wrappers only; new WinUx code must use `QDockTransition`. Feature/native adapters may perform required renderer handshakes but must not independently persist, activate, or create a second logical dock transition.

## QDockWidget state ownership rule (M5m)

Each retained `DearUIQt.docking.DockWidget` owns a `QDockWidgetStateController`, and that controller owns the canonical `QDockWindowLifecycle` for the surface. Application feature code must reuse `dock.stateController().lifecycle()` rather than create a second logical lifecycle for the same dock. `setFloating()` is a transition request; renderer/native code commits the resulting state with `set_floating()` only after its host hand-off succeeds. Feature callbacks may adapt platform-specific asynchronous handshakes, but they must not become a parallel source of dock mode, visibility, geometry or move state.
## QMainWindow dock ownership rule (M5n)

`QMainWindow`/`DockManager` own dock topology, while each `QDockWidgetStateController` is the canonical retained state for that dock. QMainWindow topology operations must adopt manager area/floating state into the dock controller. Feature code must not maintain a parallel main-window membership or dock-area source of truth. Direct DockManager floating transitions must synchronize the dock controller as well.


## Retained dock topology signal rule (M5o)

`DockManager`/`DockLayoutTree` remain the canonical split/tab topology. Each `QDockWidgetStateController` mirrors semantic topology metadata (`tabGroupId`, tabified peers, active tab, split orientation and split-parent path) for signals, diagnostics and feature reactions. `QMainWindow` forwards per-dock topology changes through `dockTopologyChanged`; feature code must consume these retained signals/state instead of traversing or caching DockManager's mutable tree dictionaries.



## Retained dock tab-group rule (M5p)

`DockManager`/`DockLayoutTree` remain the canonical owner of tab membership, ordering and active-tab topology. `DearUIQt.docking.QDockTabGroupController` is the retained QTabBar-like semantic layer: it mirrors group/order/active/visible state, owns tab-drag interaction state and emits stable signals for QMainWindow/QDockWidget consumers. Renderer tab strips may hit-test and draw, but must not become a second semantic state machine. Commands such as activate/reorder delegate back to DockManager before the controller resynchronizes.


## Semantic dock-tab command rule (M5q)

Dock/tab renderers are presentation and gesture adapters only. They may hit-test, draw insertion/drop feedback and publish retained drag state, but they must not directly mutate dock topology in response to pointer gestures. Semantic intents (`activate`, `move`, `dock`, `detach`, `cancel`) flow through `QDockTabGroupController` into the single `DockManager.executeTabCommand()` mutation gateway. `DockManager`/`DockLayoutTree` remain the canonical topology owner and the controller resynchronizes retained tab-group state after command execution. Programmatic QMainWindow/DockManager APIs remain valid mutation APIs; this rule specifically prevents renderer gesture code from becoming a parallel topology command path.


## QMainWindow dock-command rule (M5r)

All application-facing QMainWindow dock mutations must enter through `QMainWindowDockCommandBus`. `addDockWidget`, `removeDockWidget`, `restoreDockWidget`, `tabifyDockWidget`, `splitDockWidget`, `restoreState`, and explicit float/dock requests are semantic command wrappers. The bus owns command ordering, observability, reentrancy protection and diagnostics; `DockManager`/`DockLayoutTree` remain the only canonical topology mutation engine. Renderer/feature code must not create a parallel QMainWindow dock mutation path.

## Unified dock-command object rule (M5s)

All semantic dock actions use `DearUIQt.docking.QDockCommand` as the common diagnostics/state envelope. QMainWindow APIs, retained tab gestures and native `QDockTransition` paths may use different executors, but they must expose the same normalized command type, payload, source, lifecycle status, result and error contract. Legacy string/dictionary signals remain compatibility surfaces only. Optional undo metadata may be attached to a command, but topology undo must not be synthesized without a valid restore strategy. `DockManager`/`DockLayoutTree` remain the canonical topology mutation engine.



## M5t dock command history rule

QMainWindow dock undo/redo is checkpoint-backed. `QDockCommandHistory` records the
retained `saveState()` payload together with the live dock registry before and
after successful semantic commands. Undo/redo must reconcile the exact live
QDockWidget registrations first and then restore the retained topology; feature
code must not implement ad-hoc inverse split/tab/remove operations. History
restoration bypasses the semantic command bus so undo/redo never records itself.
A new successful mutation after undo clears the redo branch.

## M5u QUndoStack / QAction dock-history rule

Dock command history remains checkpoint-backed and canonical in
`QDockCommandHistory`, while `DearUIQt.gui.QUndoStack` is the Qt-style
presentation/interaction facade for undo/redo state.  QMainWindow exposes one
`dockUndoStack()` bound to its dock history.  Undo/redo QAction text and
enabled state must derive from the stack/history signals rather than feature
code polling private history lists.  `createDockUndoAction()` and
`createDockRedoAction()` provide WindowShortcut actions (`Ctrl+Z` and
`Ctrl+Shift+Z`); focused text editors retain standard editing shortcuts through
`ShortcutOverride`, so dock-history actions must not steal native editor undo.
The stack is generic and must not know DockManager topology internals.


## Generic undo-command rule (M5v)

New reusable undoable UI operations should prefer `DearUIQt.gui.QUndoCommand`
and a native `QUndoStack()` rather than creating another feature-owned list of
callbacks/snapshots.  A command owns `redo/undo` behavior and may use
`id()/mergeWith()` for coalescing; related edits may be grouped with
`beginMacro()/endMacro()`.  Checkpoint-backed subsystems such as dock topology
may continue to attach their retained history backend through
`QUndoStack(history)`.  A single stack must not mix an attached retained-history
backend with native pushed commands, because the two histories would have
independent indices and rollback semantics.


## Plot Digitizer undo-command rule (M5w)

Plot Digitizer edit history is owned by a DearUIQt ``QUndoStack``. Atomic engine edits recorded through the core history decorator are represented as ``QUndoCommand`` snapshot commands; feature/UI code must use the public ``undo_stack``, ``undo_text`` and ``redo_text`` interfaces rather than inspecting private Python history lists. Legacy ``_undo_stack``/``_redo_stack`` remain read-compatible migration views for old PDG/plugin code, but they are not the source of truth. PDG persistence continues to store the compatible snapshot representation and rebuilds the QUndo command timeline on load.

## Plot Digitizer gesture-edit transaction rule (M5y)

Interactive Plot Digitizer pointer edits use `DearUIQt.gui.QEditTransaction` for an explicit `begin -> update -> commit/cancel` lifecycle. Pointer motion may update preview state or temporary live state, but undo history is created only by the committed engine mutation. Cancel/Escape must terminate the active transaction and rollback any optional live-edit snapshot without creating an undo command. Point, calibration-anchor and future marker/curve drag tools must reuse this transaction contract instead of inventing parallel gesture state machines.


## Plot Digitizer live-edit transaction rule (M5z)

Interactive marker/curve and calibration-anchor drags may mutate engine state live, but they must do so inside `QEditTransaction` using a captured engine snapshot and rollback callback. Per-frame live mutations must emit preview-only events (`data_preview_changed` / `calibration_preview_changed`) and must not create undo commands or trigger committed-data gesture reset paths. Mouse-up commits the already-applied before/after state as one `QUndoCommand`; Escape/cancel restores the captured snapshot and records no history. Feature code must not call recorded engine mutations once per pointer frame.


## Generic property-edit transaction rule (M6a)

Interactive value editors that need commit/cancel/undo semantics should use `DearUIQt.gui.QPropertyEditController` backed by `QEditTransaction` and, when undo is required, `QUndoStack`. Widgets own rendering/input only; the controller owns edit lifetime, snapshot rollback and committed `QPropertyEditCommand` creation. Table/model editors must record commands against the retained model/index rather than a transient cell editor. Existing editors remain source-compatible when no undo stack is attached. Feature code should not maintain a parallel private undo list for ordinary property edits.


## Delegate editor lifecycle rule (M6b)

Transient item editors must use the DearUIQt delegate lifecycle rather than feature-specific commit/close handlers. `QItemEditorLifecycle` owns the canonical `createEditor -> setEditorData -> commitData/setModelData -> closeEditor` session, translates Enter/Tab/Backtab/Escape/focus-out into commit, navigation or rollback semantics, and keeps navigation policy in the view rather than the renderer. Table/list/tree renderers may create native editors, but they must not maintain a parallel commit/cancel state machine. Model undo commands must continue to target the retained model/index, never the transient editor widget.


## Item-view edit trigger/navigation rule (M6c)

`QAbstractItemView` owns edit-trigger and keyboard-navigation policy. The retained defaults match Qt (`DoubleClicked | EditKeyPressed`), while callers may opt into `SelectedClicked`, `CurrentChanged`, or `AnyKeyPressed` with `setEditTriggers()`. F2 requests editing of the current editable index; Enter/Return activates the current item; model-backed Tab/Backtab/Left/Right movement updates the current `QModelIndex` before any optional `CurrentChanged` editor is opened. Renderer callbacks may report clicks/double-clicks, but must not implement a second edit-trigger policy outside the retained view. Delegate editor lifetime remains owned by `QItemEditorLifecycle` from M6b.


## Item-view cursor/navigation rule (M6d)

`QAbstractItemView.moveCursor()` owns keyboard cursor-target resolution for model-backed views. Selection modifiers are applied after target resolution, and successful movement calls `scrollTo(currentIndex())`. Concrete item views may override `moveCursor()` for visual/tree topology, but must not create parallel Ctrl/Shift selection engines.
## QTreeView visible cursor/navigation rule (M6e)

`QTreeView` uses the same public cursor-action contract as the other item views, but resolves movement against the **visible expanded tree order** rather than raw model sibling rows. `Up`, `Down`, `Home`, `End`, `PageUp`, `PageDown`, `Next` and `Previous` therefore skip descendants hidden by collapsed ancestors. `Right` expands a collapsed branch before moving to its first visible child; `Left` collapses an expanded branch before moving to its parent.

The tree remains a compact retained renderer rather than being force-refactored onto `_QtAbstractItemView` in one compatibility-breaking step. Its `moveCursor()` is the tree-topology policy boundary, while `QItemSelectionModel` remains the source of model current/selection state. Feature code must not reproduce visible-tree traversal or Left/Right expansion policy outside `QTreeView`.



## Unified item-view interaction policy rule (M6f)

`QItemViewPolicyMixin` is the shared retained policy layer for `QAbstractItemView`-style widgets. It owns edit-trigger constants/state, cursor-action constants, keyboard-to-cursor mapping, page-step state and Ctrl/Shift selection application. `_QtAbstractItemView` and `QTreeView` must use this layer rather than maintaining parallel interaction policies. Concrete views may override `moveCursor()` and `scrollTo()` for renderer/topology needs; `QTreeView` therefore keeps visible-tree traversal/expand-collapse behavior while the common policy applies the target `QModelIndex` to `QItemSelectionModel`, focus and edit-trigger behavior. Renderer-specific code must not recreate modifier-selection or edit-trigger state machines.

## M6g item-view focus and visual-state ownership

`QItemViewPolicyMixin` is the canonical owner of retained item-view focus state. Concrete list/table/tree renderers must not maintain an independent `_has_focus` state machine. They may cache native paint results, but semantic state comes from the shared policy.

The normalized row state is `(selected, disabled, current, active)`: selection and current index remain distinct, and active/inactive selection is derived from view focus without changing `QItemSelectionModel`. Native rendering failures may be retried separately and must not erase the semantic state.

### M6h item-view paint contract

Item-view renderers and custom delegates should consume `DearUIQt.modelview.QStyleOptionViewItem` rather than re-deriving selection/focus/current state. `QItemViewPolicyMixin.styleOptionForIndex()` is the canonical source of semantic paint state; `QStyledItemDelegate.initStyleOption()` augments that object with model roles. Backend theme functions may translate the option into native colors/borders, but must not create a parallel selection/focus policy. The legacy four-value retained visual-state tuple remains compatibility-only; hover is paint-only state.


### Menu hover repaint stability (1.119.0 / M6j)
- QMenu hover is retained edge-triggered state: a stationary pointer is a complete no-op.
- Switching highlighted actions updates only the previous and next rows instead of rebinding every menu-row theme on every Dear PyGui hover frame.
- Duplicate hover callbacks from the row surface and the row-wide arrow drawlist collapse into the same retained state transition.
- Submenu show/hide is idempotent while hover topology is unchanged. This prevents continuous renderer/native invalidation that can flash the Win32 owner caption while moving across menu items.

### Native dialog chrome transaction stability (1.120.0 / M6l)
- QDialog now applies native resize-frame and caption-button policy through one `NativeWindowBackend.configureDialogChrome()` transaction.
- A dialog show/reconfigure performs at most one `GWL_STYLE` write and one `SWP_FRAMECHANGED`, instead of separate frame refreshes from resize and caption-button setters.
- Stable native chrome policies are idempotent: no style write and no non-client refresh occur when the live style already matches.
- Existing `setResizable()` and `setCaptionButtons()` APIs remain available for compatibility; QDialog prefers the combined transaction.
- This reduces USER32/DWM non-client repaint traffic and avoids disturbing the caption Close hot state while the pointer is stationary.

### Native HWND steady-state cache (1.121.0 / M6m)

- Secondary viewport HWNDs are cached per renderer tag and validated with `IsWindow()` before reuse.
- `winId()` resolves the HWND once and passes it to the owner-sync helper, avoiding duplicate native-handle lookups.
- Successfully committed `(HWND, owner HWND)` relationships are cached, so stable dialogs avoid repeated `GetWindow(GW_OWNER)` calls.
- Cache invalidation clears native chrome, first-click, close-request and interaction state tied to a destroyed/recreated HWND.
- Reconfiguring a native viewport invalidates the previous handle relationship before the new presentation starts.

### Dialog focus handoff stability (1.122.0 / M6n)
- Deferred dialog focus restoration now carries a visibility-generation token; re-showing a dialog invalidates stale close callbacks.
- A newly active same-process top-level supersedes an older dialog's queued focus return, while a visible logical parent remains the preferred Qt-style restoration target.
- Popup close gestures continue to consume the closing release so context menus cannot select the row beneath them.


### Modal pointer handoff stability (1.123.0 / M6o)
- QDialog teardown releases only explicit pointer captures owned by the closing dialog subtree.
- Sibling/tool captures acquired in the same UI turn are preserved, preventing first-click loss after modal close.
- Closing-gesture release latches remain responsible for blocking click-through to background controls.

## Qt Runtime M9 — retained popup damage and host identity

DearUIQt transient UI now follows a stricter Qt-style repaint/ownership contract:

- `QPopupSurface` is the only lifecycle object allowed to pair popup visual state with input ownership.
- popup damage is reported to `QWindowHost.requestUpdate(region)`; hover does not activate native windows or force full-window repaint.
- `QMenu` and `ComboPopup` retain row-local dirty rectangles and invalidate only rows whose visual state changes.
- diagnostics snapshots are read-only and must never call foreground/focus/activation APIs.
- `QGuiRuntime` shares `QWindowHost` by live backend object identity, never by a reusable integer `id()` alone.

These invariants exist specifically to prevent recurrence of invisible-but-clickable popup items, title-bar hover flicker, stale floating popup ownership, and cross-context host aliasing.

### DearUIQt core scheduler diagnostics

DearUIQt core timing is monotonic and event-loop owned. `QTimer`, `QElapsedTimer`, `QDeadlineTimer`, and `QEventDispatcher` must not create private worker timer threads. Runtime diagnostics must be side-effect free: inspect `QEventDispatcher.diagnosticsSnapshot()`, `QApplication.diagnosticsSnapshot()`, or `StandaloneUiHost.scheduler_diagnostics()` rather than pumping events, forcing repaint, activating a window, or reading mutable private queues from feature code.


## QtCore M11 runtime foundation

DearUIQt now distinguishes the core application type from the GUI facade while preserving one process-global singleton:

```text
QCoreApplication
    └── QApplication

QEventDispatcher / QThread
    └── priority-aware queued calls

QObject weak registry
    └── ownership/lifecycle diagnostics only (no ownership)
```

The weak registry is diagnostic infrastructure, not an ownership mechanism. Production ownership remains strictly parent/child + guarded QPointer references.

## QtCore M13 — GUI policy boundary and dispatcher convergence

DearUIQt 1.137.0 tightens the Qt-style separation between core scheduling and GUI policy:

- `QCoreApplication` owns process-global event delivery, posted/native update queues, lifecycle diagnostics and the single host turn only.
- `QApplication` owns focus, active-window, popup/modal, pointer/input backend, mouse-grab and shortcut state.
- Core QObject deletion does not depend on GUI state being present.
- `QThread` workers use a worker-owned `QEventDispatcher`; there is no second private deadline-heap implementation.
- Pre-start worker calls preserve deadline, priority and cancellation when migrated into the worker dispatcher.
- `QGuiRuntime.frameSchedulingSnapshot()` is the public source for deadline + dirty-region + native-presentation urgency used by main/floating hosts.
- Shutdown orphan assertions are opt-in and type-selective; production shutdown remains diagnostic/non-fatal by default.
- Native dialog caption stability remains transition-driven. Stable windows are not periodically polled, preventing recurrence of Close-button hover flicker.

## QtCore M14 runtime boundary

- All GUI/worker schedulers consumed by runtime code must satisfy `QAbstractEventDispatcher`.
- WinUx views expose `eventDispatcher()`; feature/controller code must not read `_dispatcher`.
- `QCoreApplication` does not own or expose style/palette policy; those APIs belong to `QApplication`.
- `QWindowHost` is shared per backend/context and weakly owned by the process application, never by transient `QGuiRuntime` wrappers.
- Frame-idle diagnostics are observational only: sampling them must not consume dirty regions, activate HWNDs, focus widgets or advance the event loop.


## QtCore M16 runtime invariants

- Delayed GUI callbacks have one canonical deadline owner: `QEventDispatcher`. WinUx may coalesce keyed immediate completions, but must not maintain a parallel timer heap.
- `QCoreApplication` contains no renderer input-key/native-mouse constant tables; those belong to `QApplication`.
- Every `QWindowHost` transition is typed and records why teardown occurred; rejected native closes return the same host to `Alive` instead of synthesizing a replacement owner.
- Frame/watchdog diagnostics are read-only and must never consume dirty regions, activate HWNDs, or force a render.


## QtCore M17 runtime invariants

- There is one callback owner per event-loop thread: `QEventDispatcher`. WinUx `UiDispatcher` may translate legacy return values/names but must not own a second callback queue or deadline heap.
- Keyed coalescing is callback-lifetime state. A key is released on cancellation or immediately before delivery, never by a feature-specific wrapper callback.
- `QWindowHost.correlationId()` is stable for one retained host lifetime; a close attempt creates a teardown correlation before `aboutToClose` so transient surfaces can record the causal transition.
- `QPopupSurface` diagnostics preserve the last host correlation after the host pointer is released; diagnostics must not keep the host alive.
- Idle-render health is observational only. Threshold evaluation must not consume dirty regions, pump events, activate/focus HWNDs or force a frame.
- GUI-specific event categories migrate through `DearUIQt.gui.QGuiEventType`; legacy `QEvent` values remain compatibility integers until the physical class move is complete.


## QtCore M18 invariants

- GUI keyboard/pointer/wheel event implementations belong to QtGui. QtCore compatibility imports must resolve to the exact same class object and may not create duplicate event types.
- Host/popup diagnostics may retain only primitive/correlation data in bounded histories; they must never retain native HWND/window objects or extend popup lifetime.
- An input-owning popup must always have a requested visual surface. Transition history is observational and may not repair or mutate an inconsistent popup.
- Performance/watchdog diagnostics are read-only. Threshold checks may log at a bounded cadence but may not schedule render work, pump the GUI event loop, activate HWNDs or consume dirty regions.
- Runtime scheduling tests and feature code should use `eventDispatcher()` and `QGuiRuntime.frameSchedulingSnapshot()` rather than private dispatcher fields.

## QtCore M19 — lazy QtGui boundary, compact lifecycle diagnostics, health hysteresis

- `DearUIQt.core.object` is again backend/GUI-import neutral during module initialization. GUI input event compatibility resolves lazily from the QtCore namespace, while canonical implementations remain in `DearUIQt.gui.events`.
- Runtime code uses canonical dispatcher spellings at internal call sites; snake-case names remain compatibility edges only.
- `QWindowHost` and `QPopupSurface` lifecycle histories are bounded, filterable, and have compact JSON-friendly forms suitable for crash/hang reports without retaining native windows.
- `QGuiRuntime.crashDiagnosticsSnapshot()` exposes compact retained frame/host state to the watchdog.
- Health warnings use consecutive breach/recovery hysteresis in addition to rate limiting. Health diagnostics remain observational and never pump events, invalidate, render, focus, or activate HWNDs.

## QtCore M20 invariants

- `DearUIQt.core.object` must not expose or lazily resolve GUI input event classes. Compatibility is allowed only at the `DearUIQt.core` namespace boundary; canonical GUI-event implementations live in `DearUIQt.gui.events`.
- `QWindowHost` and `QPopupSurface` transition histories use the same immutable `QLifecycleTransitionRecord`. A lifecycle record contains primitive/correlation data only and may never retain a QObject, HWND, viewport or renderer object.
- WinUx `UiDispatcher` is not an alternate scheduler. It owns no callback queue/deadline heap and no legacy queue view; internal code uses canonical `QEventDispatcher` spellings.
- Frame baseline/percentile diagnostics are read-only. Collecting p50/p95 wait data must not consume dirty regions, post work, activate/focus a window or trigger a render.


## QtCore M21 invariants

- Dispatcher latency diagnostics are retained/bounded and side-effect-free; reading them never processes callbacks or changes wake/deadline state.
- Production WinUx code uses `processEvents()`/`diagnosticsSnapshot()`; `UiDispatcher.drain()` and `snapshot()` exist only as compatibility edges and own no scheduling policy.
- Lifecycle history formatting/filtering is centralized; `QWindowHost` and `QPopupSurface` retain only typed primitive transition records.
- Idle-performance warnings are sample-gated. Startup/transient windows cannot arm warnings until both the current and baseline windows meet minimum sample counts.
- Current-vs-baseline performance comparison is observational and may not consume dirty regions, post work, focus/activate HWNDs or force a render.

## QtCore M24 invariants

- Dispatcher performance baselines must be non-overlapping with the current comparison window.
- Priority diagnostics are observational only and never alter Qt-style deadline/priority delivery order.
- Runtime diagnostics must not instantiate the global QThreadPool, create workers, pump events, repaint, activate HWNDs or consume dirty regions.
- WinUx legacy dispatcher methods live outside the primary facade implementation; production scheduling uses the canonical QAbstractEventDispatcher contract.

## M25 performance/fairness invariants

- Priority fairness diagnostics are observational only; they never age, reprioritize or reorder callbacks.
- Long queue-wait callback identity is stored only as a bounded module/qualname string, never as a callable/object reference.
- Thread-pool registry membership is weak; diagnostics cannot keep a dedicated pool alive.
- Release-performance acceptance is sample-gated and reads existing frame/dispatcher histories only; it never pumps events or renders.



# WinUx / DearUIQt QtCore M26 Changes

## DearUIQt 1.150.0

- Added sustained per-priority starvation diagnostics without changing scheduler order.
- Added callback-category latency aggregation using safe bounded string labels only.
- Added QThreadPool category/owner metadata and category totals with weak registry ownership.
- Added explicit JSON performance-envelope snapshot/save/load/compare APIs for release baselines.
- Extended unified runtime performance reports with sustained-starvation and callback-category sections.
- Focused regression: 102 core/runtime tests + 16 task-lane/thread-pool tests pass.


## M29 GUI-thread ownership rule

WinUx has exactly one logical application GUI owner: `QApplication` plus its canonical `QAbstractEventDispatcher`. Worker threads may perform I/O/CPU work and may enqueue completion data, but native/retained UI mutation must execute on the QApplication thread. Repeated latest-value worker writes use dispatcher-level `postLatest()` rather than allocating feature/widget-local scheduler queues. The legacy Tk native-dialog host is a compatibility/native boundary only; zero-delay owner-focus/foreground completion is marshalled back through QApplication before touching main-window ownership.
## M31 native compatibility isolation rule

- Normal WinUx main-process runtime has one application-state/UI dispatcher: `QApplication` + the canonical `QAbstractEventDispatcher`.
- Native compatibility callbacks, including delayed owner-focus/foreground hand-offs, must return through `QCoreApplication.postCall*`; host-specific `view.after()` is standalone/legacy fallback only.
- A release/soak session is GUI-thread clean only when `guiThreadAcceptanceSnapshot().accepted` is true (zero recorded cross-thread GUI mutations).
- The main-process Tk host is legacy compatibility only. Normal WinUx acceptance requires it to remain uncreated; Tk-based Server Notepad UI remains isolated in its helper process.
- Diagnostics/acceptance reads must never instantiate the Tk host, pump events, repaint, activate HWNDs, or create worker threads.



### Keyboard event key-domain rule

After `QApplication` translates renderer/native input into `QKeyEvent`, all retained widget/controller handlers must compare `event.key()` against `Qt.Key_*`. Renderer constants such as Dear PyGui `mvKey_*` belong only at the backend translation boundary. Mixing the two domains can make every shortcut appear dead while focus and dispatch are otherwise correct.
