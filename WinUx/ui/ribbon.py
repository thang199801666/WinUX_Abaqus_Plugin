"""WinUx resource adapter for the reusable UI-framework ribbon."""
from .components.toolbar import ResourceTextures
from ..resources import icon_path
from DearUIQt.ribbon import RibbonBar as FrameworkRibbonBar


class RibbonBar(FrameworkRibbonBar):
    """Ribbon preconfigured with WinUx icon/resource loaders."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("texture_loader", ResourceTextures.get)
        kwargs.setdefault("icon_path_resolver", icon_path)
        super().__init__(*args, **kwargs)


__all__ = ["RibbonBar"]
