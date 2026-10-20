"""Small host contracts used by Plot Digitizer application/UI layers."""
from __future__ import annotations

from typing import Protocol, Any


class ReferenceSink(Protocol):
    """Host capability for publishing one digitized dataset."""

    @property
    def available(self) -> bool: ...

    def add_dataset(self, dataset: Any) -> dict: ...
