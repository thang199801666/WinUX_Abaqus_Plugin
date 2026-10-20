"""Minimal pytest compatibility layer for the WinUx regression suite.

WinUx tests must run with the Abaqus-bundled interpreter (``abaqus python``),
which does not ship pytest.  This module provides the small pytest surface the
suites actually use — ``raises``/``approx``/``mark``/``fixture``/``MonkeyPatch``
/``skip``/``fail`` — and transparently defers to a genuinely installed pytest
when one is importable outside this package.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path


_THIS_FILE = os.path.abspath(__file__)


def _load_real_pytest():
    """Bind a genuinely installed pytest when one exists outside WinUx."""
    try:
        from importlib.machinery import PathFinder

        excluded = os.path.dirname(_THIS_FILE).lower()
        paths = [entry for entry in sys.path
                 if entry and os.path.abspath(entry).lower() != excluded]
        spec = PathFinder.find_spec("pytest", paths)
    except Exception:
        return None
    if spec is None or spec.origin == _THIS_FILE or spec.loader is None:
        return None
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None
    sys.modules["pytest"] = module
    return module


_real = _load_real_pytest()
if _real is not None:
    for _name, _value in vars(_real).items():
        if not _name.startswith("__"):
            globals()[_name] = _value
else:
    __version__ = "winux-lite-1.0"

    class _Skipped(Exception):
        def __init__(self, reason=""):
            super().__init__(reason)

    class _Failed(Exception):
        def __init__(self, reason=""):
            super().__init__(reason)

    class _RaisesContext:
        def __init__(self, expected, match=None):
            self.expected = expected
            self.match = match
            self.value = None
            self.exc_info = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                raise AssertionError(
                    "DID NOT RAISE {}".format(self.expected))
            expected = self.expected
            if isinstance(expected, tuple):
                matched = isinstance(exc, expected)
            else:
                matched = isinstance(exc, expected)
            if not matched:
                # Propagate: the runner reports the unexpected exception.
                return False
            if self.match is not None and re.search(self.match, str(exc)) is None:
                raise AssertionError(
                    "Pattern {!r} not found in {!r}".format(
                        self.match, str(exc)))
            self.value = exc
            try:
                self.exc_info = traceback.format_exception(exc_type, exc, tb)
            except Exception:
                pass
            return True

    def raises(expected, match=None):
        return _RaisesContext(expected, match)

    class approx:
        """Comparisons against floats, tuples, lists or dicts of floats."""

        def __init__(self, expected, rel=1e-6, abs=1e-12):
            self.expected = expected
            self.rel = rel
            self.abs = abs

        def __eq__(self, other):
            return self._compare(self.expected, other)

        def __ne__(self, other):
            return not self.__eq__(other)

        def __repr__(self):  # pragma: no cover - diagnostics only
            return "approx({!r}, rel={}, abs={})".format(
                self.expected, self.rel, self.abs)

        def _compare(self, expected, actual):
            if isinstance(expected, (list, tuple)) and isinstance(
                    actual, (list, tuple)):
                if len(expected) != len(actual):
                    return False
                return all(
                    self._compare(one, another)
                    for one, another in zip(expected, actual))
            if isinstance(expected, dict) and isinstance(actual, dict):
                if set(expected) != set(actual):
                    return False
                return all(
                    self._compare(expected[key], actual[key])
                    for key in expected)
            if isinstance(expected, bool) or isinstance(actual, bool):
                return expected == actual
            if isinstance(expected, (int, float)) and isinstance(
                    actual, (int, float)):
                tolerance = max(
                    self.abs, self.rel * max(abs(float(expected)),
                                             abs(float(actual))))
                return abs(float(expected) - float(actual)) <= tolerance
            return expected == actual

    class _MarkMeta(type):
        """``pytest.mark.<anything>`` without a call is a no-op decorator."""

        def __getattr__(cls, name):
            def passthrough(fn=None, **kwargs):
                if fn is None:
                    def decorate(inner):
                        return inner
                    return decorate
                return fn
            return passthrough

    class mark(metaclass=_MarkMeta):
        @staticmethod
        def parametrize(argnames, argvalues, ids=None):
            def decorator(fn):
                fn.__winux_parametrize__ = (argnames, list(argvalues), ids)
                return fn
            return decorator

        @staticmethod
        def skipif(condition, reason=""):
            def decorator(fn):
                fn.__winux_skipif__ = list(
                    getattr(fn, "__winux_skipif__", [])) + [
                    (bool(condition), reason)]
                return fn
            return decorator

        @staticmethod
        def skip(reason=""):
            def decorator(fn):
                fn.__winux_mark_skip__ = reason
                return fn
            return decorator

    class _FixtureMarker:
        def __call__(self, func=None, **kwargs):
            def apply(fn):
                fn.__winux_fixture__ = kwargs.get("name") or fn.__name__
                return fn
            if callable(func):
                return apply(func)
            return apply

    fixture = _FixtureMarker()

    def skip(reason=""):
        raise _Skipped(reason)

    def fail(reason=""):
        raise _Failed(reason)

    _SENTINEL = object()

    def _resolve(path):
        parts = path.split(".")
        target = sys.modules.get(parts[0])
        if target is None:
            import importlib
            target = importlib.import_module(parts[0])
        for attr in parts[1:]:
            target = getattr(target, attr)
        return target

    class MonkeyPatch:
        """The small monkeypatch surface used by WinUx suites."""

        def __init__(self):
            self._undo = []

        def setattr(self, target, name=None, value=_SENTINEL, raising=True):
            if value is _SENTINEL:
                if name is not None:
                    raise TypeError("setattr(target, value) requires a string")
                path, value = target, name
                target, name = path.rsplit(".", 1)
                target = _resolve(target) if "." in target else target
            else:
                if isinstance(target, str):
                    target = _resolve(target)
            had = hasattr(target, name)
            old = getattr(target, name, _SENTINEL)
            self._undo.append((target, name, had, old))
            setattr(target, name, value)

        def delattr(self, target, name=None, raising=True):
            if isinstance(target, str):
                path, name = target.rsplit(".", 1)
                target = _resolve(path) if "." in path else path
            self._undo.append((target, name, True, getattr(target, name)))
            try:
                delattr(target, name)
            except AttributeError:
                if raising:
                    raise

        def setenv(self, name, value):
            had = name in os.environ
            old = os.environ.get(name)
            self._undo.append(("env", name, had, old))
            os.environ[name] = value

        def delenv(self, name, raising=False):
            had = name in os.environ
            old = os.environ.get(name)
            self._undo.append(("env", name, had, old))
            os.environ.pop(name, None)

        def chdir(self, path):
            old = os.getcwd()
            self._undo.append(("cwd", None, True, old))
            os.chdir(str(path))

        def undo(self):
            while self._undo:
                item = self._undo.pop()
                if item[0] == "env":
                    _kind_kind, name, had, old = item
                    if had:
                        os.environ[name] = old
                    else:
                        os.environ.pop(name, None)
                elif item[0] == "cwd":
                    os.chdir(item[3])
                else:
                    target, name, had, old = item
                    if had:
                        setattr(target, name, old)
                    elif old is not _SENTINEL:
                        try:
                            delattr(target, name)
                        except AttributeError:
                            pass
