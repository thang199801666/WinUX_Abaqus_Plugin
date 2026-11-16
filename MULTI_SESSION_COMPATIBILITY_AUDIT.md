# WinUx Multi-Session Compatibility Audit

## Ownership policy

### App-global (intentionally shared)
- Theme / font / settings
- Main-window geometry, docking and splitter ratios
- Local filesystem panel and local-only operations
- Shared resource/icon/font caches

### Session-owned / remote
- SSHServerModel / transport
- Remote explorer path, directory snapshot and history
- Job list snapshot and remote job operations
- SSH console remote callbacks
- Remote ODB operations
- Server notepad
- Remote transfer / conflict review operations
- Session task scopes and reconnect state

## Guards added in this audit
- OperationContext captures the server object that belonged to the active session at operation creation; asynchronous workers must not resolve app.server lazily after a tab switch.
- Session switching no longer calls Transfer Center cancel_all(), because the dialog is application-global and can contain local-only or other-session work. Scope cancellation remains the authority for remote work.
- SSH console completion is session-scoped, captures its original server, and drops stale completion delivery after a session switch.
- JobViewer ODB resolution is session-scoped, captures its original server, and cannot publish into another active session.
- Remote ODB check / upgrade / catalog / extraction workers capture the original session server and suppress stale UI completion after switching.
- Transfer conflict metadata/review and quick-transfer preflight capture the original session server and are session-scoped where a remote panel is involved.
- Transfer completion from an inactive original session cannot refresh or show errors in the newly active session.
- Close Session still cancels only the task scope owned by that session and disconnects only that workspace server.
- Local-only tasks remain independent of login-session switching.

## Verification
- Multi-session/session lifecycle, console, transfers/conflicts, recursive transfer, ODB local+remote, JobViewer, schedules, server notepad, login/focus, docking/splitter, theme/font regression set: 190 tests passed + 31 subtests.
- Full WinUx / DearUIQt / winux_runtime compile: PASS.
