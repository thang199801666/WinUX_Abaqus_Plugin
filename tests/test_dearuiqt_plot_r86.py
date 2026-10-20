from contextlib import contextmanager

from DearUIQt.widgets import QLineSeries, QPlotAxis, QPlotWidget


class FakeBackend:
    mvXAxis = 1
    mvYAxis = 2
    mvLineSeries = 3
    mvPlotCol_Line = 4
    mvPlotStyleVar_LineWeight = 5
    mvPlotStyleVar_Marker = 6
    mvPlotMarker_Circle = 7
    mvThemeCat_Plots = 8
    mvPlot_Location_NorthWest = 9
    mvPlot_Location_NorthEast = 10
    mvPlot_Location_SouthWest = 11
    mvPlot_Location_SouthEast = 12

    def __init__(self):
        self.next = 100
        self.config = {}
        self.values = {}
        self.calls = []

    def _new(self, kind, **kwargs):
        tag = kwargs.pop("tag", None) or self.next
        self.next += 1
        self.config[tag] = dict(kwargs)
        self.calls.append((kind, tag, dict(kwargs)))
        return tag

    def add_plot(self, **kwargs):
        return self._new("plot", **kwargs)

    def add_plot_legend(self, **kwargs):
        return self._new("legend", **kwargs)

    def add_plot_axis(self, axis, **kwargs):
        kwargs["axis"] = axis
        return self._new("axis", **kwargs)

    def add_line_series(self, x, y, **kwargs):
        tag = self._new("series", **kwargs)
        self.values[tag] = [list(x), list(y)]
        return tag

    def does_item_exist(self, tag):
        return tag in self.config

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def set_value(self, tag, value):
        self.values[tag] = value

    def get_value(self, tag):
        return self.values.get(tag)

    def fit_axis_data(self, tag):
        self.calls.append(("fit", tag, {}))

    def focus_item(self, tag):
        self.calls.append(("focus", tag, {}))

    def bind_item_theme(self, tag, theme):
        self.calls.append(("bind_theme", tag, {"theme": theme}))

    def delete_item(self, tag):
        self.calls.append(("delete", tag, {}))
        self.config.pop(tag, None)
        self.values.pop(tag, None)

    @contextmanager
    def theme(self):
        tag = self._new("theme")
        yield tag

    @contextmanager
    def theme_component(self, component):
        self.calls.append(("theme_component", component, {}))
        yield component

    def add_theme_color(self, key, value, **kwargs):
        self.calls.append(("theme_color", key, {"value": value, **kwargs}))

    def add_theme_style(self, key, value, **kwargs):
        self.calls.append(("theme_style", key, {"value": value, **kwargs}))


def test_qplotwidget_owns_axes_series_and_keeps_renderer_symbols_internal():
    backend = FakeBackend()
    plot = QPlotWidget("History", backend=backend, width=480, height=240)
    legend = plot.addLegend(location=QPlotWidget.NorthEast)
    x_axis = plot.addAxis(QPlotAxis.XAxis, "Time")
    y_axis = plot.addAxis(QPlotAxis.YAxis, "Value")
    series = plot.addLineSeries(
        [0, 1], [2, 3], axis=y_axis, label="Live",
        color=(10, 20, 30, 255), width=2.0, marker=QLineSeries.CircleMarker,
    )

    assert backend.config[plot.tag]["label"] == "History"
    assert backend.config[legend]["location"] == backend.mvPlot_Location_NorthEast
    assert backend.config[x_axis.tag]["axis"] == backend.mvXAxis
    assert backend.config[y_axis.tag]["axis"] == backend.mvYAxis
    assert series.data() == ([0, 1], [2, 3])
    assert any(call[0] == "theme_style" and call[1] == backend.mvPlotStyleVar_Marker
               for call in backend.calls)

    series.setData([4, 5], [6, 7])
    assert series.data() == ([4, 5], [6, 7])
    assert y_axis.fitData() is True
    assert ("fit", y_axis.tag, {}) in backend.calls


def test_qplotwidget_creates_default_y_axis_and_series_lifetime_is_owned():
    backend = FakeBackend()
    plot = QPlotWidget(backend=backend)
    series = plot.addLineSeries([1], [9], label="Auto axis")
    axes = plot.axes()
    assert len(axes) == 1
    assert axes[0].orientation() == QPlotAxis.YAxis
    assert series.parent is axes[0]
    theme = series._owned_theme
    assert theme is not None
    series.delete()
    assert not backend.does_item_exist(series.tag)
    assert not backend.does_item_exist(theme)
