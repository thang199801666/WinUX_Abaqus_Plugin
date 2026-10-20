# DearUIQt

DearUIQt is a reusable retained-mode desktop GUI library with a Qt-inspired API
and a Dear PyGui renderer.  It is application-independent: **DearUIQt must not import WinUx**.

An experimental [native multi-window backend](native/README.md) now builds
independent Win32 windows in one process/context, without Qt or per-dialog IPC.
Library hosts enable it explicitly. WinUx selects an ABI-matched installed
runtime automatically and routes its reference tools to retained native forms.

## Public package layout

- `DearUIQt.core` — QObject, events, signals, geometry, timers, threads, futures and processes.
- `DearUIQt.gui` — actions, palette/style, retained `QPainter`/`QPen`/`QBrush`, owned `QPaintLayer`/font/texture resources, system facades (`QCursor`, `QKeyboard`, `QClipboard`, `QFontMetrics`, `QScreen`), `QStandardItem` and other non-widget GUI types.
- `DearUIQt.widgets` — controls, windows, dialogs, `QCanvas`/`QViewportCanvas`, non-owning `QRetainedItem` adapters, `QToolTip`, `QPlotWidget`/axes/series, docking and composite widgets such as `QInlineEditPanel`.
- `DearUIQt.layouts` — box/grid/form layouts and splitter primitives.
- `DearUIQt.modelview` — item models and list/table/tree views.
- `DearUIQt.backends` — renderer boundary; Dear PyGui is loaded lazily and can be injected in tests.
- `DearUIQt.interop` — public interoperability adapters (currently Tk/ttk scrollers) that keep consuming applications away from backend implementation modules.
- `DearUIQt.themes` — renderer-neutral theme specs, QObject-owned `QTheme` resources and backend-resolving public theme factories.
- `DearUIQt.docking`, `DearUIQt.ribbon` — higher-level desktop shell components.
- `DearUIQt.runtime` — standalone host and `QGuiRuntime` context/viewport/render-loop lifecycle boundary.

`DearUIQt.QtCore`, `QtGui`, `QtWidgets`, `DearUIQt.qt` and historical ImGui names
remain compatibility facades. New application code should prefer the public
packages above.

## Dependency direction

```text
application (WinUx, other apps)
        ↓
widgets / modelview / layouts / gui
        ↓
core
        ↓
backends (Dear PyGui today)
```

Application-specific behavior belongs in the consuming application, never in
DearUIQt. Backend-specific native calls are being progressively isolated behind
`DearUIQt.backends` and widget implementation modules.

### Renderer-neutral application code

Application modules should import widgets from `DearUIQt.widgets`, policy from
`DearUIQt.gui`, and declarative styling from `DearUIQt.themes`. Public theme factories
resolve the active renderer automatically, so consumers should call e.g.
`tool_bar_theme()` rather than passing a Dear PyGui module. `ThemeSpec`, `ThemeTarget`,
`ThemeColor` and `ThemeStyle` keep renderer constants out of application code. `ThemeSpec.createObject()` / `QTheme` provide QObject ownership for materialized theme lifetime so consuming applications do not manually delete renderer theme ids.

`DearUIQt.backends` is reserved for low-level drawing/plot/native escape hatches while
those surfaces are progressively wrapped. Retained drawing now starts at `QCanvas` +
`QPainter`; retained history/XY plotting starts at `QPlotWidget` + `QPlotAxis` + `QLineSeries`; application renderers should migrate shape creation there instead of calling
backend `draw_*` functions directly. Pointer, modifier-key, clipboard, text-measurement and viewport
queries belong to `QCursor`, `QKeyboard`, `QClipboard`, `QFontMetrics` and `QScreen`; `QCursor.buttons()` also exposes mouse-button state to standalone/floating hosts without requiring a QApplication. Application
startup/shutdown/render-loop ownership plus viewport configuration/size changes belong to `QGuiRuntime`. Application-wide fonts are installed with `QGuiRuntime.setApplicationFont()` and QObject-owned `QFontDatabase` resources rather than renderer font registries. Deferred retained synchronization uses `invokeAfterFrames()` / `invokeNextFrame()` rather than application-owned frame callbacks. Modeless transient surfaces use `QPopupPanel` / `QModelessMenu`; item/global legacy renderer handlers migrate through `QItemInputBinding` / `QGlobalInputBinding` so application modules do not own native handler registries. Popup/menu and viewport
styling share semantic factories (`menu_surface_theme`, `menu_button_theme`,
`menu_image_button_theme`, `viewport_surface_theme`, `compact_layout_surface_theme`,
`floating_window_theme`) so consumers do not duplicate renderer constants or native theme
construction. Direct `dearpygui` imports are intentionally kept out of consumers so backend
selection and testing remain centralized.

## Dialog and convenience-widget policy

`QDialog` follows Qt result semantics (`Accepted` / `Rejected`, `done()`,
`result()`, `open()` and `exec()`).  The older `QtDialog` class remains a
compatibility form base for applications that historically used `accept()` to
run validation/default actions rather than finish the dialog. Its retained body is exposed
through `contentWidget()` so subclasses can configure/layout the body through QWidget APIs
instead of reaching for the native renderer tag. Generic value/item/visibility operations are available through
`control_value()`, `set_control_value()`, `set_control_items()` and `set_control_visible()`; wrappers are preferred
when present and legacy native tags remain a compatibility fallback.

`QComboBox`, `QListWidget`/`QListWidgetItem` and
`QTreeWidget`/`QTreeWidgetItem` are QObject-owned public convenience widgets.
The tree/list convenience views retain item ownership, Qt item-data roles and
selection state while renderer-specific row hit targets stay inside
`DearUIQt.modelview`. `QAbstractItemDelegate` and `QStyledItemDelegate` provide
the public extension point for richer model/view presentation.

`QStandardItem/QStandardItemModel` provide the QtGui item-owned model for list/table/tree data, while `QModelIndex` and abstract models remain in `core`. `QTableView` supports delegate-driven persistent editors and in-place `dataChanged` refreshes so editing does not rebuild native rows.

Item views own retained focus and pointer routing through `QGlobalInputBinding` rather than application-owned renderer registries. `QtListView` exposes reusable `itemGeometry()`, `keyAt()` and `indexAt()` hit-testing, while `QAbstractItemView` provides horizontal/vertical scroll values and `scrollBy()`. Filesystem/explorer surfaces should consume these APIs instead of duplicating renderer rectangle and scroll queries. Application-wide Fusion styling can be installed through `fusion_desktop_theme()` and `QGuiRuntime.setApplicationTheme()` without exposing renderer theme constants.

`QListWidget.setItemWidget()` supports transient row editors such as inline
`QLineEdit` rename controls without forcing consuming applications to rebuild
native Selectables. `QInlineEditPanel` provides the reusable top-level variant
for Explorer-style rename overlays, including text measurement, source-item
occlusion, pointer protection and owned theme lifetime. Applications should not
reimplement those renderer details around an ad-hoc input window.

`QMenu` is the canonical retained popup renderer. It owns physical popup input
shielding, nested popup hit-testing, viewport clamping, checkable/action state,
keyboard navigation and a dedicated accelerator/shortcut column. Application
features should provide declarative action specs instead of maintaining a second
popup renderer.

`QTableWidget` accepts renderer-neutral sizing policies such as
`QTableWidget.FixedFit`; worksheet/editor styling belongs in declarative theme
factories such as `worksheet_theme_spec()` rather than renderer constants in the
consumer.

## Retained native and resource migration boundary

Specialized high-throughput renderers sometimes retain native item ids while their
application logic is migrated incrementally. `QRetainedItem` is the canonical
non-owning facade for those existing ids: geometry, visibility, hover/active state,
focus discovery, values, parent/type inspection, scroll state, theme/font binding and
configuration stay behind DearUIQt instead of leaking backend calls into consumers.
It does **not** take native ownership unless explicitly requested. During hierarchy
migration it also provides `reparent()`, `setLabel()` and `setTexture()` so existing
retained items can move between Qt-style hosts without application-side renderer calls.
Transitional inspection of renderer-owned surfaces stays behind `nativeState()`,
`nativeConfiguration()` and `childItems()`; retained visibility re-synchronizes with the native item before Qt-style
show/hide transitions so legacy mutations cannot be coalesced incorrectly.

Renderer resources follow QObject ownership as well. `QFontDatabase`/`QFont`,
`QTextureRegistry`/`QTexture`, `QPaintLayer`, `QViewportCanvas` and `QToolTip` own native resource
lifetime and expose stable ids only as a compatibility bridge. Application code
should pass these objects directly to QWidget/QPainter APIs wherever supported and
should not create/delete font registries, texture registries, draw layers or tooltip
containers itself. `QTextureRegistry.loadFile()` is the canonical image-file-to-texture
path for toolbar/icon consumers. Frame-level button/key queries belong to `QCursor` and
`QKeyboard`, not direct renderer polling.

Historical `ImGuiComboBox` / `QtComboBox` remain compatibility leaves for code
that depends on the older editable-combo implementation details.

## Interoperability boundary

Consumers that must coexist with another desktop toolkit should use public adapters from
`DearUIQt.interop` rather than importing renderer-specific helpers from `DearUIQt.backends`.
For example, Tk/ttk scroller integration is exposed as `QNativeScrollerMetrics`,
`configure_ttk_scroller_styles()` and `make_ttk_scroller()`. This keeps backend ownership
inside DearUIQt while allowing transitional multi-toolkit applications to migrate incrementally.
`StandaloneUiHost` follows the same rule: its backend argument is optional and production
hosts resolve the active renderer internally, while explicit injection remains available for tests.
