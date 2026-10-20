"""WinUx regression test package.

The suites are executed through ``abaqus python -m unittest tests.<name>``
(via ``tools/run_tests.py``), so ``tests`` is imported as a package.  Several
suites still import their siblings the historic script-friendly way, e.g.
``from ui_sources import implementation_path`` or
``import test_all_floating_dialogs``.  Seeding the package directory into
``sys.path`` restores both conventions under one runner.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
