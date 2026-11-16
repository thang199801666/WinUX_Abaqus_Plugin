# ListView Selection / Scroll Stability Audit

## Fixed causes

1. **Implicit scroll on focus acquisition**
   - `QItemViewPolicyMixin.setFocus()` used to call `_focus_current()`.
   - A stale current row could therefore reclaim the viewport when a list merely regained focus.
   - Focus acquisition is now scroll-neutral. Explicit keyboard navigation/`scrollTo` remains responsible for intended movement.

2. **Explorer current-index fallback after refresh/sort**
   - `ExplorerItemModel.replace()` / `reorder()` promoted `min(selected)` to current when the previous current identity disappeared.
   - This could promote row 0/first selected row and later pull selection/focus/scroll back there.
   - Refresh/sort now leaves current invalid until a real user gesture or explicit caller chooses a new current row.

3. **Delayed local-watch scroll restoration**
   - Local watcher still contained deferred scroll-restore callbacks after incremental refresh.
   - A delayed callback could run after a new wheel/scrollbar gesture and rewind the viewport.
   - Incremental refresh now leaves the existing native scroll owner untouched and never queues a delayed restore.

## Existing guards retained

- `QItemSelectionModel.setCurrentRemovalFallbackEnabled(False)` for item views.
- `QtItemViewState.replace()` does not invent a first current row.
- File selector async results preserve live selection/scroll and use interaction revisions to reject stale restoration.
- File selector wheel interaction invalidates deferred scroll restoration.

## Validation

- 57 tests + 4 subtests: item-view navigation, programmatic current, Explorer refresh, file panel, selector stability, watcher/thread flow.
- 33 tests: selector UI stability, QListView/QTableView updates, structural selection/current policy.
- Total: 90 tests passed + 4 subtests.
