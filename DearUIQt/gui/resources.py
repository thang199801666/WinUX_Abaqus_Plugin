"""Owned renderer resources exposed through Qt-style DearUIQt objects."""
from __future__ import annotations

from pathlib import Path

from ..backends import get_backend
from ..core.object import QObject


class _NativeResource(QObject):
    def __init__(self, native_id, *, parent=None, backend=None, deleter=None):
        super().__init__(parent=parent)
        self.backend = backend or get_backend()
        self._native_id = native_id
        self._deleter = deleter

    def nativeId(self):
        return self._native_id

    @property
    def tag(self):
        return self._native_id

    def exists(self):
        if self._native_id is None:
            return False
        checker = getattr(self.backend, "does_item_exist", None)
        if not callable(checker):
            return True
        try:
            return bool(checker(self._native_id))
        except Exception:
            return False

    def delete(self):
        if self._deleted:
            return
        native = self._native_id
        self._native_id = None
        if native is not None:
            try:
                if self._deleter is not None:
                    self._deleter(native)
                elif self.backend.does_item_exist(native):
                    self.backend.delete_item(native)
            except Exception:
                pass
        super().delete()


class QFont(_NativeResource):
    """Owned application font resource."""
    def __init__(self, native_id, path="", pixel_size=0, **kwargs):
        super().__init__(native_id, **kwargs)
        self.path = str(path or "")
        self.pixel_size = float(pixel_size or 0)


class QFontDatabase(QObject):
    """Small application-font registry hiding renderer font-atlas details."""
    def __init__(self, *, parent=None, backend=None):
        super().__init__(parent=parent)
        self.backend = backend or get_backend()
        cm = self.backend.font_registry()
        self._registry = cm.__enter__()
        cm.__exit__(None, None, None)
        self._fonts = []

    def addApplicationFont(self, path, pixel_size):
        path = str(Path(path))
        if not Path(path).is_file():
            return None
        try:
            native = self.backend.add_font(path, float(pixel_size), parent=self._registry)
        except TypeError:
            # Older/fake backends may rely on the active container stack.
            cm = self.backend.font_registry()
            registry = cm.__enter__()
            try:
                native = self.backend.add_font(path, float(pixel_size))
            finally:
                cm.__exit__(None, None, None)
            if self._registry is None:
                self._registry = registry
        font = QFont(native, path, pixel_size, parent=self, backend=self.backend)
        self._fonts.append(font)
        return font

    def delete(self):
        if self._deleted:
            return
        registry = self._registry
        self._registry = None
        super().delete()
        if registry is not None:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass


class QTexture(_NativeResource):
    """Owned immutable texture resource."""
    pass


class QTextureRegistry(QObject):
    """Own a native texture registry and all QTexture children."""
    def __init__(self, *, parent=None, backend=None, visible=False):
        super().__init__(parent=parent)
        self.backend = backend or get_backend()
        cm = self.backend.texture_registry(show=bool(visible))
        self._registry = cm.__enter__()
        cm.__exit__(None, None, None)

    def nativeId(self):
        return self._registry

    @property
    def tag(self):
        return self._registry

    def loadFile(self, path, *, tag=None):
        """Load an image file and return an owned :class:`QTexture`.

        Image decoding remains a backend capability, while registry/lifetime
        ownership stays inside DearUIQt.  Applications therefore never need
        renderer ``load_image`` or texture-registry primitives.
        """
        loader = getattr(self.backend, "load_image", None)
        if not callable(loader):
            return None
        try:
            width, height, _channels, data = loader(str(path))
        except Exception:
            return None
        return self.addStaticTexture(width, height, data, tag=tag)

    def addStaticTexture(self, width, height, data, *, tag=None):
        kwargs = {"parent": self._registry}
        if tag is not None:
            kwargs["tag"] = tag
        try:
            native = self.backend.add_static_texture(
                int(width), int(height), data, **kwargs)
        except TypeError:
            kwargs.pop("parent", None)
            native = self.backend.add_static_texture(
                int(width), int(height), data, **kwargs)
        return QTexture(native, parent=self, backend=self.backend)

    def delete(self):
        if self._deleted:
            return
        registry = self._registry
        self._registry = None
        super().delete()
        if registry is not None:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass


__all__ = ["QFont", "QFontDatabase", "QTexture", "QTextureRegistry"]
