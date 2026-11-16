# WinUx Memory Stability Audit

This audit targets process-lifetime growth that can accumulate during long-running WinUx sessions.

## Guards added

- File panel navigation history is capped at 256 entries.
- SSH hidden/submission echo queues are capped at 128 pending entries each.
- Remote ODB/Abaqus compatibility caches are capped at 256 entries per cache.
- Explorer retained-item facade cache is periodically cleared and reset on rebuild/destroy.
- Explorer per-item icon/cell customization maps are pruned when the model is replaced.
- Explorer custom textures and font databases are released when a ListView is destroyed.
- Retired application/Explorer/path font databases are kept for only a small number of generations and older registries are deleted.
- Retired toolbar/theme resources are bounded and old native theme resources are explicitly deleted.

## Existing bounded systems verified

- SSH transcript uses BoundedTextBuffer.
- Terminal scrollback/history and styled-row caches are bounded.
- Notification history is bounded.
- Dock command history and dispatcher diagnostic histories are bounded.
- Transfer progress is coalesced by file instead of enqueueing one callback per network chunk.

## Regression validation

Targeted memory/font/theme, Explorer/resource, ODB, and FilePanel tests passed after the changes.
