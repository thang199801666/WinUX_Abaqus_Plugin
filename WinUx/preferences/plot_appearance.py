"""Remember the last series color theme for newly opened plot panels."""
from .storage import JsonPreferenceStore
from ..services.plot_palettes import normalize_plot_theme


class PlotAppearancePreferences:
    def __init__(self, root=None):
        self._store = JsonPreferenceStore('plot_appearance.json', root=root)

    def load_palette(self):
        settings = self._store.load()
        return normalize_plot_theme(settings.get('palette') if isinstance(settings, dict) else None)

    def save_palette(self, palette):
        palette = normalize_plot_theme(palette)
        self._store.save({'palette': palette})
        return palette
