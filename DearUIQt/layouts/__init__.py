"""Layout managers and splitter primitives."""
from .._lazy import resolve, namespace_dir
_EXPORTS = {
    "QBoxLayout": ".box", "QHBoxLayout": ".box", "QVBoxLayout": ".box",
    "QGridLayout": ".box", "QFormLayout": ".box", "QLayoutItem": ".box",
    "QSpacerItem": ".spacer",
    "QSplitter": ".splitter", "QSplitterHandle": ".splitter",
    "SplitterAxis": "..splitter", "SplitterController": "..splitter",
    "SplitterPolicy": "..splitter", "SplitterSizes": "..splitter",
    "SplitterState": "..splitter", "clamp_ratio": "..splitter",
    "split_extent": "..splitter",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
