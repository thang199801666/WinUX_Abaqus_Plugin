# Dear ImGui Qt-style widget layer

The wrapper layer uses Dear PyGui/Dear ImGui controls only. Qt names describe
visual/behavioral contracts; they do not introduce PyQt/PySide/Tk into WinUx.
New code should prefer the explicit `ImGui*` names while the `Q*` names remain
compatibility aliases. Server Notepad is intentionally outside this layer and
remains the one approved ttk-based exception.
It can be imported without loading native Dear PyGui; construction loads the
backend lazily. Tests inject a fake backend.

```python
from WinUx.widgets import QVBoxLayout, QLabel, QPushButton

layout = QVBoxLayout(parent=dialog.content, after=view.after)
status = QLabel("Ready", parent=layout)
button = QPushButton("Refresh", parent=layout)
button.clicked.connect(refresh)
status.setText("Loading...")
```

Construct and delete widgets on the UI thread. Setters from workers require
`after=view.after`; only the newest pending value for each property is delivered.
Identical values skip native writes. A newer direct UI setter invalidates an
older queued worker setter. Children inherit the backend and scheduler from their
wrapper parent. Signals execute synchronously by default. For UI delivery, use
`signal.connect(receiver.method, queued=True)` with a QObject receiver configured
with `after=view.after`. Queued signals preserve every event; display setters
coalesce intermediate values. Disconnecting a connection or deleting its receiver
invalidates already queued events. `connect` returns a SignalConnection handle.

Bound QObject receivers are detected automatically and disconnected on disposal.
Other callables can specify `receiver=object` explicitly. Parent ownership disposes
children and disconnects signals. `setParent` changes ownership, validates cycles
and does not move native controls. A native parent ID provides visual containment;
QObject ownership requires a wrapper parent or `dialog.own_widget(widget)`.
`with QSignalBlocker(editor): editor.setText(value)` updates the native value while
suppressing change signals and restores the previous state, including nested use.

Available canonical controls are `ImGuiLabel`, `ImGuiPushButton`, `ImGuiLineEdit`,
`ImGuiProgressBar`, `ImGuiCheckBox`, `ImGuiRadioButtonGroup`, and the ImGui item
views/layout aliases.  The radio wrapper intentionally retains Dear PyGui's
native grouped radio primitive and adds current-text/index/activation signals;
it does not paint custom radio hit targets.
`QLabel/QPushButton/QLineEdit/...` resolve to the same Dear ImGui implementation.
The base wrapper now provides QWidget-like retained properties such as
`setEnabled/isEnabled`, `setVisible/isVisible`, `setObjectName`, dynamic
`setProperty/property`, fixed size, tooltip and focus helpers. Progress values are
normalized to 0..1. Box layouts use native Dear ImGui flow, not Qt's constraint
solver.

The shared `imgui_qt_style.py` foundation owns Qt/Fusion-like palette roles,
metrics and state themes for line edits, buttons, checkboxes and progress bars.
Single-line dialog editors are direct `mvInputText` items rather than framed
child-window composites so Dear ImGui exclusively owns caret activation, text
selection and insertion position.

QtDialog's shared action/button-box path uses owned QPushButton objects while
preserving the public native button IDs and existing themes. ProgressDialog owns
its label and progress wrappers. Its display updates use a latest-value
queue; cancel/fail commands use the ordinary queue so commands are preserved.
Native rendering still requires verification with a compatible Dear PyGui DLL.

QCheckBox provides `setChecked`, `isChecked`, `setText` and the boolean `toggled`
signal. Programmatic changes emit only when the checked value changes;
QSignalBlocker suppresses those signals during synchronization. Worker setters
coalesce display values. Native checkbox and line-edit interaction invalidates
older pending worker values, including interaction that keeps the same value.
Use wrapper setters for display writes; direct backend writes bypass wrapper
state and signal bookkeeping. Getters and construction/deletion require the UI
thread. Login's remember option and Settings' auto-login option own QCheckBox
wrappers while retaining their public native IDs for existing form APIs.

The existing editable QtComboBox uses fixed theme aliases rather than caching
numeric IDs across native context recreation. This avoids a stale theme ID
referring to an unrelated control when Dear PyGui reuses numeric IDs.

QGridLayout uses a native table and owned box containers for cells:

```python
from WinUx.widgets import QGridLayout, QLabel, QLineEdit

grid = QGridLayout(2, column_widths=(120, None), parent=dialog.content, after=view.after)
dialog.own_widget(grid)
QLabel("Name", parent=grid.cell(0, 0))
editor = QLineEdit(parent=grid.cell(0, 1))
grid.addWidget(editor, 1, 1)
```

Cells are created lazily, including intervening rows. Repeated cell access
reuses the same container. `addWidget` moves both the native item and QObject
ownership, within one backend/UI thread. Fixed column widths are positive finite
values; None stretches a column. Grid construction, cell access and placement
require the UI thread. Deleting a grid releases its cell/widget tree. Row/column
spans, constraints and responsive breakpoint policies remain unsupported.
QtDialog's shared labeled-field path now owns grids and labels, preserves the
builder's return value and restores the native container stack on failure.

The isolated native test runner preloads a host-Python build of the same DPG
version before the production vendor path is added. For example, after installing
`dearpygui==2.3.1` and pytest into separate temporary directories:

```powershell
python tools/run_native_tests.py --native-deps "$env:TEMP\winux-native-test-deps" --pytest-deps "$env:TEMP\winux-test-deps"
```

Real native-item tests cover containment, deletion, button callbacks/dimensions,
line-edit blocking, queued progress and late updates. They create contexts without
opening a viewport. This verifies native item behavior, not visible rendering,
frame rate, Abaqus Python compatibility or a live server connection.

## Qt item views

`QtDataGridView` and `QtListView` provide a shared QAbstractItemView-like
selection/current-index contract on top of the current Dear PyGui backend.  They
use stable row keys, separate current/anchor state from selection, support
single/extended selection, Ctrl/Shift keyboard navigation, activation signals,
and the shared Qt/Fusion palette/metrics.

```python
from WinUx.widgets import QtDataGridView, QtGridRow, QtListView

grid = QtDataGridView(
    dialog.content,
    ("Name", "Status", "Elapsed"),
    multiple=True,
    sortable=True,
)
grid.setRows([
    QtGridRow(
        "job-1", ("Model-1", "Running", "00:32"),
        data={"owner": "user"}, background=(205, 244, 213, 255),
    ),
])
grid.setContextMenu(
    [{"label": "Refresh", "action": "refresh"}],
    on_trigger=lambda action, key: run_grid_command(action, key),
)

versions = QtListView(dialog.content, ["abq2026", "abq2025"], visible_rows=6)
versions.currentTextChanged.connect(on_version_changed)
```

`QtTable` in the dialog layer is now a compatibility adapter over
`QtDataGridView`; ODB/Bookmarks/Sync result grids therefore share the reusable
item-view behavior. Settings' Abaqus-version list and Server Folder suggestions
use `QtListView` instead of `dpg.add_listbox`. ExplorerListView remains a
specialized file-system renderer because it owns Shell icons, inline rename,
rubber-band selection, drag/drop and native Explorer hooks, but its
selection/current-index behavior now shares `QtItemViewState` with the generic
views. Job Viewer remains on that specialized renderer until the reusable Qt
context-menu layer reaches icon-rich nested-menu parity.

## Phase 3: tabs, menus and item-view selection

`ImGuiTabWidget` and `ImGuiMenu` provide retained Dear ImGui implementations of the small QTabWidget/QMenu contracts used by WinUx. They do not import Qt or Tk. `ImGuiDataGridView` and `ImGuiListView` share the same Qt/Fusion selection palette: active selections are blue with white text, inactive/disabled rows use the neutral palette, and all selection/current-index behavior remains owned by Dear ImGui.
