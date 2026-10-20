"""Run one WinUx test module under a single, pytest-style-aware collector.

WinUx suites mix two idioms:

* classic ``unittest.TestCase`` classes, and
* pytest-style bare ``test_*`` functions (optionally ``@pytest.mark
  .parametrize``-driven, built on module-level ``@pytest.fixture`` providers).

The Abaqus-bundled interpreter cannot run pytest, and plain unittest collects
zero tests from bare pytest-style functions, which silently reported suites
empty.  This entry point collects both idioms into one BulkTestSuite and
prints the classic unittest result block so the outer runner
(``tools/run_tests.py``) can parse it:

    Ran N tests in 0.02s

    OK  ... or ...  FAILED (failures=n, errors=m, skipped=k)

Usage:

    abaqus python tools/pytestlite.py tests.test_the_module
"""
from __future__ import annotations

import importlib
import inspect
import sys
import tempfile
import traceback
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import WinUx  # noqa: E402  (configures the bundled vendor + native runtime paths)

import pytest  # noqa: E402  (root compatibility layer; re-exports real pytest when present)

import os  # noqa: E402

if os.environ.get("WINUX_ALLOW_MODALS") != "1" and os.name == "nt":
    # Regression tests must never surface a modal Win32 dialog (MessageBoxW
    # inside update flows used to block the suite until the runner timeout).
    os.environ["WINUX_HEADLESS"] = "1"


def _long_path(path):
    """Return the Win32 long-path form of *path* when it is a short path."""
    import ctypes
    path = str(path)
    try:
        buf = ctypes.create_unicode_buffer(320)
        result = ctypes.windll.kernel32.GetLongPathNameW(path, buf, len(buf))
        if result and result < len(buf) and buf.value:
            return buf.value
    except Exception:
        pass
    return path


_LONG_TEMP = _long_path(tempfile.gettempdir())


class TestFunctionError(Exception):
    pass


def _expand_function(fn, module, counter):
    """Return one TestCase per concrete parameter combination."""
    skip_conditions = list(getattr(fn, "__winux_skipif__", []))
    parametrize = getattr(fn, "__winux_parametrize__", None)
    combinations = []
    if parametrize is None:
        combinations.append({})
    else:
        argnames, argvalues, _ids = parametrize
        if isinstance(argnames, str):
            argnames = [name.strip() for name in argnames.split(",")]
        else:
            argnames = [str(name) for name in argnames]
        for raw in argvalues:
            if len(argnames) == 1:
                combinations.append({argnames[0]: raw})
                continue
            if isinstance(raw, dict):
                combinations.append(dict(raw))
                continue
            if not isinstance(raw, (tuple, list)):
                raise TestFunctionError(
                    "parametrize values for {!r} must be tuples when more "
                    "than one name is given (got {!r})".format(
                        fn.__name__, raw))
            if len(raw) != len(argnames):
                raise TestFunctionError(
                    "parametrize arity mismatch for {!r}: {} names, "
                    "value {!r}".format(fn.__name__, len(argnames), raw))
            combinations.append(dict(zip(argnames, raw)))

    signature = inspect.signature(fn)
    dependencies = [name for name in signature.parameters
                    if name not in ("self",)]
    cases = []
    for index, mapping in enumerate(combinations, 1):
        counter[0] += 1
        cls_name = "PyFunc_{}_{}".format(fn.__name__, counter[0])
        test_name = fn.__name__ if fn.__name__.startswith("test") else "test_{}".format(fn.__name__)
        attrs = {
            "_fn": staticmethod(fn),
            "_fn_module": module,
            "_mapping": mapping,
            "_skip_conditions": skip_conditions,
            "_dependencies": [
                name for name in dependencies if name not in mapping],
            test_name: _make_run_test(fn, module),
            "__doc__": fn.__doc__ or "",
        }
        cls = type(cls_name, (_PyFunctionCase,), attrs)
        cls.__name__ = cls_name
        case = cls(test_name)
        if len(combinations) > 1:
            case._description = "{}[{}]".format(fn.__name__, index)
        cases.append(case)
    return cases


class _PyFunctionCase(unittest.TestCase):
    """Executes one pytest-style test with fixture resolution."""

    _fn = None
    _fn_module = None
    _mapping = None
    _dependencies = None
    _description = None

    def shortDescription(self):
        return self._description


def _make_run_test(fn, module):
    def run_test(self):
        for condition, reason in self._skip_conditions:
            if condition:
                self.skipTest(reason)
        if getattr(fn, "__winux_mark_skip__", None):
            self.skipTest(fn.__winux_mark_skip__)
        values = dict(self._mapping or {})
        teardowns = []
        module_fixtures = _module_fixtures(module)
        try:
            for name in self._dependencies:
                resolved = _resolve_fixture(
                    name, values, module_fixtures, teardowns, set())
                if resolved is _MISSING:
                    raise TestFunctionError(
                        "no fixture named {!r}".format(name))
                values[name] = resolved
            self._fn(**values)
        except pytest._Skipped as exc:
            self.skipTest(str(exc) or "skipped")
        except pytest._Failed as exc:
            self.fail(str(exc))
        finally:
            for teardown in reversed(teardowns):
                try:
                    teardown()
                except StopIteration:
                    pass
                except Exception:
                    pass
    return run_test


def _module_fixtures(module):
    fixtures = {}
    for name in dir(module):
        obj = getattr(module, name, None)
        fixture_name = getattr(obj, "__winux_fixture__", None)
        if callable(obj) and fixture_name:
            fixtures[fixture_name] = obj
    return fixtures


_builtin_fixtures = {}

_MISSING = object()


def _builtin(name):
    def provide():
        if name == "monkeypatch":
            return pytest.MonkeyPatch()
        if name == "tmp_path":
            return Path(tempfile.mkdtemp(prefix="pytestlite-tmp-", dir=_LONG_TEMP or None))
        if name == "tmp_path_factory":
            return _TmpPathFactory()
        raise TestFunctionError(
            "unsupported builtin fixture {!r}".format(name))
    return provide


class _TmpPathFactory:
    def mktemp(self, basename="pytest", numbered=True):
        prefix = "{}-".format(basename)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=_LONG_TEMP or None))

    def getbasetemp(self):
        return Path(tempfile.gettempdir())


def _resolve_fixture(name, values, module_fixtures, teardowns, active):
    if name in values:
        return values[name]
    if name in active:
        raise TestFunctionError("circular fixture dependency: {}".format(name))
    active.add(name)
    try:
        if name in module_fixtures:
            provider = module_fixtures[name]
        elif name == "monkeypatch":
            provider = _builtin(name)
        elif name == "tmp_path":
            provider = _builtin(name)
        elif name == "tmp_path_factory":
            provider = _builtin(name)
        else:
            return _MISSING
        signature = inspect.signature(provider)
        kwargs = {}
        for pname, param in signature.parameters.items():
            if pname in values:
                kwargs[pname] = values[pname]
                continue
            resolved = _resolve_fixture(
                pname, values, module_fixtures, teardowns, active)
            if resolved is _MISSING:
                if param.default is not param.empty:
                    continue
                raise TestFunctionError("no fixture named {!r}".format(pname))
            kwargs[pname] = resolved
        result = provider(**kwargs)
        if inspect.isgenerator(result):
            value = next(result)

            def teardown():
                try:
                    next(result)
                except StopIteration:
                    pass
            teardowns.append(teardown)
        else:
            value = result
        values[name] = value
        return value
    finally:
        active.discard(name)


def main(argv):
    if len(argv) < 2:
        print("usage: pytestlite.py tests.<module>")
        return 2
    module_name = argv[1]
    try:
        module = importlib.import_module(module_name)
    except BaseException as exc:
        print("ERROR: import_test_module ({})".format(module_name))
        print("-" * 70)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        print("----------------------------------------------------------------------")
        if hasattr(exc, "load_error"):
            print(repr(exc))
        print("Ran 1 test in 0.0s")
        print("FAILED (errors=1)")
        sys.stdout.flush()
        return 1

    loader = unittest.defaultTestLoader
    unit_suite = loader.loadTestsFromModule(module)
    import_errors = []
    for error in getattr(loader, "errors", []):
        import_errors.append(error)

    counter = [0]
    pytest_cases = []
    collection_errors = []
    for name in dir(module):
        obj = getattr(module, name, None)
        if obj is None or not callable(obj):
            continue
        if getattr(obj, "__name__", None) != name:
            continue
        if isinstance(obj, type):
            continue
        if not name.startswith("test"):
            continue
        if inspect.iscoroutinefunction(obj):
            continue
        try:
            for case in _expand_function(obj, module, counter):
                pytest_cases.append(case)
        except TestFunctionError as exc:
            collection_errors.append((name, exc))

    suite = unittest.TestSuite()
    suite.addTests(unit_suite)
    suite.addTests(unittest.TestSuite(pytest_cases))

    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    for name, exc in collection_errors:
        print("ERROR: collect_{} ({})".format(name, module_name))
        print("-" * 70)
        print("{}: {}".format(type(exc).__name__, exc))
    sys.stdout.flush()
    if result.wasSuccessful() and not collection_errors:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
