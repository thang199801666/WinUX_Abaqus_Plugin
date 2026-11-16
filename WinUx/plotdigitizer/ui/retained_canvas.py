"""Reuse canvas primitives across viewport and pointer updates."""
from types import SimpleNamespace

from DearUIQt.gui import QPainter, QPaintLayer


_POSITIONAL = {
    'draw_line': ('p1', 'p2'),
    'draw_rectangle': ('pmin', 'pmax'),
    'draw_circle': ('center', 'radius'),
    'draw_triangle': ('p1', 'p2', 'p3'),
    'draw_quad': ('p1', 'p2', 'p3', 'p4'),
    'draw_polygon': ('points',),
    'draw_text': ('pos', 'text'),
    'draw_image': ('texture_tag', 'pmin', 'pmax'),
}


def _freeze(value):
    # QPainter already supplies immutable point/color tuples in the hot path.
    # Copy mutable polygon/list inputs, not every scalar inside those tuples.
    return tuple(_freeze(item) for item in value) if isinstance(value, list) else value


class _PaintCommands:
    def __init__(self, backend, parent):
        self.backend, self.parent = backend, parent
        self.items = []
        self._circle_styles = {}
        self.index = 0
        for name in _POSITIONAL:
            setattr(self, name, self._draw(name))

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def _draw(self, name):
        def draw(*args, **kwargs):
            values = dict(zip(_POSITIONAL[name], args))
            values.update(kwargs)
            values.pop('parent', None)
            values = {key: _freeze(value) for key, value in values.items()}
            index = self.index
            self.index += 1
            previous = self.items[index] if index < len(self.items) else None
            if previous is not None and previous[0] == name:
                _, tag, old_values = previous
                changed = {key: value for key, value in values.items()
                           if key not in old_values or old_values[key] != value}
                if changed:
                    self.backend.configure_item(tag, **changed)
                self.items[index] = (name, tag, values)
                if name == 'draw_circle':
                    self._remember_circle_style(tag, values)
                return tag
            # Replacing a primitive in-place must preserve painter order.
            options = {'parent': self.parent}
            if previous is not None:
                options['before'] = previous[1]
            tag = getattr(self.backend, name)(**values, **options)
            if previous is not None:
                self.backend.delete_item(previous[1])
                self._circle_styles.pop(previous[1], None)
                self.items[index] = (name, tag, values)
            else:
                self.items.append((name, tag, values))
            if name == 'draw_circle':
                self._remember_circle_style(tag, values)
            return tag
        return draw

    def _remember_circle_style(self, tag, values):
        self._circle_styles[tag] = tuple(values.get(key) for key in
            ('radius', 'segments', 'color', 'fill', 'thickness'))

    def circles(self, centers, radius, *, color, fill, thickness=1.0):
        """Update a marker run with one shared style comparison per old style."""
        style = {'radius': radius, 'segments': 0, 'color': _freeze(color),
                 'fill': _freeze(fill), 'thickness': thickness}
        signature = tuple(style.values())
        style_changes = {}
        for center in centers:
            index = self.index
            previous = self.items[index] if index < len(self.items) else None
            if previous is None or previous[0] != 'draw_circle':
                self.draw_circle(center, **style)
                continue
            self.index += 1
            _, tag, values = previous
            old_style = self._circle_styles.get(tag)
            if old_style != signature:
                if old_style not in style_changes:
                    style_changes[old_style] = {key: value for key, value in style.items()
                                                if values.get(key) != value}
                changed = dict(style_changes[old_style])
                self._circle_styles[tag] = signature
            else:
                changed = {}
            center = _freeze(center)
            if values.get('center') != center:
                changed['center'] = center
            if changed:
                self.backend.configure_item(tag, **changed)
                values.update(changed)

    def finish(self):
        for _, tag, _ in self.items[self.index:]:
            self.backend.delete_item(tag)
            self._circle_styles.pop(tag, None)
        del self.items[self.index:]


class RetainedCanvasLayer(QPaintLayer):
    """A retained QPainter stream, optionally translated as one native node.

    Command order is stable, but command type/count may change after edits.
    Unchanged commands cause no renderer mutation; changed ones are configured
    in place. Marker radii therefore keep their screen-space sizing on zoom.
    """
    def __init__(self, parent, *, translate=False):
        super().__init__(parent)
        self._node = self.backend.add_draw_node(parent=self.tag) if translate else self.tag
        self._translation = (0.0, 0.0)
        self._commands = _PaintCommands(self.backend, self._node)

    def begin(self):
        self._commands.index = 0
        self.setTranslation(0, 0)
        device = SimpleNamespace(tag=self._node, backend=self.backend)
        painter = QPainter(device)
        painter._backend = self._commands
        return painter

    def finish(self):
        self._commands.finish()

    def drawCircles(self, centers, radius, *, color, fill, thickness=1.0):
        self._commands.circles(centers, radius, color=color, fill=fill, thickness=thickness)

    def setTranslation(self, x, y):
        translation = (float(x), float(y))
        if translation == self._translation:
            return
        if self._node == self.tag:
            raise ValueError('This paint layer has no translation node')
        matrix = self.backend.create_translation_matrix((*translation, 0.0))
        self.backend.apply_transform(self._node, matrix)
        self._translation = translation

    def clear(self):
        self._commands.index = 0
        self._commands.finish()
        self.setTranslation(0, 0)
        return True
