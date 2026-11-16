WinUx 1.1.7 - DEARUIQT DIALOG AND ITEM-VIEW STABILITY

This release consolidates the current source and verified fixes under version 1.1.7.
Earlier development version headings below are historical notes, not the release version.

Release packaging:
- Rebuilt integrity metadata and retained 1.1.6 bootstrap compatibility in the published package.
- Changes-only archives preserve their manifest-covered README without duplicate ZIP entries.

Item-view scroll continuity

- Fixed repeated spreadsheet selection leaving QTableWidget's current cell at an externally changed row/column; selection now reconciles the real current cell without requesting scrolling.
- Added tests/test_itemview_scroll_retention_ui.py covering lists, grids, trees, item widgets and spreadsheets: scroll, idle, focus, current selection, visible-row clicks and refresh.
- Validated with abaqus python and physical wheel/click input across seven control types and the real-controller Local/Server panes before/after Login, Message and Settings dialogs.
- File/Folder Selector scroll/click/late-callback tests passed; focused item-view regression suite: 42 passed.

Dialog host correction (current source)

- Restored the 1.1.12 DearUIQt owned native dialog default; embedded dialogs are diagnostic opt-out only (WINUX_NATIVE_QDIALOGS=0).
- Fixed missing QtFusionPalette import that aborted message/confirmation content construction.
- Kept native session-tab presentation serialization and synchronous native hide fixes.
- Added abaqus python tests/test_dialog_content_render_ui.py for message roles, Login, Settings and deferred session-tab updates.
- Native validation completed with abaqus python: 21 dialog types in full/PiP mode, physical Login/OK/Cancel/X, cold/nested modals and first presentation/cancellation.
- Updated stale regression fixtures for foreground permission, same-process sibling Z-order and per-session connection creation. Physical-menu tests now diagnose external mouse interference separately.
- Native dialog/focus/chrome unit regression suite: 63 passed.

WinUx 1.2.3 - STABLE SINGLE-CONTEXT APPLICATION DIALOG HOST

- Fixed the persistent blank/white WinUX dialog shell seen with in-process QDialogs on some Windows/GLFW multi-viewport paths.
- Normal WinUx application QDialogs now stay in the primary DearUIQt renderer/context by default. They remain modal, centered over the owner, retained on the same QApplication event loop, and require no worker process or IPC.
- DearUIQt native multi-window support remains enabled for menus/docks and explicit native tools. QDialog native HWNDs can be re-enabled only for renderer diagnostics with WINUX_NATIVE_QDIALOGS=1.
- This removes the fragile implicit dependency between session-tab/main-tree mutations and secondary QDialog platform viewports instead of trying to hide/reveal an already detached blank HWND.

WinUx 1.2.2 - SESSION TAB / NATIVE DIALOG PRESENTATION FIX

- Fixed native dialogs becoming an empty white ``WinUX`` shell after the multi-session tab upgrade.
- Session-tab snapshots are now serialized behind active/pending/retiring native QDialog transactions; the main retained tree is never rebuilt while a secondary dialog viewport owns presentation.
- Login success now closes the Login QDialog before publishing the final session-tab state, matching Qt top-level transition ordering.
- Added a native secondary-window hide fallback independent of owner-close lease capture, so hidden/destroyed QDialogs cannot remain visible while GLFW performs deferred platform-window teardown.
- QDialog hide/destroy now performs the synchronous native visibility cut after releasing modal ownership, while renderer destruction and normal owner-focus repair remain unchanged.
- Added regression coverage for deferred session-tab commit and lease-independent native dialog hiding.

Validation:
- Session/dialog serialization + native isolation: 25 passed.
- Login/session/dialog regression: 46 passed.
- Windows-only USER32 tests remain unavailable on the Linux packaging container and are unchanged by this patch.

WinUx 1.2.1 - MULTI-SESSION DOCUMENT TABS

- Replaced the single visible remote session workflow with Photoshop-style closable session tabs directly below the menu bar.
- Every explicit login creates a new tab with its own stable session ID, SSHServerModel/transport, cached remote path, directory snapshot, Job Viewer snapshot and session task scope.
- Added an always-available + button for creating another login/session and an x close control on every session tab. Closing a background tab does not disturb the active tab; closing the active tab activates the nearest remaining tab.
- Switching tabs changes only the active remote context. The previous tab keeps its SSH transport alive while active-tab polling/navigation work is suspended to prevent cross-session UI writes.
- A session ID remains stable for the lifetime of its tab. Every re-activation receives a fresh operation generation so callbacks/tasks created during an older activation can never become valid again merely because the user returns to the same tab.
- The application-level server alias now follows the active tab workspace. Explorer, Job Viewer, ODB/analysis entry points and other remote controllers therefore resolve the correct session resource without duplicating per-feature server state.
- SSH Console callbacks now resolve the active server dynamically rather than retaining a bound method from the server that existed during application startup.
- Cached Server Explorer rows/path/history and Job Viewer rows are restored immediately when a tab is selected, then refreshed against that tab's live transport.
- Background tabs do not perform heavy Job polling or navigation refresh. A disconnected background transport is reconnected only when that tab becomes active again.
- File > New Session... always creates a new tab. File > Close Session closes only the active tab, and Session Details reports all open tabs plus active/session-scoped task diagnostics.
- The session tab strip participates in application Light/Dark theming and occupies layout height only while at least one remote session exists, preserving splitter/dock geometry when no server tab is open.
- Application shutdown explicitly closes every logical session and requests shutdown of every tab-owned SSH transport, including inactive tabs.
- Local Explorer/workspace state remains process-scoped and is not reset when remote tabs are switched or closed.

Validation:
- Session lifecycle/workspace tests: 11 passed.
- Tab/layout/theme regression: 60 passed + 20 subtests.
- Login/connection/shutdown regression: 49 passed.
- Release pipeline performs complete Python syntax validation, smoke tests, deployment manifest rebuild, exact baseline diff, ZIP integrity checks and manifest hash verification.

WinUx 1.1.99 - ONE LOGIN / ONE APPLICATION SESSION

- Added a centralized AppSessionManager: every explicit SSH login creates exactly one logical WinUx session with a unique session ID and generation.
- SSH reconnect/transport repair stays inside the same logical session; it never creates a second application session.
- Switching accounts/servers ends the previous session first, invalidates its generation and starts a clean replacement session.
- Logout is now an explicit application action and clears remote UI/runtime state without closing WinUx.
- Added File > Log Out and a live read-only Session menu row showing account, state and short session ID; Login becomes Switch Session while connected.
- Session metadata tracks host, port, username, created/connected timestamps, current remote path and reconnect count without storing passwords.
- Remote OperationContext now validates both connection generation and logical session ID so stale callbacks cannot publish into a replacement login.
- Login replacement/logout stops Job polling/plots, transfer and analysis tasks, schedule runtime, server navigation state and the shared SSH transport before the next session is exposed.
- Server/console connected callbacks now require both a usable transport and a valid logical session; Job Viewer user identity is sourced from the current session.
- Schedule recovery is schema-v2 and account-scoped by host/port/username, preventing pending schedule mutations for one login from being written into another server/account after a session switch.
- Full SSH login clears server/ODB capability hint caches so a new account/server cannot inherit discovery state from the previous session.
- Session state is included in the application watchdog diagnostics and contains no credentials.

Validation:
- Session lifecycle, operation-context and account-scoped schedule tests pass.
- Wider session/transfer/login regression: 69 passed + 15 subtests; one WinSCP callback test is confirmed to fail identically in the untouched 1.1.98 baseline.
- Release pipeline performs complete Python syntax validation, smoke tests, deployment manifest rebuild, exact baseline diff, ZIP integrity checks and manifest hash verification.

WinUx 1.1.98 - APPLICATION-WIDE THEME CONSISTENCY

- Expanded the Light/Dark system from window-level palette switching to semantic palette roles used consistently by retained controls, native child editors and tool-specific surfaces.
- Added semantic Success/Warning/Error/Info foreground/background roles so status, progress, validation and notification UI keeps readable contrast in both themes.
- Reworked Explorer inline rename, drag preview, spin editors, combo/select states and central inline-editor factories to use the active Qt/Fusion palette instead of Light-only surfaces.
- Improved File/Folder Selector theming for toolbar glyphs, navigation/search/view actions, dividers, action/footer surfaces and cached icons; retained icon resources are now scoped by Light/Dark scheme.
- Improved docking overlay guides, dock control states, ribbon built-in visual styles and toast notification defaults so newly-created and already-open surfaces follow the current application theme.
- Preserved explicit user-selected Explorer color presets; only application-native Explorer and Job Viewer palettes are synchronized to Light/Dark.
- Improved Regex workbench theming, including the native Windows Rich Edit child: its Win32 erase/background color now follows QtFusionPalette.BASE and live theme changes invalidate stale formatting.
- Improved Compact/PiP Job Viewer controls so title/button/glyph surfaces use the active palette rather than a permanently-dark control skin.
- Improved Plot Digitizer theme propagation across Workflow checklist rows, rounded checkboxes, ribbon menus, canvas view-tool overlays and status/progress surfaces; retained caches now include the active scheme and refresh live.
- Kept plot data colors, terminal ANSI colors, marker/axis semantics and user color presets unchanged so application theme changes do not alter data meaning.

Validation:
- Application-theme + Regex + Plot Digitizer targeted suite: 101 passed, 53 subtests passed.
- Release pipeline performs complete Python syntax validation, smoke tests, deployment manifest rebuild, exact baseline diff, ZIP integrity checks and manifest hash verification.

WinUx 1.1.97 - JOB VIEWER DARK CONTRAST FIX

- Fixed Job Viewer rows that could retain a Light-mode Running/Queued background while text had already switched to the Dark palette.
- Scheduler status colors now derive from the live Qt/Fusion palette roles instead of a separately cached theme flag.
- Added semantic row foreground colors so Running/Queued text always keeps high contrast against its actual row fill.
- ExplorerListView now tracks optional row_text_color metadata and invalidates both retained background and foreground resources during row/theme refresh.
- Job Viewer and Compact/PiP Job Viewer rebind both status background and foreground colors immediately on Light/Dark changes.
- Selection keeps the normal active/inactive selection palette; semantic status text is used only for unselected rows.

Validation:
- Job/theme targeted regression suite: 23 passed, 4 subtests passed.
- Additional Explorer row/selection checks: 8 passed; one unrelated source-contract test is already failing identically in the original 1.1.96 baseline.
- Release pipeline performs full Python syntax validation, smoke tests, manifest hashing and ZIP integrity verification.

WinUx 1.1.96 - DARK JOB STATUS / DOCK TITLE POLISH

- Fixed Job Viewer Running/Queued rows using Light-mode pastel fills while WinUx is in Dark mode; Dark now uses dedicated green/amber semantic surfaces with readable light text.
- Preserved the previous Job Viewer status RGB values exactly in Light mode.
- Added JobsView.refreshTheme() and CompactJobsView.refreshTheme() so existing status rows recolor immediately on a live Light/Dark switch instead of waiting for the next scheduler poll.
- Theme switching now calls the view-level refresh hooks for full and compact Job Viewer surfaces.
- Hardened QDockWidget retained chrome with a palette fingerprint self-check during layout synchronization.
- Bumped the dock-title retained theme resource revision so stale Light TITLE_ACTIVE resources cannot survive into Dark mode; this targets the remaining light SSH Console title strip.

Validation:
- Theme/menu/dock/console/Job Viewer regression suite: 53 passed.
- Job status palette and global theme contract suite: 10 passed.
- Release pipeline performs full Python syntax validation, smoke tests, manifest hashing and ZIP integrity verification.

WinUx 1.1.95 - DARK RETAINED MENU / DOCK REFRESH

- Fixed top-level File/Bookmarks/Commands/Reference/View/Help popup menus retaining Light surfaces after switching WinUx to Dark mode.
- QMenuBar now refreshes both menu-bar buttons and every owned QMenu popup; retained QMenu instances also self-refresh before opening when the application palette has changed.
- Added QDockWidget.refreshTheme() so the SSH Console and Plot dock title strip, content frame, title text, float/close controls, vector glyphs and dock context menu all follow the active Light/Dark palette live.
- Runtime theme switching now refreshes the QObject-owned main-window widget tree plus non-QObject retained docks/Job Plot clients.
- Job Plot dock/toolbars/panels/menus/tooltips now rebind their palette resources on a live theme switch while preserving the existing Light-mode history text color.
- Hardened QMenu hover damage updates so lightweight/test backends without a popup damage callback do not fail during row state transitions.

Validation:
- Theme/menu/dock targeted regression suite: 55 passed.
- Focused menu/theme regression suite after hover hardening: 28 passed.
- The Windows coordinate-space test remains platform-only because ctypes.windll is unavailable in the Linux validation container.
- Modified modules compile successfully; final release validation parses the complete Python tree.

WinUx 1.1.94 - DARK DIALOG PALETTE REBIND FIX

- Fixed Settings and other already-open dialogs that could remain partially Light after switching the application to Dark mode.
- QDialog now tracks palette-derived raw Dear PyGui helper surfaces and rebinds navigation panes, form-label cells, notes/status text and raw tables during a live theme change.
- QGroupBox and QListView/QListWidget now refresh their retained theme resources and row visuals instead of keeping the palette that existed at construction time.
- QPushButton styling no longer uses hard-coded white faces in Dark mode; Light mode keeps the existing pixel appearance.
- Plot/axis popup surfaces now follow Dark mode while preserving the previous Light palette exactly.
- Native Windows dialog captions now retry the legacy dark-mode DWM attribute when needed and force a non-client repaint so title bars change immediately.
- Settings status feedback now keeps its current error/muted palette binding across subsequent Light/Dark switches.

Validation:
- Theme-specific regression suite: 11 passed.
- Settings/dialog/list/menu/font/plot regression suite: 48 passed.
- Full suite reached 734 passed / 1,356 subtests before the first Linux-only ctypes.windll test limitation; the failure is platform-specific and unrelated to these changes.
- All 1,583 Python files parse successfully.

WinUx 1.1.93 - GLOBAL LIVE THEME SYNCHRONIZATION

- Extended Settings > General > Appearance > Theme so Light/Dark is one application-wide state rather than a main-window-only preference.
- Every floating dialog worker now receives the current theme before form construction, preventing a light first frame while WinUx is in Dark mode.
- Saving a new theme broadcasts it live to every open floating dialog; no restart or dialog reopen is required.
- Added centralized DearUIQt QDialog refresh for window/body/footer chrome, controls, tables, context menus, combo popups and styled tooltips.
- Added explicit live refresh hooks for File/Folder Selector, Transfer Center, Reference Chart and SSH Console custom surfaces.
- Theme resource caches for dialogs, model views, menus, combos and tooltips are invalidated/re-materialized safely across palette changes.
- Main window and floating-dialog Windows title bars/borders/text now follow the active Light/Dark palette, including saved-theme startup.
- File selector Explorer palette is refreshed with the active color scheme instead of retaining Light-mode colors.

Validation:
- Global theme/dialog pipeline regression suite: 11 passed.
- Broad theme/font/menu/scrollbar/dialog regression run: 87 passed; one unrelated pre-existing ODB launcher source-contract test remains stale.
- Modified Python modules compile successfully.

WinUx 1.1.92 - LIGHT / DARK APPLICATION THEME

- Added Settings > General > Appearance > Theme with Light and Dark choices.
- Persists ui_theme in the shared settings.json; existing profiles default safely to Light.
- Applies the saved palette before retained UI/theme resources are created at startup.
- Save applies the selected theme live to the main window, menu bar, Local/Server file panels, Job Viewer, status surfaces and dialogs opened afterwards.
- Dark mode uses a dedicated Qt/Fusion palette for windows, editors, buttons, tables, menus, selections, borders, tooltips and scrollbars without changing control geometry.
- Theme cache keys are scheme-aware so Light and Dark resources cannot accidentally reuse stale colors from the other scheme.
- Added regression coverage for theme normalization, persistence, palette switching and Settings/runtime wiring.

Validation:
- Theme/font/Settings/menu/scrollbar regression subset: 29 passed.
- Modified DearUIQt and WinUx Python modules compile successfully.
- One unrelated pre-existing Explorer palette test remains stale in the 1.1.91 baseline (its expected RGB values already disagree with the original source).

WinUx 1.1.91 - FONT-AWARE CONTROL GEOMETRY

- DearUIQt control metrics now account for the active application font line height in addition to DPI.
- Live font changes refresh widget themes and root layouts so controls resize/recenter without restarting WinUx.
- QPushButton auto-height and sizeHint are font-metric driven; button text remains centered as font family/size changes.
- QLineEdit and QComboBox refresh typography-dependent padding/height without recreating native controls.
- Existing 15 px UI typography retains the established baseline dimensions; larger/smaller fonts scale control chrome safely.

WinUx 1.1.90 - FONT DIALOG STABLE RESET

- Reset the Font Dialog implementation to the proven 1.1.79 stable baseline.
- Removed the experimental per-row font binding, viewport raster overlays, list-local raster canvases, and related font-preview resource paths introduced in 1.1.80-1.1.89.
- Restored the balanced Font / Font style / Size / Sample / Script layout and the stable type-to-select behavior.
- Family list rows use the normal UI font; the selected face is represented in Sample preview only. This intentionally prioritizes native stability over per-row face rendering.

WinUx 1.1.79 - FONT DIALOG LAYOUT BALANCE

- Increased QFontDialog vertical room from font metrics so Script and its combo are fully visible above the footer.
- Anchored OK / Cancel to the lower-right using a true expanding box-layout stretch.
- Reduced the lower-left spacer and tightened lower-right spacing for a more Windows-like silhouette.
- Kept lazy single-face font preview and table-free dialog construction unchanged.

WinUx 1.1.78 - FONT DIALOG TYPE-TO-SELECT

- Improved Font Dialog keyboard search: typing a family prefix moves the list to the nearest match without replacing the text being typed.
- Font style and Sample preview now follow the highlighted family immediately while typing.
- OK resolves an incomplete typed prefix to the currently highlighted installed family, preventing invalid partial family names from being saved.
- Direct row clicks still synchronize the editor to the full family name.
- Preserves the lazy single-face preview strategy and all previous native-crash guards.

WinUx 1.1.77 - FONT DIALOG POLISH

- Centered the Sample preview and gave it metric-driven minimum dimensions for a more Windows-like preview area.
- Expanded the Script selector to the full lower-right width.
- Direct Size typing now synchronizes the size list and refreshes the live preview immediately.
- Preserved lazy single-face font loading and the table-free dialog architecture to avoid the native crashes fixed in earlier releases.

WinUx 1.1.76 - SAFE ASCII UI SEPARATORS

- Replaced the Settings font summary separator with ASCII-safe hyphens so selected fonts without a middle-dot glyph do not show stray characters.
- Normalized common UI ellipsis/truncation markers in core controls and the local folder selector from the Unicode ellipsis glyph to plain ASCII "...".
- Keeps typography customization intact while avoiding glyph/encoding artifacts with older or niche installed fonts.

WinUx 1.1.75 - SIMPLIFIED FONT SETTINGS

- Simplified Settings > General > Appearance to a single font summary and Choose Font... action.
- Removed separate App font, Font style and Font size controls from Settings.
- QFontDialog is now the only editor for family/style/size; selection is stored as one internal typography state.
- Save persists the selected family/style/size together and keeps the existing application typography apply path.

WinUx 1.1.74 - TALLER FONT SELECTOR

- Increased QFontDialog height using active font line spacing rather than fixed UI pixels.
- Increased Font and Size visible rows from 10 to 13 so the taller dialog provides useful list space.
- Raised the minimum dialog height while preserving metric-driven layout and the existing Sample/Script/footer proportions.

WinUx 1.1.73 - SAFE LAZY FONT PREVIEW

- Removed bulk loading/binding of every installed font face when QFontDialog opens.
- Font-family face preview is now lazy and limited to the currently selected row.
- Live Sample preview reuses the same bounded font cache instead of expanding the atlas for the full catalog.
- Dynamic preview skips TTC collections and unusually large font files to avoid native DearPyGui/ImGui font-atlas crashes.
- Preserves the real Font style combobox and existing family/style/size behavior.

WinUx 1.1.72 - FONT SELECTOR INIT ORDER FIX

- Fixed QFontDialog constructor crash caused by currentSelection() reading script_combo before Script controls were created.
- Family-row font preview now reads the already-created size editor directly during construction instead of asking for a full dialog selection.
- currentSelection() now safely falls back to the first script while the Script combo has not yet been constructed.
- Added regression coverage for partial-construction safety.

WinUx 1.1.71 - FONT STYLE COMBOBOX MODEL SYNC

- Fixed Font style QComboBox showing an empty preview even though style items existed in the model.
- QFontDialog now constructs the style combo with the initial family styles instead of starting with an empty item list.
- Family changes now clear/repopulate the style model and explicitly synchronize the retained ComboField preview text.
- Keeps the standard Regular / Bold / Italic / Bold Italic options visible for every family.

WinUx 1.1.70 - REAL FONT STYLE COMBOBOX

- Replaced the Font style text/list pair with a real DearUIQt QComboBox.
- Font style popup is repopulated whenever the selected font family changes.
- Regular / Bold / Italic / Bold Italic are always presented first, followed by family-specific installed styles.
- Font family rows now bind their representative font directly to the native selectable row; no setItemWidget replacement labels are used.
- Fixes misplaced family preview labels and the empty Font style area seen in 1.1.69.

WinUx 1.1.69 - FONT SELECTOR STYLE OPTIONS + FACE PREVIEW

- Font family rows now render using the font face they represent, making the list visually match Windows more closely.
- Font style rows now render using the selected family/style face when available.
- Restored standard style options (Regular / Bold / Italic / Bold Italic) so the style list does not collapse to a single entry when Windows reports only one installed face.
- Improved face resolution fallback for preview/runtime so synthetic style choices prefer the closest installed bold/italic face before falling back to the regular face.

WinUx 1.1.68 - TABLE-FREE FONT SELECTOR

- Rebuilt DearUIQt QFontDialog with QHBoxLayout/QVBoxLayout instead of table-backed QGridLayout/QFormLayout.
- Removed table-backed QDialogButtonBox usage from the font selector footer.
- Preserved Windows-like family/style/size columns, Sample/Script region, live preview and metric-driven sizing.
- Eliminates the nested mvTable/add_table construction path that caused SystemError while opening Font Selector from Settings.
- Added regression coverage preventing table-backed layout primitives from returning to QFontDialog.

WinUx 1.1.67 - SAFE FONT SELECTOR OPEN
- Fixed QFontDialog crashing with DearPyGui add_table SystemError when opened from Settings.
- Font selector construction is now queued until QApplication native pointer-release dispatch has completed.
- Added a pending-open guard to prevent duplicate selectors from repeated clicks in the same input transaction.
- Deferred creation aborts safely if Settings closes before the queued callback runs.
- No font selector layout or typography behavior was regressed.

WinUx 1.1.66 - WINDOWS-LIKE FONT SELECTOR
- Refined DearUIQt QFontDialog proportions to more closely match the Windows Font dialog.
- Increased font/style/size list height and metric-driven native-like column ratios.
- Moved Sample and Script into the lower-right region, leaving the lower-left region open like Windows.
- Font typing now keeps the full catalog visible and moves selection to the nearest prefix.
- Double-clicking family/style/size accepts the current font selection.
- All geometry remains derived from active QFontMetrics.

WinUx 1.1.65 - CUSTOM FONT SELECTOR
- Added reusable DearUIQt QFontDialog with Windows-style Family / Font style / Size columns.
- Added live font preview and script selector.
- Settings > General > Appearance now exposes Font style and Choose Font... .
- Persists ui_font_family, ui_font_style and ui_font_size and applies the selected face live.
- Font selector geometry is derived from active QFontMetrics (text width and line spacing).
- Toolbar/floating-host typography caches now include font style.

WinUx 1.1.64 - FONT-METRIC-DRIVEN DIALOG LAYOUT
- Dialog/message-box geometry is calculated from the active font metrics.
- Buttons use measured text width plus metric-derived padding; footer/button height follows line spacing.
- Message icons scale and vertically center against the measured heading/message block.
- Compact dialog width/height follows measured wrapping instead of fixed Segoe UI assumptions.

WinUx 1.1.63 - live application typography

Fixes Settings > General > Appearance saving App font / Font size without updating the running UI.

Changes:
- Rebinds the DearUIQt application font immediately after Settings is saved.
- Rebinds existing Explorer/ListView body rows, headers and pinned-row text without rebuilding list state.
- Updates Local/Server path-bar fonts in the same live apply pass.
- Preserves selection, scroll position, hover state and virtualized row ownership while typography changes.
- Forces an immediate UI frame so the new font is visible as soon as Settings closes.
- Keeps the selected font persisted for the next launch.

Validation:
- Typography preference/runtime wiring tests pass.
- Modified Python modules compile successfully.

WinUx 1.1.62 - application font preferences

Adds persistent application-wide typography controls to Settings > General.

Changes:
- Added App font selector populated from installed Windows fonts.
- Added Font size control with safe 10-24 px bounds.
- Saves ui_font_family and ui_font_size in the shared settings.json.
- Applies the selected typography at startup to the main WinUx DearUIQt context.
- Explorer/ListView body text, headers and native rename editor follow the selected family/size.
- Floating dialogs and standalone Plot Digitizer hosts use the same saved typography.
- SSH Console keeps Consolas for monospace alignment but follows the selected app font size.
- Missing/uninstalled saved fonts automatically fall back to Segoe UI.
- Font changes are intentionally applied after restart to avoid replacing live renderer font handles.

Validation:
- New typography preference regression tests pass.
- Settings layout contract passes.
- GeneralPreferences compatibility test for unrelated settings passes.
- Modified Python modules compile successfully.

WinUx 1.1.10 - Settings layout refinement

Improves every Settings tab without changing preference behavior.

Layout changes:
- General uses shorter help text and a compact CPU-estimation form.
- File Colors separates rule editing from ordering actions and aligns the selected-rule editor.
- Updates keeps version/channel/actions in one compact form.
- Performance uses consistent numeric editor widths instead of stretching controls across the page.
- Abaqus Versions aligns the command editor, action row and default-command combo.
- Saved Login presents Host, Username and Password as separate property rows.
- DearUIQt QFormLayout now supports an optional preferred editor-column width with trailing stretch space.
- Settings navigation uses the shared Qt/Fusion navigation width and slightly larger default dialog geometry.

Validation:
- Portable Settings layout contract test passes.
- Modified Python modules compile successfully.

WinUx 1.1.10 - version check downgrade guard

Fixes Settings > Updates incorrectly offering GitHub v1.1.7 when the installed build is v1.1.10.

Root cause:
- settings_form.py passed <deployment>/WinUx instead of the deployment root to check_for_updates().
- VERSION therefore appeared missing and the GitHub provider treated v1.1.7 as a recovery candidate.

Fixes:
- Settings resolves the correct deployment root.
- updater.py also walks nested caller paths back to the nearest VERSION-owning deployment root.
- Settings independently reconciles local/server semantic versions and never enables Update Now when remote <= local.
- Update Now handler blocks stale downgrade candidates before launching the updater.
- Added regression tests for nested UI paths and contradictory/stale update state.
