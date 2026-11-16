# WinUx Deep Stability / Multi-Session / Cleanup Audit

## Scope

This pass reviewed session ownership, asynchronous worker lifetime, retry/timer
coalescing, transfer behavior across session switches, per-session task scopes,
Session Manager metrics, remote worker server capture, and selected UI/runtime
robustness paths.

## Key findings and fixes

### 1. Stable task ownership across session re-activation

Previously `SessionToken.task_scope` included the activation generation. A session
can receive a new generation each time its tab is activated, so a long-running
transfer started under an older generation could become unreachable by a later
`cancel_scope()` when that same session was closed.

Task scope is now stable for the lifetime of the logical session:

`session:<session_id>`

Generation remains separate and continues to invalidate stale UI callbacks.

### 2. Session switching no longer cancels active transfers

Switching from session A to B now cancels stale UI/background/analysis work but
leaves A's transfer lane running. Closing A still cancels A's transfer scope and
shuts down A's SSH transport.

### 3. Remote workers capture their server instance

Controller background workers were audited for late `self.server` resolution.
That pattern is unsafe because `self.server` aliases the currently active tab and
may point at a different SSH session by the time the worker runs.

Remote workers in the audited controllers now capture the session/server at
operation creation. A static AST audit reports zero worker functions under
`WinUx/controllers` that directly dereference `self.server`.

Affected areas include:

- Job submission / job actions / job refresh fallback
- INP analysis
- SSH console refresh
- Sync Preview
- Clipboard transfer and server clipboard staging
- Explorer create/delete/rename/navigation
- Server Notepad stream/save paths
- Schedule manifest synchronization

### 4. Schedule retry callbacks are bounded and account-scoped

Schedule manifest retry logic previously used raw delayed callbacks. Repeated SSH
errors could enqueue duplicate callbacks, and a callback created for account A
could execute after account B became active.

Retries are now coalesced by `(operation, account_key)`. Stale callbacks become
inert after an account/session switch.

### 5. Session Manager RAM metric cost reduced

The Session Manager refreshes every second. Recursive session RAM estimation can
visit up to tens of thousands of Python objects, so recomputing it every second
for every session was unnecessary overhead.

Per-session estimated RAM is now cached for 5 seconds while state, uptime and task
counts remain live at the normal refresh cadence. Closed-session metric cache
entries are pruned. The runtime snapshot now also includes the actual WinUx
process working set where the OS supports it.

### 6. Sync Preview delivery is session-aware

Sync Preview now captures `OperationContext` and the original SSH server. Worker
completion uses guarded UI posting so a result from an old session cannot populate
a newly active session.

### 7. Plot Digitizer painter construction made backend-safe

Axis/data marker painter construction no longer assumes `QPainter` is always a
concrete class object. This improves compatibility with injected/test renderers
without changing production rendering behavior.

### 8. Code cleanup

- Removed an unused `QMenu` import left behind after the transfer speed selector
  migrated to the shared `QComboBox`.
- Full package output removes `__pycache__`, `.pyc`, and `.pytest_cache` artifacts.
- Existing compatibility alias modules remain intentionally in place; they already
  forward to canonical implementations and are not duplicate implementations.

## Validation

- Focused multi-session lifecycle tests: PASS.
- New stable-scope / switch-transfer regression: PASS.
- New account-scoped retry/coalescing regression: PASS.
- Broad multi-session / transfer / ODB / console / job / sync-preview selection:
  156 tests + 31 subtests PASS.
- Additional explorer/clipboard/notepad/transfer selection:
  89 tests + 40 subtests PASS.
- Full suite reached 741 tests + 1,356 subtests PASS before the first Windows-only
  `ctypes.windll` test failed in the Linux sandbox.
- With that platform-only test excluded, suite reached 831 tests + 1,368 subtests
  before a native DearPyGui extension test unavailable in the sandbox.
- With native-only tests excluded, suite reached 881 tests + 1,402 subtests before
  a pre-existing Plot Digitizer Music Sales OCR failure. The same OCR failure was
  reproduced on the pre-audit baseline, so it is not a regression from this pass.
- Python compilation: all 700 source files under WinUx, DearUIQt and winux_runtime
  compiled successfully.

## Ownership rule going forward

1. App-global: theme, font, settings, local panel, shared layout/resource caches.
2. Session-lifetime: SSH server, transfers, session workspace, account journal.
3. Activation-generation: visible remote navigation/UI callbacks and stale-result
   protection.
4. Remote worker rule: capture `OperationContext`/server before submit; never read
   the active `app.server` alias lazily from a background worker.
