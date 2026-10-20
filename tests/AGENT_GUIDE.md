# WinUx test-suite normalization — agent guide

Read this fully before touching anything. You are one of several agents fixing
disjoint clusters of failing test modules. Your owned modules are listed in
your task prompt; never touch files owned by other agents.

## How to run tests (the only supported way)

```
abaqus python tools/pytestlite.py tests.<module_name_without_.py>
```

- Plain `python` is FORBIDDEN (PermissionError on test files). Real pytest does
  not exist in this environment. Never batch unrelated GUI suites in one
  process — each pytestlite invocation is already a fresh interpreter.
- To inspect a module's current failures, run it and redirect:

```
abaqus python tools/pytestlite.py tests.test_foo 2>&1 > %TEMP%\opencode\foo.txt
```

then read that file. `reports/failures/<module>.txt` holds the previous run's
output but uses old anonymous names (`FAIL/runTest`); always re-run fresh.
- Success = the summary line is exactly `OK`. Iterate until every owned module
  ends `OK` (skips are fine: `OK (skipped=n)`).

## Environment facts

- Tests run via the root `pytest.py` compatibility shim (compatible subset:
  `raises(match=)`, `approx`, `mark.parametrize/skipif`, plain + yield
  `fixture` with dependency injection, `skip/fail`, `MonkeyPatch`,
  `tmp_path`/`tmp_path_factory` builtins). If a needed pytest API is missing
  or wrong, work around it in the test file itself and REPORT it — do not
  edit `pytest.py`.
- `tests/__init__.py` seeds the tests directory onto `sys.path`, so bare
  sibling imports (`from ui_sources import implementation_path`,
  `import test_all_floating_dialogs`) work under `tests.test_x`.
- `tests/ui_sources.py: implementation_path(path)` maps legacy source paths to
  canonical ones (e.g. `ui/framework/*` → `DearUIQt/*`,
  `DearUIQt/qt/scroller.py` → `DearUIQt/backends/dearpygui_scroller.py`,
  `WinUx/components/*` → `WinUx/ui/components/*`). For ANY test that asserts
  against source text, resolve every path through `implementation_path`; if a
  moved path is not mapped, resolve it inline in the test to the new real
  path (do not edit ui_sources.py — report the needed mapping).
- SOURCE-CONTENT tests (assertIn on file text) are the dominant pattern. The
  product was rebuilt many times; when the contract's intent survives but the
  implementation moved/renamed, re-point the assertion to the current
  implementation and keep/tighten the guarantee whenever possible.
- Version: the product VERSION is now **1.1.4** (file: repo-root `VERSION`).
  Tests pinning `1.1.0` are stale: update them to read the real VERSION
  (preferred: compute the expectation from the root `VERSION` file or the
  product's version lookup) or at minimum pin `1.1.4`.

## Architecture map (for re-pointing assertions)

- GUI toolkit is **DearUIQt** (DearImGui/DearPyGui widgets exposing a Qt-like
  API; root package `DearUIQt/`: `widgets/`, `layouts/`, `dialogs/`,
  `docking/`, `modelview/`, `backends/dearpygui*.py`, `gui.py`, `core/`).
  NO Qt/PySide/PyQt, NO tkinter in primary UI paths.
- Old `WinUx/ui/framework/*` is gone; `WinUx/ui` now holds
  `behaviors/components/hosting/native` subpackages. `WinUx/ui/components/`
  re-homes old `WinUx/components/*`; `WinUx/dialogs/floating_dialog.py` is an
  alias for `WinUx/ui/hosting/floating_dialog.py`; several
  `WinUx/dialogs/<name>.py` are aliases forwarding into
  `WinUx/dialogs/inprocess_adapters.py` / `floating_adapters.py`.
- Dialogs: main-window dialogs are in-process Qt-like dialogs — classes in
  `WinUx/dialogs/inprocess/transient.py` (LoginDialog, JobEditDialog,
  JobManagerDialog...) and `WinUx/dialogs/inprocess/*.py` (SettingsDialog,
  JobScheduleDialog, TransferCenterDialog...), built on form classes in
  `WinUx/dialogs/*_form.py` + shared Qt-style widgets. Explicit
  process-isolated floating hosting lives in
  `WinUx/dialogs/floating_adapters.py` (classes subclass
  `FloatingDialogController` from `WinUx/ui/hosting/floating_dialog.py` or
  `ResultDialog`).
- Context menus are DearUIQt `QMenu` widgets (DearUIQt/widgets/menu.py);
  explorer delegates via thin compatibility shims in
  `WinUx/ui/components/explorer_context_menu.py` (input shield =
  `menu._show_input_shield()`, popup ownership = `QMenu.popup()` grab).
- Shared scroller metrics: `DearUIQt/backends/dearpygui_scroller.py`
  (`SharedScrollerMetrics/Palette`, `DpgScrollerArrowOverlay`, alias
  `QScrollerArrowOverlay` in `DearUIQt/backends/dearpygui.py`).
- Splitter/docking: `DearUIQt/docking/dock_widget.py`, `dock_manager.py`;
  plot panel `WinUx/ui/components/job_plots.py` is fully widget-based
  (`QPlotWidget/QPlotAxis/QLineSeries`, toolbar frame
  `self._toolbar_frame` / `self.toolbar = self._toolbar_frame.tag`).

## Fix policy per failing test

1. **Stale assertion, intent survives** → update the assertion to the current
   implementation (rename symbols, swap file paths via
   `implementation_path`, adjust metrics to what the code actually does —
   read the real code, don't guess numbers).
2. **Genuine product bug** → fix the product minimally, in files that belong
   to your cluster's feature area, following surrounding style. Already known
   and fixed: `WinUx/dialogs/local_folder_form.py` `_browser_key` used an
   undefined `dpg`; use `QGlobalInputBinding.qtKeyForNative(_app_data)`.
   If the needed product file is outside your area, do NOT edit it — report.
3. **Contract superseded and nothing current matches the intent** (only for
   latest-rev suites) → delete just that obsolete test function from the
   module and leave a one-line comment naming the replacing contract
   (e.g. `# superseded by test_dearuiqt_modeless_r87`). Never delete files.
4. If a module hard-crashes the interpreter with NO output at all (native
   viewport suites), do not chase it: note it in your final report and move
   on (the runner has a native-runtime skip list).

## Strict do-not-touch (shared infrastructure)

`tools/run_tests.py`, `tools/pytestlite.py`, `pytest.py`, `tests/__init__.py`,
`tests/__init__.py`-seeded siblings, `tests/ui_sources.py`,
`tests/native_runtime_modules.txt`, `tests/legacy/*`, `tests/AGENT_GUIDE.md`,
and every test module outside your owned list. Product edits: only your
feature area, only real regressions.

## Deliverable (final message)

For each owned module: final status (`OK` / `SKIP-native` / `still-failing + why`)
plus a bullet summary of the most important test updates and any product fixes
(file:line, what and why), and any infrastructure needs (ui_sources mappings,
shim gaps) for the coordinator to apply.
