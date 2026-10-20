"""WinUX public package API.

Heavy GUI modules are loaded lazily so diagnostics and configuration utilities
can be imported by the launcher without importing Dear PyGui first.
"""

from .bootstrap.vendor import configure_package_vendor


# Preserve the historical helper name for integrations that imported it even
# though vendor discovery now has an explicit bootstrap owner.
def _configure_bundled_vendor():
    return configure_package_vendor()


VENDOR_DIR, _VENDOR_DLL_HANDLES = _configure_bundled_vendor()

__all__ = ["WinUXController", "run"]


def __getattr__(name):
    if name == "WinUXController":
        from .controller import WinUXController
        return WinUXController
    if name == "run":
        from .bootstrap.application import run
        return run
    raise AttributeError("module {!r} has no attribute {!r}".format(
        __name__, name))
