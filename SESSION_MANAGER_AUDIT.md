# Session Manager

- Added File > Session Manager...
- Displays all open login sessions.
- Columns: Session, State, Opened at, Open time, RAM (est.), Transport, Tasks.
- RAM (est.) measures Python/cache data owned by each logical session. All sessions share one WinUx process, so OS working-set RAM cannot be attributed exactly per session.
- Footer shows total estimated session cache RAM and actual WinUx process working-set RAM.
- Refreshes every 1 second while open.
- Double-click/Activate switches the active session.
- Close Session uses the existing session-close confirmation flow.
