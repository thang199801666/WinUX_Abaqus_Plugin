# WinUx optimization goal

Status: active. User-authorized scope: remove god classes, improve performance
without losing features or responsiveness, reduce server stress through adaptive
algorithms, and build Qt-style wrappers over Dear PyGui/Dear ImGui.

## Acceptance criteria

- Large classes have focused responsibilities and delegate to independent,
  testable components. Moving a monolith unchanged into a mixin is insufficient.
- Existing callable feature surface is preserved. Newly introduced regressions
  are fixed; existing failures are tracked explicitly.
- Background reads, polling and rendering remain bounded. Interactive actions
  bypass idle backoff; cancellation and shutdown remain responsive.
- Server query counts, latency and UI update overhead have reproducible
  measurements under stable, changing, slow and failing workloads.
- Qt-style widgets provide ownership, signals, queued UI updates, layouts and
  consistent styling. Real application forms adopt the wrappers incrementally.
- Native UI verification uses a compatible Dear PyGui runtime; unavailable live
  SSH/native checks are recorded rather than treated as passed.

## Work sequence

1. Establish behavioral baselines and fix portable test failures where valid.
2. Add latency-aware bounded polling and jitter; consolidate duplicate server
   observations without allowing stale results to affect destructive operations.
3. Add UI wrapper foundations and coalesced display updates; migrate forms while
   preserving existing callback and keyboard/modal contracts.
4. Extract local navigation/watch, clipboard, Server Notepad coordination and
   analysis workflows from the app controller.
5. Decompose Explorer interaction/lifecycle, Notepad process orchestration,
   floating/native window hosting and splitter layout into focused owners.
6. Measure workloads, verify contracts and document remaining platform limits.

Prior completed passes and test limits are recorded in `REFACTOR_NOTES.md`.
This goal stays active until the required implementation and verification work
is actually complete.

## Foundation progress

- Implemented `CostAwarePollingPolicy` and adopted it in the shared qstat poller.
  It blends existing change/quiet backoff with EWMA query cost and bounded jitter.
  Known changes and manual refreshes retain fast polling. All delays stay within
  existing user-configured minimum/maximum limits. Quiet external changes may be
  observed later as backoff grows; this is an explicit server-load/freshness
  tradeoff, not a claim of identical detection latency under every workload.
- A deterministic five-minute simulation produced 12 -> 10 queries for a quiet
  four-second-response server, and 14 -> 14 for a fast 0.1-second server. This
  measures modeled query counts, not live server CPU utilization.
- Added ownership/signals, queued widget setters, duplicate-write suppression
  and native box containers in `WinUx/widgets`; adopted labels/progress bars in
  ProgressDialog. Added LatestCallQueue to bound visual update bursts.
- Fifteen new tests cover budget limits, fast recovery, EWMA, concurrent/coalesced
  updates, widget ownership, signals and disposal. The 10,000-update burst queues
  one callback. Six existing adaptive-polling functions and four feature-surface
  checks passed. Native rendering and live SSH have not been verified.
- Full unittest discovery: 407 tests, the same existing 15 failures and 13 errors
  as the prior baseline, with no new failing/error IDs. Report:
  `tools/goal_foundation_tests.json`.

God-class decomposition, broader wrapper adoption, cross-feature remote query
coordination, native verification and comprehensive profiling remain pending.

## Navigation and watcher decomposition

- Extracted NavigationController and LocalWatchController. The facade remains
  compatible; the watcher component owns its locks, generation and refresh state.
  App controller size decreased from 2,805 to 2,516 lines in this pass.
- File/directory probing and native watcher installation/joining now happen in
  workers. Superseded startup/local/server requests skip their I/O. Remote
  navigation also discards results from a replaced SSH connection generation.
- Watcher read keys include generation to prevent coalescing an old-directory
  read with a new-directory read. Rejected refresh submissions release active
  state and retry through one debounced callback. Rename/drag begun during a
  directory read delays publication until the interaction ends. Scroll restore
  callbacks verify path/generation before modifying the pane.
- Added 17 behavioral tests; a 10,000-notification burst schedules one refresh,
  and events during that read schedule one followup. Four feature-integrity
  checks and seven fast-shutdown tests passed. Full unittest discovery ran 424
  tests with unchanged 15 failures and 13 errors; no new failure/error IDs.
- Installed pytest in a temporary test-only directory (no runtime dependency).
  Fixed conftest's ignore hook to defer decisions using None so --ignore works.
  The broader pytest run, excluding four modules that cannot import the native
  DLL, ran 538 tests: 515 passed and 23 failed. Twenty-two failures correspond to
  the known obsolete native-dialog expectations or missing native DLL. One
  additional cross-platform path assertion was fixed to test serialization
  against the input Path representation, and all 12 standalone controller tests
  then passed. This is broader coverage than the unittest baseline, not a claim
  of a clean complete suite.
- Logs: `tools/navigation_watch_tests.json`, `tools/pytest_navigation_watch.log`.
  Native watcher/GUI behavior still needs compatible-runtime verification.
- Final targeted pytest run: 56/56 passed across navigation, watcher, controller
  components, feature integrity, shutdown, runtime optimization and transfer
  stability tests.
- Native dependency inspection found `python310.dll` in the shipped Dear PyGui
  extension. The available bundled interpreter is Python 3.12.14; no `abaqus`
  command is on PATH. This explains why that interpreter cannot verify the
  shipped Python-3.10 native GUI extension. Continue portable work while retaining
  native verification as an outstanding acceptance requirement.

## Server Notepad coordination decomposition

- Extracted ServerNotepadController. App controller decreased from 2,516 to
  2,350 lines; its historical Notepad callbacks delegate to the component.
- Load/reload share one streaming pipeline rather than duplicate callbacks,
  timing, failure delivery and worker setup. The service's bounded IPC/SFTP
  backpressure and transactional write/signature checks remain unchanged.
- A read token scoped to dialog/path cancels superseded work and checks the SSH
  generation before reads and each outgoing frame. Queued completion also
  validates generation. Closed windows/shutdown drop work and release tokens.
  ENOENT retry is bounded to one retry and uses a cancellable 150 ms wait.
- Rejected load/save tasks now report failure to the editor. Pending saves
  refuse to execute after SSH generation changes. This does not yet bind every
  document's complete lifetime to a host identity; that broader reconnect/edit
  behavior still needs review.
- Added 13 behavioral tests covering stream order, shared load/reload, bounded
  retry, cancellation, reconnection, shutdown, queue rejection, save signatures
  and conflict routing. Targeted pytest: 81 passed and two subtests passed.
  Full unittest: 437 tests, unchanged 15 failures and 13 errors, no new IDs.
  Changed sources compile successfully. Report: `tools/notepad_controller_tests.json`.
- Clipboard, analysis, Explorer/Notepad process and window-host god classes,
  broader Qt-style wrapper adoption and native-runtime verification remain work
  toward the original goal. Goal remains active.

## File clipboard decomposition and Cut retry load

- Extracted FileClipboardController and ClipboardTransferController, with
  ClipboardCache and ServerCutMonitor as focused services. Historical facade
  signatures remain intact. Main controller decreased from 2,350 to about
  2,033 lines.
- Paste freezes source selection/destination before worker execution. Completion
  clears internal clipboard only if its generation still matches, preserving a
  later Copy/Cut. Queue rejection reports an error instead of leaving progress
  pending. Snapshot mkdir/cleanup runs on background workers; cleanup validates
  a direct child under the cache before deleting anything.
- A single lazy daemon Cut supervisor replaces one thread per Cut. It performs
  local staged-path checks while idle, without SSH queries; failed remote deletes
  use bounded exponential retries starting after the attempt finishes. A test
  with persistent delete errors produces six attempts in 60 virtual seconds.
- Cut batches and pending clipboard preparation belong to their captured SSH
  generation. Reconnect invalidates old batches rather than deleting sources in
  a replacement session; stale server clipboard state cannot route paste to that
  session. Existing staged snapshots may still be pasted as local files.
- Added 15 tests for frozen requests, stale completions/session changes, bounded
  retries, idle server load, shared thread ownership, queue rejection and cache
  confinement. Targeted pytest: 47 passed. Full unittest: 452 tests, unchanged
  15 failures and 13 errors; no new failure/error IDs. Report:
  `tools/clipboard_component_tests.json`. Changed sources compile successfully.
- Source metadata/content revalidation before remote Cut commit, true Explorer
  integration and production-native verification remain outstanding. Analysis
  flows, large Explorer/Notepad/window classes and broader UI wrapper adoption
  still need work. Goal remains active.

## INP/ODB analysis and job-submission decomposition

- Extracted InpAnalysisController, OdbAnalysisController and
  JobSubmissionController. Existing controller method signatures remain as
  compatibility facades; the feature-integrity contracts pass. Main controller
  decreased from about 2,033 to 1,860 lines. Its many facade methods and other
  large modules mean the god-class acceptance criterion is still outstanding.
- Added OperationContext to guard worker startup and queued UI delivery against
  shutdown, destroyed dialog/window and changed SSH generation. Core suggestions
  check the generation before each file read; job submission stops before the
  next job if its session changes. Queue rejection now reports failure instead
  of leaving analysis or submission pending.
- Job parameters and ODB selections are copied before queuing. ODB extraction
  keys now include the entire selection, including X/Y grouping, rather than
  only the union of history IDs. Distinct pairings therefore retain their own
  requested work. Analysis remains on its existing single-worker bounded lane.
- Added 13 behavioral tests for stale sessions/results, closed-window delivery,
  frozen inputs, distinct pairing keys and queue rejection. Targeted pytest:
  72 passed. Full unittest: 465 tests, unchanged 15 failures and 13 errors; no
  new failure/error IDs. Report: `tools/analysis_component_tests.json`.
  Changed sources compile successfully; current metrics are saved in
  `tools/refactor_current.json`.
- In-flight Abaqus subprocess interruption and native GUI/SSH integration have
  not been verified. Guarding generations does not make a remote request already
  executing cancellable or eliminate the narrow reconnect race during dispatch.
  Further large-class decomposition, Qt-style wrapper adoption, native runtime
  verification and performance measurements remain required. Goal stays active.

## Explorer row-model ownership and refresh cost

- Added a GUI-independent ExplorerItemModel which owns rows, ordering and
  identity reconciliation. ExplorerListView delegates replacement and the
  data-view mixin delegates sorting; the existing writable `items` attribute is
  preserved through a property. Stable path/job/name identities retain existing
  metadata-refresh and row-reuse behavior. This is composition with a separately
  owned model, rather than another behavior mixin sharing all view state.
- Metadata refresh computes old/new identities once each and restores selection,
  anchor and keyboard current position in one pass. Sorting uses cached name/type
  values without eagerly calculating the fallback casefold; parent/folder-first
  ordering remains independent of sort direction. Keyboard sorting now also
  remaps current position, fixing navigation to an unrelated row after sorting.
  Object-based reorder avoids allocating topology lists for ordinary header sorts.
- Added 11 tests, including actual facade method execution with a test-only DPG
  boundary, row reuse/rebuild, all sort columns/directions, session-independent
  metadata identities and keyboard remapping. Targeted pytest: 30 passed. Full
  unittest: 476 tests, unchanged 15 failures and 13 errors, no new IDs.
  Reports: `tools/explorer_model_tests.json`, `tools/refactor_current.json`.
- The portable benchmark compares the preceding reconciliation/sort algorithm
  with the new model and checks equivalent results before timing. Median refresh
  time: 1,000 rows 4.33 ms -> 1.72 ms (2.52x); 20,000 rows 83.35 ms -> 20.93 ms
  (3.98x). Sources/results: `tools/benchmark_explorer_model.py` and its JSON.
  These measurements exclude native rendering, SSH and end-to-end frame latency.
- Large Explorer native-hook/input/theme responsibilities, Notepad process and
  window/layout classes still require decomposition. Broader Qt-style wrappers
  and native integration/performance verification remain outstanding. Goal is
  active.

## Qt-style signal delivery and dialog ownership

- Added SignalConnection handles with idempotent disconnect, automatic QObject
  bound-receiver tracking and opt-in queued delivery via the receiver's UI
  scheduler. Queued signals preserve each event; display-property setters keep
  their separate latest-value coalescing. Disconnect/deletion invalidates pending
  signal deliveries, preventing callbacks into a disposed receiver.
- Added QObject.setParent with cycle/deleted-parent validation and QSignalBlocker
  with nested-state restoration. Wrapper children inherit the backend/scheduler;
  constructing under a deleted parent is refused before native control creation.
  Disposal releases sibling widgets and native items even if a destroyed-signal
  handler raises. Native construction/deletion remain UI-thread responsibilities.
- QtDialog's shared action path now creates owned QPushButton wrappers, preserving
  its returned native IDs, accept/default callbacks, dimensions and theme roles.
  ProgressDialog explicitly owns its label/bar wrappers. Closing releases their
  queued state and signal connections. This adoption applies to the existing
  shared QtDialog forms, including floating-process forms using that base.
- Added 13 behavioral tests for queued order/thread delivery, connection disposal,
  ownership/reparenting, inherited scheduler/backend, nested blocking, exception
  cleanup and the actual shared action method's callback/default/disposal contract.
  Targeted pytest: 51 passed. Full unittest: 489 tests, unchanged 15 failures and
  13 errors, no new IDs. Report: `tools/widget_signal_tests.json`. Changed modules
  compile. Main and floating runtimes already use manual DPG callback management.
- Native rendering, pixel-level appearance and end-to-end frame cost remain
  unverified with the shipped Python-3.10 DPG extension. Rich form layouts,
  additional control wrappers and broader god-class decomposition remain work;
  the original goal is still active.

## Explorer keyboard command ownership

- Extracted 21 keyboard/shortcut methods into a composed
  ExplorerKeyboardController. The existing methods remain thin facades with
  unchanged signatures, preserving registered native handler callbacks and the
  public callable-surface contract. GUI/input boundaries are injected, allowing
  behavioral tests without importing Dear PyGui. ExplorerListView decreased from
  2,731 to 2,540 lines; native hooks, theme and interaction construction still
  remain substantial responsibilities, so the god-class criterion is not done.
- Corrected Ctrl+Shift+Arrow selection-change notification and stale/removed
  current/anchor/selection indices. Ctrl+Arrow still moves current position alone;
  single-selection, range, popup/rename precedence, Escape, clipboard-owner
  routing and standalone fallback behavior remain covered.
- Arrow/Home/End no longer query an unused page-size rectangle: the page-size
  read occurs only for PageUp/PageDown. The visible-row scroll guard retains its
  existing read and skips native scroll writes when the target is already visible.
- Added 18 behavioral tests and a composition contract. Targeted pytest before
  the final composition contract: 65 passed. Full unittest: 507 tests, unchanged
  15 failures and 13 errors, no new IDs. Report: `tools/explorer_keyboard_tests.json`.
  Changed modules compile and current metrics are updated. Native keyboard/focus
  integration and end-to-end frame timings still require verification.
- The preceding turn produced concrete state changes and regression evidence.
  Further decomposition, rich Qt-style wrapper adoption and native performance
  validation remain required for the original active goal.

## Isolated native Dear PyGui verification

- Checked common Python 3.10 installation paths and Abaqus runtime availability;
  no usable interpreter/launcher was found. `D:/ABQ2026` contains include/lib
  assets, not an executable runtime. The shipped vendor DPG is 2.3.1 with a
  Python-3.10 extension; the available bundled host interpreter is Python 3.12.14.
- Installed DPG 2.3.1 for the host interpreter into a temporary test-only
  directory. Added `tools/run_native_tests.py` to preload this same-version
  backend and host Pillow before WinUx's vendor selection. It validates the DPG
  version and prints environment/scope metadata. Production vendor files and
  application startup are unchanged.
- Added five real-native-item tests for parent containment/disposal, button
  callbacks/dimensions/enabled state, line-edit signal blocking, worker progress
  coalescing/clamping and late callbacks after deletion. Contexts are created
  without showing a viewport. The isolated wrapper plus existing dialog-migration
  suite passes all 14 tests, exercising actual Dear PyGui controls rather than
  only fake backends. Portable native-test collection is explicitly handled.
- Broader isolated-native pytest: 615 passed, eight subtests passed, 21 failed.
  All failing tests are in `test_native_dialogs.py` and assert obsolete Tk/native
  architecture predating the existing floating DPG migration. Full output is
  `tools/pytest_native_context.log`. The previous lazy-view import/DLL error is
  resolved in this environment. Three test modules requiring actual floating
  Abaqus processes/windows were excluded explicitly; their behavior is not proven.
- Native item behavior is now verified on the same DPG version with a host ABI.
  Visible appearance/render performance, production Python-3.10/Abaqus ABI and
  live server behavior still need verification. Obsolete dialog regression
  contracts should be updated against actual current behavior, preserving their
  lifecycle/threading intent. Large-class removal and fuller wrappers remain
  incomplete, so the goal stays active.

## Current dialog regression contracts and schedule refresh

- Retargeted the 21 obsolete Tk/dialog assertions to the current floating DPG
  architecture. Public aliases must resolve to FloatingDialogController-backed
  adapters; forms must retain shared labeled sections/footer layout. Scheduling
  checks now execute the shared date/duration parsers, preserving second
  resolution, future-date validation and legacy delete-date compatibility.
  Headless execution of both form/adaptor `finish` methods checks one result,
  close-before-callback and deferred delivery. Existing applicable native-host
  chrome, modal/focus and ownership assertions remain. All 33 contracts pass.
- Restored the intended Job Schedule incremental update behavior: unchanged
  snapshots do not rewrite cells/buttons/status; changing only a countdown writes
  only that cell. Rebuilt rows retain their initial native text. Incoming rows are
  captured as tuples before the snapshot is stored.
- Fixed an ownership leak exposed by shared QPushButton adoption: deleting a
  schedule row now releases wrappers/connections in its native subtree before
  deleting the container. A real DPG test rebuilds rows ten times and verifies
  wrapper count remains bounded, then verifies clearing removes row ownership.
  Another native test verifies zero unchanged writes and one changed-cell write.
- Isolated-native full regression, excluding the same three actual floating
  Abaqus-window/process modules: **638 passed and eight subtests passed**, no
  failures. Output: `tools/pytest_native_context.log`. Portable unittest: 508
  tests, zero assertion failures, seven environment/import errors and one native
  skip; report `tools/dialog_contract_tests.json`. Remaining errors are shipped
  DPG ABI imports/lazy-view import and pytest-only modules in the plain stdlib run.
  Changed sources compile. Headless dialog contracts are collected on non-Windows.
- These results verify item creation, form behavior, scheduling and ownership in
  the isolated host backend. Actual child viewport positioning/input/rendering,
  Abaqus runtime compatibility and live SSH performance remain unverified; large
  class decomposition and richer wrappers still require work. Goal stays active.

## Explorer resource responsibilities

- Moved ListViewTheme/ListViewThemeManager into GUI-independent explorer_themes,
  WindowsCursorFile into platform/windows_cursors and DragPreviewHelper into its
  own draw-layer component. ExplorerListView re-exports the historical names, so
  existing imports and callable signatures remain compatible. No theme values,
  native cursor algorithms or preview drawing behavior were intentionally changed.
- Explorer list-view module decreased from 2,540 to 1,838 lines; its resource
  registries/helpers no longer share the facade source. This is meaningful module
  responsibility separation, but native-hook methods and mixed view interaction
  state remain; it does not alone prove elimination of every god class.
- Added six portable behavioral tests for theme aliases, detached resolution,
  registration/inheritance/removal, invalid names, cursor path/size caching and
  non-Windows fallback. A real DPG test verifies lazy drag-layer construction,
  active-state reset and native draw-item disposal. Existing style contracts now
  inspect their actual resource owner while preserving the same palette assertions.
- Isolated-native full regression: **645 passed and eight subtests passed**,
  using the established three explicit Abaqus-window module exclusions. Output:
  `tools/pytest_native_context.log`; current source metrics:
  `tools/refactor_current.json`. All feature-surface checks pass in this run.
- Resource extraction makes no new end-to-end performance claim. Native viewport
  rendering/Abaqus compatibility, live SSH measurements, remaining large classes
  and richer Qt-like layout/control adoption remain outstanding. Goal stays active.

## Floating-dialog IPC display backpressure

- Added LatestCommandQueue, a bounded standard Queue-compatible FIFO with
  opt-in replacement of unsent display state. Ordinary commands create barriers:
  a later state update cannot replace an earlier update across a Run/Cancel/Fail
  or other command. The normal command path retains FIFO/full-queue reporting;
  display replacement is accepted even at capacity when that key already exists.
  Queue locking, wakeups, timeout and task accounting remain tested.
- FloatingDialogController now exposes post_latest. Transfer progress, console
  output, schedule snapshots and diagnostics reports use it; state encoding and
  socket writes stay on the existing IPC writer. Init, user actions, cancellation,
  failure, visibility and other commands retain ordinary post semantics.
- Fixed the child ProgressDialog's external `cancelling` command to set its
  cancellation guard, preventing a later queued progress state from replacing
  the cancellation caption. The real native control test confirms this behavior.
- Added eight portable queue/controller-method tests: a burst of 10,000 progress
  states occupies one slot with the final value, concurrent producers retain one
  slot per key, command barriers preserve before/after order, full capacity does
  not drop commands, and closed/full controller posting behaves explicitly.
  This measures pending-message reduction, not real IPC throughput or frame rate.
- Isolated-native full regression: **654 passed and eight subtests passed**, with
  the established three actual Abaqus-window module exclusions. Full output:
  `tools/pytest_native_context.log`. Changed modules compile. The child receiver
  already has a bounded 64-message queue, retaining transport backpressure.
- In-flight sends cannot be replaced and the optimization does not change remote
  SSH polling itself. Actual floating-window stress/render tests, live server
  measurements, remaining god classes and richer wrapper adoption remain required.
  The original goal stays active.

## Notepad search/controller ownership

- Extracted eight search/result-navigation/replacement methods into
  ServerNotepadSearchController. It owns the search generation, pending sliced
  search and result metadata. Compatibility properties connect the remaining
  background-index mixin to that same state; facade signatures remain unchanged.
  Find/Replace dialog construction stays with the window. Search IntVar instances
  now have an explicit owning window instead of relying on Tk's default root.
- Server-notepad process source decreased from 2,185 to 1,942 lines. Its remaining
  UI construction, highlighting, tabs and process transport still need separation;
  this extraction does not establish completion of the god-class requirement.
- Preserved the large-file background-index path and the editable-text fallback's
  80-results/8-ms per-slice limits, 5,000-result cap and generation checks. Added
  eight behavioral tests for literal and regex replacement, invalid/no-match
  handling, backward wrap options, cancel generation, stale-result suppression,
  bounded/resumed Find All and background-index preference.
- Isolated-native full regression: **662 passed and eight subtests passed**,
  with the established three actual Abaqus-window module exclusions. Output:
  `tools/pytest_native_context.log`; updated metrics: `tools/refactor_current.json`.
  Changed sources compile. Notepad search behavior is checked at its widget
  boundary without creating a Tk root; actual editor rendering remains unverified.
- Live SSH stress measurements, native/Abaqus integration, remaining large-class
  decomposition and richer Qt-style control/layout adoption remain necessary.
  Goal stays active.

## Notepad viewport highlighter and duplicate-work suppression

- Extracted syntax rules and three highlight/configuration/scheduling methods
  into ServerNotepadHighlighter. Language patterns are compiled once in a bounded
  16-entry cache; all eight existing language rules and normal-text behavior are
  retained. Main Notepad process source decreased from 1,942 to 1,821 lines.
- Per-document snapshots identify text widget, document index generation,
  language, viewport bounds and sampled content. An identical snapshot skips
  regex scanning and native tag removal/addition. Edits/reloads invalidate through
  generation/content, scrolling through bounds and language/style changes through
  language/configuration. Snapshot retention is capped at 200,000 characters;
  larger viewport samples retain the existing uncached highlighting behavior.
- Debounce callbacks carry a document generation, so cancellation failure cannot
  allow an older pending callback to run in place of newer work. Existing normal
  and performance-mode delays remain unchanged. Added seven behavioral tests
  for skipping, invalidation, bounded retention, stale callbacks, unloaded docs
  and all language rules (eight subtests).
- Portable benchmark for 100 identical viewport passes: tag operations decreased
  from 50,700 to 507 (99% reduction); Python-boundary median 125.76 ms -> 1.63 ms.
  It compares this highlighter with/without snapshot reuse and excludes Tk
  rendering/IPC, typing under edits, and end-to-end frame latency. Sources/results:
  `tools/benchmark_notepad_highlight.py` and its JSON.
- Isolated-native full regression: **669 passed and 16 subtests passed**, with
  the established three actual Abaqus-window module exclusions. Full output:
  `tools/pytest_native_context.log`. Changed sources compile and current metrics
  are refreshed. Live editor/Tk rendering, server stress, production Abaqus ABI,
  remaining god classes and richer Qt-style wrappers remain incomplete. Goal
  stays active.

## Explorer Win32 hook state and shell-drop ownership

- Extracted viewport lookup, WNDPROC installation/restoration and cursor geometry
  into ExplorerNativeHook. It owns all native handle/callback/cursor/geometry
  fields. Compatibility properties and four thin facade methods retain existing
  mixin/caller access. GUI backend and shared Explorer registry are injected;
  class-level drop routing and external cursor-provider semantics remain intact.
  ExplorerListView source decreased from 1,838 to 1,498 lines.
- Fixed drop-registration lifetime across multiple hooks on the same HWND.
  Attempting to remove a non-top hook no longer disables shell drops. Removing
  the active top hook preserves registration while another owner remains; only
  the final successfully removed owner disables acceptance. Deferred/failed
  restoration retains callback ownership, preventing disposal of a callback that
  still participates in the native chain. Failed installation cleans up its own
  drop registration when no other owner exists.
- Shell file-drop enumeration now releases its handle in a finally block, even
  if a native query fails. Added six behavioral Win32-boundary tests for deferred
  and failed restoration, stacked/final owners, idempotent removal, Unicode paths,
  drop coordinates/handle release and invalid header geometry.
- Isolated-native full regression: **675 passed and 16 subtests passed**, with
  the established three Abaqus-window module exclusions. Full output:
  `tools/pytest_native_context.log`; metrics: `tools/refactor_current.json`.
  Changed sources compile. These hook tests mock OS calls; actual WNDPROC dispatch
  and externally subclassed window teardown still need real-HWND verification.
- Main controller, Notepad, native host, modern dialog and layout classes remain
  large/mixed; complete god-class removal is unproven. Live SSH stress, production
  Abaqus/render checks and fuller Qt-like controls/layouts remain work toward the
  original active goal.

## Real hidden-HWND Explorer hook verification

- Added four Win32 integration tests using actual hidden STATIC-class windows;
  no viewport is shown and no mouse/keyboard automation is used. Real
  SetWindowLong/WNDPROC callbacks install a two-hook chain, defer non-top removal,
  restore in order and preserve WS_EX_ACCEPTFILES until the last owner leaves.
  WM_SETTEXT/WM_GETTEXT verify forwarding to the original native procedure.
- A real WM_SETCURSOR dispatch with a failing external provider verifies the
  exception stays within the ctypes callback guard and the hook remains alive.
  The test covers native callback dispatch rather than merely invoking Python
  methods against fake API objects.
- Destroyed-HWND testing exposed a missing cleanup path: native teardown now
  checks IsWindow and forgets callback/state/drop ownership when no native window
  remains. It avoids trying to restore a vanished WNDPROC or retaining that
  window's registry entry. Active-window deferred removal still retains callbacks.
- All four real-HWND tests plus six existing OS-boundary tests pass. Isolated
  native full regression: **679 passed and 16 subtests passed**, with the same
  three actual Abaqus-window module exclusions. Full output is
  `tools/pytest_native_context.log`; changed sources compile.
- This verifies hook dispatch/restoration/ownership in the host Python ABI.
  Actual Explorer/GLFW input routing, shell-generated HDROP data, visible render
  behavior and production Abaqus compatibility remain separate unproven gates.
  Remaining god classes, richer wrappers and live server performance still need
  work; the original goal remains active.

## Job action composition and SSH-session guards

- Moved Job menu dispatch, deferred modal handling, confirmation callbacks and
  background action execution into `controllers/job_actions.py`. Historical
  controller methods keep their signatures and delegate through a lazily created
  component. Main controller shrank from 1860 to 1742 lines in this pass; the
  remaining 196 methods include many compatibility facades and still require
  architectural work.
- Capture the SSH generation before queuing modals or commands. Cancellation
  confirmation and edit callbacks reject a replacement session; queued workers
  check before contacting the server, and old result callbacks cannot navigate
  or publish into the replacement session. This removes unnecessary server
  calls for already-obsolete queued actions without adding polling or requests.
- Report rejected background tasks explicitly. Hot Download progress terminates
  on queue rejection or a stale queued session; its progress callback requests
  cancellation if the session changes during transfer. Local destination and
  selected job identifiers remain bound to the original request.
- Fourteen behavior tests cover stale modal/confirmation/edit/workers/results,
  owner and shutdown guards, queue rejection, progress cancellation, successful
  download/navigation, plot toggling and normal refresh. Existing architecture
  tests now check the facade and actual component location.
- Isolated native-context regression: **693 passed and 22 subtests passed**;
  the same three actual Abaqus-window modules remain excluded. Changed sources
  compile; current AST metrics are in `tools/refactor_current.json` and regression
  output in `tools/pytest_native_context.log`.
- No live SSH throughput or visible UI measurement is claimed. A generation
  check cannot interrupt a remote command already executing; the narrow race
  between checking and starting a server call still needs a session-bound
  transport design. Live integration, remaining god classes and richer Qt-style
  wrappers remain unfinished, so the original goal stays active.

## Checkbox wrappers and native interaction ordering

- Added exported `QCheckBox` with boolean `toggled`, checked/text setters, UI-only
  getter, inherited scheduler/backend, parent ownership and QSignalBlocker
  support. Login remember and Settings auto-login now own these wrappers while
  preserving existing native field IDs and value snapshots.
- Native line-edit and checkbox input now invalidates older queued worker
  display values before publishing signals. A user action that keeps the same
  checkbox value still invalidates the old queued value; this prevents queued
  synchronization overwriting newer interaction. Duplicate setter writes are
  suppressed; a test with 1000 worker updates produces one pending callback,
  one native write and one final signal rather than 1000 intermediate writes.
- Native Login integration exposed context-dependent stale numeric theme IDs in
  the editable QtComboBox. All four combo/input theme caches now use stable
  aliases, preventing old IDs from binding unrelated controls after context
  recreation. This fixes an actual full-suite failure, not just a source check.
- Eight portable tests and four native-context tests cover signal blocking,
  latest updates, input ordering, ownership/deletion, getters, Login snapshots
  and recreation of all combo themes. Broad regression: **705 passed and
  22 subtests passed**, with the same three actual Abaqus-window exclusions.
  Changed modules compile; metrics and regression output are updated under tools.
- Native tests create items without showing a viewport. Visible rendering,
  production ABI, real server throughput, remaining large classes and richer
  layout/focus/style contracts remain unverified or incomplete. The original
  objective stays active.

## Retained Server Notepad tab strip

- Extracted `_EditorTabStrip` and `_ToolTip` into
  `components/server_notepad_tabs.py`, retaining historical imports from the
  standalone process and existing callable signatures. Process module shrank
  from 1821 to 1567 lines; editor window construction still needs decomposition.
- Tab synchronization preserves cells and their bound callbacks for unchanged
  document objects. Only removed or replaced documents dispose their cells;
  new documents create tabs. Repacking happens on structural/order changes,
  including replacement at the same path, and existing title/active styles and
  scrolling behavior remain. Batch updates ensure active visibility once rather
  than invoking it while processing each retained tab.
- Tooltip widgets bind destruction to timer cancellation and popup removal,
  preventing a removed tab leaving a pending tooltip or orphan tooltip window.
- Four portable behavior tests and one actual Tk integration test verify no
  new frames across 20 synchronizations of 12 tabs, retained identity, title
  changes, native packing order, replacement close callbacks, complete cleanup
  and tooltip disposal. Tk integration passes with the isolated elevated test
  runner; the restricted plain invocation skips when its Tk display is absent.
- `tools/benchmark_notepad_tabs.py` compares full recreation against retention
  using hidden real Tk widgets (12 tabs, 20 updates, median of five runs):
  **977.08 ms versus 128.46 ms, 7.61x** in this host run. Results are saved in
  `tools/benchmark_notepad_tabs.json`; this is local widget-update evidence,
  not visible FPS, end-to-end application latency or a server-load measurement.
- Full isolated native-context regression: **710 passed and 22 subtests passed**
  with the same three actual Abaqus-window exclusions. Sources compile; metrics
  and `tools/pytest_native_context.log` are updated. No live-server validation or
  completion of the remaining god-class/layout work is claimed; goal stays active.

## File command composition and asynchronous server creation

- Extracted command dispatch, delete confirmation/worker completion and inline
  rename coordination into `controllers/file_commands.py`. Nine historical
  methods retain their signatures as facades. Main controller shrank from
  1742 to 1545 lines; its many compatibility methods and remaining responsibilities
  still need further work.
- Confirmation callbacks bind to the originating SSH generation. Old remote
  delete confirmations and inline rename callbacks cannot run against a newly
  connected server. Queued remote deletion checks the session before its server
  call and protects UI delivery. Queue rejection reports failure without issuing
  a refresh; actual partial deletion failures still refresh as before.
- Remote new-file/new-folder calls now run through the existing background task
  manager, preserving command events. They capture the requested directory,
  reject stale queued sessions, report queue exhaustion and initiate inline
  rename only if the pane still displays the requested directory. Existing
  remote filesystem creation methods serialize their wire transactions.
- Fourteen behavior tests cover confirmation selection snapshots, stale session
  boundaries, queue rejection, partial failure, local delete/shutdown behavior,
  async creation, navigation changes, rename success/error and existing shortcut,
  clipboard and transfer pipelines. Existing source contract checks now inspect
  the component plus facade rather than assuming implementation remains inline.
- Full isolated regression: **724 passed and 24 subtests passed**, with the same
  three actual Abaqus-window exclusions. Changed sources compile; metrics and
  `tools/pytest_native_context.log` are updated.
- No live SSH latency/throughput gain is claimed. Inline remote rename still uses
  its existing synchronous return-value contract and needs an asynchronous editor
  completion design. Generation checks do not interrupt an already executing
  command or eliminate the check-to-dispatch transport race. Remaining god-class,
  wrapper and real-runtime gates remain unfinished; original goal stays active.

## Asynchronous inline server rename

- Added toolkit-independent one-shot `runtime/rename_result.py` and wired its
  pending/success/failure contract through FileCommandController, FilePanel and
  ExplorerRenameMixin. Remote rename now starts on the existing background
  manager and never performs the SSH rename inline in the render callback.
  Local rename retains its existing synchronous path/result behavior.
- Explorer keeps the rename editor open during the operation, suppresses repeated
  commit requests while pending, closes/notifies selection on success, and
  refocuses for retry on failure. FilePanel retains the original commit callback
  on failure and releases it on success only when it still owns that callback.
  Closing/replacing an editor invalidates the old editor-completion transition.
- Session generation guards suppress queued old-session calls and stale result
  publication. Queue rejection and exceptions settle the pending result and
  report failure rather than leaving the editor waiting indefinitely. A result
  for a different directory or newer editor avoids refresh/navigation that would
  disrupt current editing. Error-dialog refocus is also callback/session scoped.
- Eleven additional behavior tests exercise actual production editor/panel
  methods through an AST harness without native imports, plus controller worker
  boundaries. They cover pending duplicate suppression, retry, late/once-only
  completion, callback replacement, queue rejection, session/directory changes
  and an old completion that must not refresh away a new editor.
- Full isolated native regression: **735 passed and 28 subtests passed** with
  the same three actual Abaqus-window exclusions. Sources compile and metrics/
  regression output are updated. Tests prove state transitions and dispatch;
  visible native editor integration and live SSH latency still need verification.
- Closing a pending editor does not undo a rename already dispatched on the
  server. Session checking still cannot atomically bind a model call to the
  captured transport or interrupt a remote command in flight. Remaining class,
  wrapper, rendering and real server-performance gates keep the goal active.

## Preserve refresh freshness while coalescing concurrent demand

- Removed the qstat poller's assumption that any running query already covers
  refreshes arriving during that query. A scheduler snapshot may precede the
  submit/cancel that requests refresh. The wakeup/fast events now remain pending
  until the next loop, yielding one immediate follow-up snapshot for a burst
  rather than silently deferring to the ordinary polling timer.
- A real-thread concurrency test holds the first mocked scheduler call open,
  issues 1000 refresh requests, and verifies exactly two queries total: the
  running query and one immediate follow-up. This verifies bounded burst demand
  without pretending a query that started before an action is necessarily fresh.
- Before-poller fallback workers now capture the SSH generation, skip replaced
  sessions, use connection-scoped coalescing keys and report rejected queues.
  If the long-lived poller started while the fallback was waiting, the fallback
  wakes it instead of issuing another qstat in parallel.
- Five behavior tests cover thread/event coalescing and fallback startup/session/
  rejection boundaries. Isolated full regression: **740 passed and 28 subtests
  passed**, with the same three actual Abaqus-window exclusions. Sources compile;
  metrics and `tools/pytest_native_context.log` are updated.
- Query-count evidence uses a mocked server and real poller thread, not a live
  PBS server. Explicit refresh during a running query can correctly cost one
  additional query compared with the former freshness assumption. Passive
  adaptive limits/cost budgeting remain; live throughput, remaining god classes
  and broader UI/runtime verification keep the original goal active.

## Console renderer composition and caret-only blinking

- Moved viewport drawing from ConsoleDialog into injectable
  `components/console_renderer.py`. The `_paint` facade and dock/dialog sharing
  remain. Native drawing is separated from command, selection and find handling;
  some renderer-facing compatibility state still resides in the view and needs
  further decomposition.
- Caret blink is no longer part of the transcript paint signature. Blinking
  configures only the existing caret rectangle; it does not delete/recreate
  transcript, selection or find draw items. Canvas size writes are skipped when
  unchanged, and font/character geometry now participates in repaint invalidation.
  Existing scrolling, visible-row drawing, find and selection behavior remains.
- Six portable renderer tests cover unchanged frames, caret blinking, new text,
  font geometry, find/pending caret suppression, selection and resize. A native
  Dear PyGui context test verifies real text items remain alive while the caret
  visibility changes. Source contracts follow the extracted renderer location.
- Native item microbenchmark (`tools/benchmark_console_draw.py/json`): 60 blink
  updates, 100 transcript lines and five repetitions. Repainting visible text
  takes **15.02 ms** versus **2.14 ms** for caret-only updates (**7.03x** in this
  host run). Native text creations and deletions each drop from **1080 to 0**
  after initial paint. Viewport metrics are injected, no viewport/GPU frame is
  shown, and these timings do not establish visible FPS or end-to-end app speed.
- Full isolated regression: **747 passed and 28 subtests passed**, with the same
  three actual Abaqus-window exclusions. Changed sources compile; metrics and
  regression output are updated. Remaining god classes, richer wrappers, visible
  integration and live server performance keep the original objective active.

## Owned grid layout and shared dialog field adoption

- Added/exported `QGridLayout`, backed by a native table with retained owned cell
  containers. It supports lazy row creation, fixed or stretching columns and
  moving a QWidget together with its QObject ownership. Invalid dimensions,
  positions, cross-backend placement and ownership cycles are rejected before
  mutation. Repeated access/placement avoids duplicate native creation/moves.
- Native move failure leaves original ownership intact; partial row construction
  disposes created cells/row and can be retried. Grid disposal clears the owned
  tree and cell caches. Worker-thread operations reject native access.
- QtDialog's common labeled-widget path now uses owned grid/label wrappers with
  the existing fixed label width. It preserves builder return values, restores
  the native container stack and removes a partially built form row on failure.
  Existing form controls retain their public native IDs.
- Eight portable tests and two native-context tests cover retained cells,
  ownership/movement/deletion, construction rollback, validation, labeled-field
  parent/value preservation and failing builder cleanup. Existing native Login
  integration also passes through the adopted field path.
- Full isolated regression: **757 passed and 28 subtests passed**, with the same
  three actual Abaqus-window exclusions. Sources compile; current metrics and
  `tools/pytest_native_context.log` are updated. Widget README includes usage and
  limitations. Grid spans, constraint solving and responsive/focus policies
  remain unsupported; visible layout and construction/per-frame cost still need
  measurement. This does not prove the complete UI/performance goal achieved.

## Server Notepad layout composition and actual hidden-window construction

- Extracted window construction, dock headers, menus, toolbar and load-progress
  presentation into `services/server_notepad_layout.py`. Five historical methods
  delegate to an owned ServerNotepadLayout; document/load/save/search callbacks
  remain on the window. Main process module shrank from **1567 to 1069 lines**.
  The layout has one construction/presentation responsibility; remaining window
  and IPC responsibilities still need decomposition.
- Preserve the original styling, native notebook/tab strip, menus, keyboard
  bindings, shared scroller, prepared icon assets, docks and status fields.
  PhotoImage now explicitly belongs to the editor's Tk root, avoiding accidental
  default-root ownership when multiple Tk roots exist in one process.
- Added one portable progress test and two actual Tk integration tests. The
  integration creates the complete real ServerNotepadWindow with deiconification
  and native activation suppressed, mocks saved-state loading, and cancels its
  scheduled timers before disposal. It verifies native notebook/toolbar/status/
  tab widgets, prepared images, shortcuts, Save-menu callback and progress packing.
  No visible window, live server requests or user preference writes are involved.
- Existing toolbar/dock/scroller source contracts now inspect the component's
  authoritative implementation rather than requiring it in the old process file.
  Full isolated regression: **760 passed and 28 subtests passed**, with the same
  three actual Abaqus-window exclusions. Changed sources compile; metrics and
  regression output are updated under tools.
- This pass establishes composition and native widget construction evidence,
  not visible appearance, frame rate, live SSH performance or production ABI.
  Other large classes and richer wrapper/integration gates remain unfinished;
  the original objective stays active.

## Server Notepad command/IPC and Explorer interaction decomposition

- Server Notepad bootstrap no longer owns keyboard/IPC routing internals.
  Shortcut and parent-command dispatch live in `server_notepad_commands.py`;
  bounded JSON-lines IPC, compression/decompression and Tk pump scheduling live
  in `server_notepad_ipc.py`. `server_notepad_process.py` dropped from 1069 to
  760 lines without changing its historical callable surface.
- Large save compression remains on the writer thread and compressed snapshot
  expansion remains on the reader thread, so Tk continues to receive normal
  Unicode payloads without doing zlib/base64 work in the interactive frame.
- Explorer/native drag orchestration moved out of `controller.py` into
  `ExplorerTransferInteractionMixin`. The transfer engine was intentionally not
  rewritten: conflict/progress/cancel/overwrite semantics remain in
  `TransferController`. Cached cross-pane destinations are preserved for the
  native-capture release race.
- Repaired the native hook teardown regression found by the baseline gate before
  continuing refactor work. Full regression now reports **733 passed, 11 skipped
  and 28 subtests passed**; compileall passes. Native Win32/Tk-visible behavior
  still requires a Windows GUI smoke run.
- `controller.py` is now 1288 lines (from 1545 at the start of this pass). The
  next high-value orchestration targets are `view.py`, `splitter_layout.py` and
  `explorer_list_view.py`, followed by worker/timer ownership review across
  dialog/view services.
