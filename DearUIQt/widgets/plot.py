"""Qt-style plotting widgets over the active Dear PyGui/ImPlot backend.

The classes in this module intentionally keep renderer symbols out of consuming
applications.  ``QPlotWidget`` owns the plot surface, ``QPlotAxis`` owns one
axis and ``QLineSeries`` owns retained series data/style.  Native tags remain
available through ``.tag`` for compatibility with older host code, but new code
should use the object API.
"""
from __future__ import annotations

from ..core.object import Qt
from .widget import QWidget


class QPlotAxis(QWidget):
    """One X/Y plot axis with Qt-style ownership and fit semantics."""

    XAxis = "x"
    YAxis = "y"

    def __init__(self, orientation=YAxis, label="", *, parent=None, after=None,
                 backend=None, tag=None):
        if parent is None:
            raise ValueError("QPlotAxis requires a QPlotWidget parent")
        backend, options = self._construction(parent, backend)
        value = str(orientation or self.YAxis).strip().lower()
        if value in ("x", "horizontal", str(Qt.Horizontal)):
            axis = backend.mvXAxis
            self._orientation = self.XAxis
        elif value in ("y", "vertical", str(Qt.Vertical)):
            axis = backend.mvYAxis
            self._orientation = self.YAxis
        else:
            raise ValueError("orientation must be XAxis/YAxis")
        if tag is not None:
            options["tag"] = tag
        native = backend.add_plot_axis(axis, label=str(label or ""), **options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        self._label = str(label or "")

    def orientation(self):
        return self._orientation

    def label(self):
        return self._label

    def setLabel(self, text):
        self._label = str(text or "")
        self._on_ui("label", self._configure, "label", self._label)

    def fitData(self):
        self._require_ui()
        if not self.exists():
            return False
        try:
            self.backend.fit_axis_data(self.tag)
            return True
        except Exception:
            return False


class QLineSeries(QWidget):
    """Retained XY line series parented to a :class:`QPlotAxis`."""

    NoMarker = "none"
    CircleMarker = "circle"

    def __init__(self, x=(), y=(), label="", *, parent=None, after=None,
                 backend=None, tag=None, color=None, width=1.6, marker=None):
        if not isinstance(parent, QPlotAxis):
            raise TypeError("QLineSeries parent must be QPlotAxis")
        backend, options = self._construction(parent, backend)
        if tag is not None:
            options["tag"] = tag
        native = backend.add_line_series(list(x or ()), list(y or ()),
                                         label=str(label or ""), **options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        self._label = str(label or "")
        self._owned_theme = None
        self._line_color = color
        self._line_width = float(width)
        self._marker = marker or self.NoMarker
        if color is not None or width is not None or marker not in (None, self.NoMarker):
            self.setStyle(color=color, width=width, marker=marker)

    def label(self):
        return self._label

    def setLabel(self, text):
        self._label = str(text or "")
        self._on_ui("label", self._configure, "label", self._label)

    def setData(self, x, y):
        values = [list(x or ()), list(y or ())]
        self._on_ui("series-data", self._set_series_data_now, values)

    def _set_series_data_now(self, values):
        if self._deleted or not self.exists():
            return False
        try:
            self.backend.set_value(self.tag, values)
            self._properties["value"] = values
            return True
        except Exception:
            return False

    def data(self):
        self._require_ui()
        try:
            value = self.backend.get_value(self.tag)
        except Exception:
            value = self._properties.get("value", [[], []])
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            return ([], [])
        return (list(value[0] or ()), list(value[1] or ()))

    def setStyle(self, *, color=None, width=None, marker=None):
        """Apply a retained line-series style without exposing ImPlot symbols."""
        self._require_ui()
        if color is not None:
            self._line_color = color
        if width is not None:
            self._line_width = float(width)
        if marker is not None:
            self._marker = marker
        backend = self.backend
        old_theme = self._owned_theme
        try:
            with backend.theme() as theme:
                with backend.theme_component(backend.mvLineSeries):
                    if self._line_color is not None:
                        backend.add_theme_color(
                            backend.mvPlotCol_Line, self._line_color,
                            category=backend.mvThemeCat_Plots)
                    backend.add_theme_style(
                        backend.mvPlotStyleVar_LineWeight, float(self._line_width),
                        category=backend.mvThemeCat_Plots)
                    marker_value = self._marker
                    if marker_value not in (None, self.NoMarker, False):
                        marker_map = {
                            self.CircleMarker: getattr(backend, "mvPlotMarker_Circle", None),
                        }
                        native_marker = marker_map.get(str(marker_value).lower(), marker_value)
                        if native_marker is not None:
                            backend.add_theme_style(
                                backend.mvPlotStyleVar_Marker, native_marker,
                                category=backend.mvThemeCat_Plots)
            backend.bind_item_theme(self.tag, theme)
            self._owned_theme = theme
            if old_theme is not None and old_theme != theme:
                try:
                    if backend.does_item_exist(old_theme):
                        backend.delete_item(old_theme)
                except Exception:
                    pass
            return theme
        except Exception:
            return None

    def delete(self):
        if self._deleted:
            return
        theme = self._owned_theme
        self._owned_theme = None
        super().delete()
        if theme is not None:
            try:
                if self.backend.does_item_exist(theme):
                    self.backend.delete_item(theme)
            except Exception:
                pass


class QPlotWidget(QWidget):
    """Retained plot surface with axis/series helpers.

    The surface intentionally models the small plotting subset WinUx needs.
    Additional plot types can be layered behind the same API without leaking
    Dear PyGui/ImPlot constants back into applications.
    """

    NorthWest = "northwest"
    NorthEast = "northeast"
    SouthWest = "southwest"
    SouthEast = "southeast"

    def __init__(self, title="", *, parent=None, after=None, backend=None,
                 width=-1, height=-1, tag=None, show=True, mouse_position=True,
                 crosshairs=False, query=False, **kwargs):
        backend, options = self._construction(parent, backend)
        options.update(dict(
            label=str(title or ""), width=int(width), height=int(height),
            no_mouse_pos=not bool(mouse_position), crosshairs=bool(crosshairs),
            query=bool(query),
        ))
        if tag is not None:
            options["tag"] = tag
        if show is not True:
            options["show"] = bool(show)
        options.update(kwargs)
        native = backend.add_plot(**options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        self._title = str(title or "")
        self._legend = None
        self._axes = []
        self._owned_theme = None
        if show is not True:
            self._prime_visibility_state(show)

    def title(self):
        return self._title

    def setTitle(self, text):
        self._title = str(text or "")
        self._on_ui("label", self._configure, "label", self._title)

    def addLegend(self, *, location=NorthWest, horizontal=False, outside=False):
        self._require_ui()
        mapping = {
            self.NorthWest: getattr(self.backend, "mvPlot_Location_NorthWest", None),
            self.NorthEast: getattr(self.backend, "mvPlot_Location_NorthEast", None),
            self.SouthWest: getattr(self.backend, "mvPlot_Location_SouthWest", None),
            self.SouthEast: getattr(self.backend, "mvPlot_Location_SouthEast", None),
        }
        native_location = mapping.get(str(location or self.NorthWest).lower(), location)
        kwargs = dict(parent=self.tag, horizontal=bool(horizontal), outside=bool(outside))
        if native_location is not None:
            kwargs["location"] = native_location
        self._legend = self.backend.add_plot_legend(**kwargs)
        return self._legend

    def addAxis(self, orientation, label=""):
        axis = QPlotAxis(orientation, label, parent=self, after=self._after,
                         backend=self.backend)
        self._axes.append(axis)
        return axis

    def axes(self):
        self._axes[:] = [axis for axis in self._axes if not axis._deleted]
        return tuple(self._axes)

    def addLineSeries(self, x, y, *, axis=None, label="", color=None,
                      width=1.6, marker=None):
        if axis is None:
            axes = [value for value in self.axes() if value.orientation() == QPlotAxis.YAxis]
            if not axes:
                axis = self.addAxis(QPlotAxis.YAxis)
            else:
                axis = axes[0]
        if not isinstance(axis, QPlotAxis):
            raise TypeError("axis must be QPlotAxis")
        return QLineSeries(x, y, label, parent=axis, after=self._after,
                           backend=self.backend, color=color, width=width,
                           marker=marker)

    def applyFusionTheme(self):
        """Apply DearUIQt's light Fusion plot palette and return the theme id."""
        self._require_ui()
        from ..themes import plot_surface_theme
        theme = plot_surface_theme(backend=self.backend)
        self.setTheme(theme)
        self._owned_theme = theme
        return theme

    def focusPlot(self):
        return self.setFocus()


__all__ = ["QPlotWidget", "QPlotAxis", "QLineSeries"]
