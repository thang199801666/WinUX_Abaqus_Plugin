"""Dependency contracts for reusable UI-framework surfaces.

The contracts in this module are intentionally toolkit-light.  Application code
can provide project-specific resources without the reusable controls importing
an application package or resource registry directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Callable, TypeAlias


TextureLoader: TypeAlias = Callable[[str, int], object | None]
IconPathResolver: TypeAlias = Callable[[str], str | PathLike[str]]


@dataclass(frozen=True)
class RibbonResources:
    """Optional resource providers used by :class:`RibbonBar`.

    ``texture_loader`` resolves a named icon to a Dear PyGui texture tag.
    ``icon_path_resolver`` resolves a named icon to an image path when a large
    ribbon tile needs to compose icon and caption into one texture.

    Both dependencies are optional so a ribbon can also be created with raw
    Dear PyGui/image identifiers in small standalone applications.
    """

    texture_loader: TextureLoader | None = None
    icon_path_resolver: IconPathResolver | None = None

    def merged(
        self,
        *,
        texture_loader: TextureLoader | None = None,
        icon_path_resolver: IconPathResolver | None = None,
    ) -> "RibbonResources":
        """Return a copy with explicit providers taking precedence."""
        return RibbonResources(
            texture_loader=(
                self.texture_loader if texture_loader is None else texture_loader
            ),
            icon_path_resolver=(
                self.icon_path_resolver
                if icon_path_resolver is None
                else icon_path_resolver
            ),
        )


__all__ = ["TextureLoader", "IconPathResolver", "RibbonResources"]
