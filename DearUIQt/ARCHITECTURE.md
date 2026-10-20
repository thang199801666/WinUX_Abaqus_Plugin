# DearUIQt architecture

DearUIQt is an application-independent GUI library.  WinUx is a consumer, not a dependency.

## Stable public layers

- `core/`: object model, events, signals, geometry, application loop, timers, threads, futures, process and input primitives.
- `gui/`: actions, palette/style policy and QtGui-owned standard item models.
- `widgets/`: concrete visual controls and windows, including retained canvas and plot surfaces.
- `layouts/`: layout managers and splitter widgets.
- `modelview/`: item models and list/table/tree views.
- `backends/`: renderer integrations and native escape hatches.
- `interop.py`: public adapters for coexistence with other desktop toolkits; consuming applications should use this instead of backend implementation helpers.
- `docking/`, `ribbon/`, `dialogs/`: reusable higher-level desktop components.

## Dependency rule

Application → widgets/layouts/modelview/gui → core. Renderer calls enter through `backends`.
Canonical implementation modules must not depend on `DearUIQt.qt`; that package exists only for source compatibility.
DearUIQt must never import WinUx.

## Native multi-window backend (experimental)

`native/dearuiqt_native_windows.h` extends the pinned Dear PyGui renderer with
Win32/D3D11 platform viewports. `backends/native_windows.py` owns that ABI;
`QNativeWindow` and opted-in `QtDialog` instances share one GUI thread, context
and resource registry. No Qt runtime, dialog process or IPC is involved.
Stock backends reject this capability explicitly. See `native/README.md` for
build/test instructions and the remaining WinUx production migration work.

## Compatibility

`DearUIQt.QtCore`, `QtGui`, `QtWidgets`, top-level exports and `DearUIQt.qt` remain supported facades.  New library or application code should import canonical public namespaces.

## Renderer boundary

Host applications must not import Dear PyGui directly. Backend-specific work goes through
`DearUIQt.backends`; common controls, layout, model/view, style and scroll policy stay in
the public Qt-style namespaces. `BackendCapabilities` lets higher layers probe optional
renderer features without importing or naming Dear PyGui.

`QPalette`, `QStyle`, `QProxyStyle`, `QStyleFactory` and `QAbstractScrollArea` are retained
policy objects and remain importable without loading the native renderer.


## Compatibility versus canonical behavior

Canonical Qt-named classes should follow Qt ownership and lifecycle contracts.
Where WinUx predates those contracts, historical names remain compatibility
leaves rather than weakening the new public API.  For example `QDialog` owns
standard result-code semantics while `QtDialog` preserves the legacy form
validation workflow; `QComboBox` is a QWidget while `ImGuiComboBox` remains a
renderer-specific editable-combo compatibility surface.

## Model/view ownership

Convenience item widgets (`QListWidget`, `QTreeWidget`) own their item objects
and translate Qt item roles into renderer rows. Applications must not construct
backend Selectables to emulate list/tree rows. Inline editors are attached via
item-view APIs, and native row/overlay plumbing remains an implementation detail
of `modelview/`.


## Model/view dependency rule

``QModelIndex``, ``QAbstractItemModel``, ``QAbstractTableModel``,
``QAbstractListModel`` and ``QItemSelectionModel`` belong to ``DearUIQt.core``
and must remain backend-neutral.  Views/delegates live in ``DearUIQt.modelview``
and may render through ``DearUIQt.backends``.  Application forms should provide
data through model roles or convenience item widgets instead of constructing
renderer tables/selectables directly.


## Standard item models and editors

`QStandardItem` and `QStandardItemModel` live in `DearUIQt.gui`, matching QtGui.
They depend only on `core` model/index primitives and remain renderer-neutral.
`QTableView`/`QTreeView` consume `QAbstractItemModel` instances; delegate editor
lifecycle stays in `modelview`. Persistent table editors must preserve native
row identity across `dataChanged` updates, while structural model changes may
rebuild rows and close affected editors.

## Table semantics

Application code must distinguish data tables from layout tables. A **data table**
belongs in `modelview/` (`QTableView`, `QTableWidget`, models and delegates). A
**layout-only table** is not a data model and must use `QGridLayout`, `QFormLayout`
or another layout manager. Renderer table primitives remain private implementation
details of those library classes; WinUx should not construct them directly.

`QTableWidget` owns every installed `QTableWidgetItem` and cell widget. Structural
row/column changes must keep logical cell coordinates synchronized, dispose only
contents that leave the table, and detach item ownership when the table itself is
deleted. Applications may therefore rebuild dynamic tables without retaining stale
cell editors or renderer descendants.


## Painting, plotting and runtime boundaries

Application drawing uses `QCanvas`/`QViewportCanvas` with `QPainter`; XY/history plotting uses
`QPlotWidget`, `QPlotAxis` and `QLineSeries`. Renderer plot constants, marker
styles, line themes and fit operations must remain inside DearUIQt. Consumers
may retain `.tag` only as a compatibility bridge while migrating old hosts.

`QGuiRuntime` owns renderer context, viewport creation/configuration, frame
rendering, application-wide font/theme binding, callback queue access, deferred frame scheduling and teardown. Reusable native hosts use `itemSnapshot()` / `itemCount()` / `releaseTopLevelItemsSince()` to audit and release per-lease renderer resources without enumerating backend items in application code. Application
hosts should use `invokeAfterFrames()` / `invokeNextFrame()` instead of owning native
frame callbacks and must not call renderer context/viewport lifecycle functions directly.

`QDockWidget` exposes retained child facades through `contentWidget()` and
`dragHandleWidget()` so dock consumers can query focus/geometry/input state
without reaching into native child tags.

Legacy `QtDialog` forms may still hold native ids, but generic state changes
should use its `control_*` facade. The facade first dispatches to a DearUIQt
widget object and only falls back to the native id for unmigrated controls.

## Transient windows, input bindings and theme resources

Modeless transient surfaces that must not enter the renderer popup stack use
`QPopupPanel` or a higher-level component such as `QModelessMenu`. Applications
must not own native global/item handler registries for those surfaces;
`QGlobalInputBinding` and `QItemInputBinding` translate Qt key/mouse constants
and own registry lifetime behind the backend boundary.

Materialized renderer themes should be QObject-owned through `QTheme` when an
application needs a dedicated, non-cached theme. `ThemeSpec.createObject()` is
the canonical bridge from a renderer-neutral specification to that owned
resource. Widgets and dialogs accept either `QTheme` or a legacy native theme id
during migration, but consuming application code should not manually delete
renderer theme ids.

`QWidget.setThemeProvider(factory)` is a DearUIQt extension for state-aware
control styling. Line editors and push/tool buttons call the factory with
`focused` and `disabled` keyword flags during their existing style refresh;
factories should cache their materialized themes. Setting the provider to `None`
restores the preceding explicit theme or default control styling. Static
`setTheme()` remains supported. Native `QtDialog.combo()` controls accept the
same factory through the optional `theme_provider` argument. This keeps focus
rings and disabled colors working when compound forms share fixed metrics.

`QCursor.buttons()` provides current Qt mouse-button flags even in standalone or
process-hosted dialogs that do not own the main `QApplication`; this keeps
physical-release polling out of application modules without changing their host
model.

## Retained model/view geometry and application styling

`QAbstractItemView` owns focus routing and scroll state behind the backend boundary.
Concrete list views expose item geometry/hit-testing (`itemGeometry`, `keyAt`,
`indexAt`) so filesystem and explorer features do not duplicate native rectangle
queries. Global/item focus, activation, resize, visibility and pointer callbacks
remain owned by `QGlobalInputBinding` / `QItemInputBinding`.

Application-wide retained styling is described with declarative theme specs. A
consumer may install `fusion_desktop_theme()` through
`QGuiRuntime.setApplicationTheme()`; renderer `mvThemeCol_*` / `mvStyleVar_*`
constants must not leak back into application modules.

## Composite editors and popup ownership

Reusable transient editing belongs in DearUIQt, not in application renderer code.
`QInlineEditPanel` is the canonical modeless inline editor for overlays that need
to cover/restore a source item, resize to text and keep pointer protection while
editing. Application modules own rename semantics; DearUIQt owns the retained
window/input/theme mechanics.

`QMenu` is the single canonical popup-menu renderer. Nested submenus, popup-tree
hit testing, screen/viewport clamping, check/checkable state, keyboard navigation
and accelerator-column layout remain inside the widget. Consumers provide action
specifications and react to `triggered`; they must not build parallel popup engines.

Data-table sizing is expressed through `QTableWidget` policies (`FixedFit`,
`FixedSame`, `StretchProportional`, `StretchSame`). Worksheet-specific visual
policy is declared with `worksheet_theme_spec()` so renderer table/editor constants
do not escape into application code.

## Retained-item and renderer-resource ownership

During migration, application features may still receive native ids from specialized
renderers. They must adapt those ids through `QRetainedItem` rather than querying or
configuring the backend directly. The facade is non-owning by default; native deletion
requires explicit ownership. It also provides hierarchy/label/texture mutation for retained
migration plus the transitional native-focus bridge for legacy controls that are not yet
represented by a full QWidget object. Native state/configuration/child traversal required by incremental
migration stays behind `QRetainedItem.nativeState()` / `nativeConfiguration()` / `childItems()`, and retained
visibility is re-synchronized before show/hide writes.

Font atlases, static textures, draw layers and tooltip containers are DearUIQt-owned
resources (`QFontDatabase`/`QFont`, `QTextureRegistry`/`QTexture`, `QPaintLayer`,
`QToolTip`). Their registries and native children follow QObject lifetime. Consumers
may retain `.tag`/`nativeId()` only for compatibility with unmigrated renderer APIs,
but creation/destruction belongs inside DearUIQt. Image files are loaded through
`QTextureRegistry.loadFile()`; application toolbar/resource code must not create texture
registries or poll frame-level mouse/key state through the renderer.


## Viewport overlays

Top-level drag ghosts, dock indicators and other paint-only viewport chrome use
`QViewportCanvas` with `QPainter`. Consuming applications must not allocate native
viewport drawlists directly. Ordinary widget-contained drawing continues to use
`QCanvas`; both surfaces share the same painter and retained-item configuration model.

## Interoperability and backend-import policy

Application packages should not import `DearUIQt.backends` merely to reuse a backend helper.
Cross-toolkit integration belongs behind public adapters in `DearUIQt.interop`; the current
Tk/ttk scroller bridge is the canonical example. Production `StandaloneUiHost` instances
resolve the active backend internally, while constructor injection remains available to tests.
The migration goal is therefore stricter than eliminating direct `dpg.*` calls: application
source should also converge toward zero imports from `DearUIQt.backends`.

## Event-loop teardown and dense table efficiency

QObject tree disposal is an application transaction.  The owning `QApplication`
purges posted events, deferred native mutations, modal/popup ownership, pointer
routing and focus state once for the root subtree before recursive object disposal.
Descendant `delete()` calls must not rescan application queues.  This keeps dialog
and model/view teardown proportional to the object tree instead of multiplying it
by the number of pending events.

`QTableWidgetItem` keeps DisplayRole/EditRole in compact slotted storage and
allocates a sparse role dictionary only for uncommon roles.  Native table items
must also avoid redundant renderer configuration for default state.  These rules
are important for deferred full-population worksheets: every logical row can be
materialized without paying per-cell Python dictionaries or an extra native
`configure_item(enabled=True)` crossing.
