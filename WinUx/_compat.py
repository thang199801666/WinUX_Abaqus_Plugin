"""Import compatibility without duplicate classes, registries or native state."""
import importlib
import sys


def alias_module(name, target):
    module = importlib.import_module(target)
    sys.modules[name] = module
    return module


def package_exports(namespace, target):
    module = importlib.import_module(target)
    namespace["__all__"] = module.__all__
    namespace["__getattr__"] = lambda name: getattr(module, name)
    namespace["__dir__"] = lambda: sorted(set(namespace) | set(dir(module)))
