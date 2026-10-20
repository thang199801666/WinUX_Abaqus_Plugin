"""Application bootstrap and process-lifecycle helpers.

This package is intentionally dependency-light.  GUI modules are imported only
from the lifecycle entry point after diagnostics have been installed.
"""

from .application import run
from .vendor import configure_package_vendor

__all__ = ["configure_package_vendor", "run"]
