"""Ownership and explicit signal connections independent of GUI libraries."""
from __future__ import annotations

import threading
import weakref


class Qt:
    """Small namespace for connection/orientation constants used by wrappers."""

    AutoConnection = 0
    DirectConnection = 1
    QueuedConnection = 2
    Horizontal = 1
    Vertical = 2

    # Qt.ScrollBarPolicy values.  DearUIQt backends may map AlwaysOn and
    # AsNeeded to the same native primitive when the renderer has no separate
    # always-visible scrollbar mode, but applications can retain the Qt API.
    ScrollBarAsNeeded = 0
    ScrollBarAlwaysOff = 1
    ScrollBarAlwaysOn = 2

    # Qt.ItemDataRole values used by model/view convenience widgets.
    DisplayRole = 0
    DecorationRole = 1
    EditRole = 2
    ToolTipRole = 3
    StatusTipRole = 4
    WhatsThisRole = 5
    FontRole = 6
    TextAlignmentRole = 7
    BackgroundRole = 8
    ForegroundRole = 9
    CheckStateRole = 10
    UserRole = 0x0100
    Unchecked = 0
    PartiallyChecked = 1
    Checked = 2

    # Qt.ItemFlag values used by QAbstractItemModel/QStyledItemDelegate.
    NoItemFlags = 0x00000000
    ItemIsSelectable = 0x00000001
    ItemIsEditable = 0x00000002
    ItemIsDragEnabled = 0x00000004
    ItemIsDropEnabled = 0x00000008
    ItemIsUserCheckable = 0x00000010
    ItemIsEnabled = 0x00000020
    ItemIsAutoTristate = 0x00000040
    ItemNeverHasChildren = 0x00000080
    ItemIsUserTristate = 0x00000100

    # Qt.SortOrder / MatchFlag values used by standard item models.
    AscendingOrder = 0
    DescendingOrder = 1
    MatchExactly = 0x0000
    MatchContains = 0x0001
    MatchStartsWith = 0x0002
    MatchEndsWith = 0x0003
    MatchRegularExpression = 0x0004
    MatchWildcard = 0x0005
    MatchFixedString = 0x0008
    MatchCaseSensitive = 0x0010
    MatchWrap = 0x0020
    MatchRecursive = 0x0040

    # Keyboard modifier bit flags use Qt-compatible values so wrapper code can
    # retain the familiar ``event.modifiers() & Qt.ControlModifier`` contract
    # without depending on a native Qt binding.
    NoModifier = 0x00000000
    ShiftModifier = 0x02000000
    ControlModifier = 0x04000000
    AltModifier = 0x08000000
    MetaModifier = 0x10000000

    # Qt.Key values used by backend-neutral input bindings. Printable keys use
    # their Unicode/ASCII code while navigation/function keys occupy Qt's
    # established 0x01000000 range.
    Key_Escape = 0x01000000
    Key_Tab = 0x01000001
    Key_Backtab = 0x01000002
    Key_Backspace = 0x01000003
    Key_Return = 0x01000004
    Key_Enter = 0x01000005
    Key_Insert = 0x01000006
    Key_Delete = 0x01000007
    Key_Home = 0x01000010
    Key_End = 0x01000011
    Key_Left = 0x01000012
    Key_Up = 0x01000013
    Key_Right = 0x01000014
    Key_Down = 0x01000015
    Key_PageUp = 0x01000016
    Key_PageDown = 0x01000017
    Key_F1 = 0x01000030
    Key_F2 = 0x01000031
    Key_F3 = 0x01000032
    Key_F4 = 0x01000033
    Key_F5 = 0x01000034
    Key_F6 = 0x01000035
    Key_F7 = 0x01000036
    Key_F8 = 0x01000037
    Key_F9 = 0x01000038
    Key_F10 = 0x01000039
    Key_F11 = 0x0100003A
    Key_F12 = 0x0100003B
    Key_Space = 0x20
    Key_A = ord("A")
    Key_B = ord("B")
    Key_C = ord("C")
    Key_D = ord("D")
    Key_E = ord("E")
    Key_F = ord("F")
    Key_G = ord("G")
    Key_H = ord("H")
    Key_I = ord("I")
    Key_J = ord("J")
    Key_K = ord("K")
    Key_L = ord("L")
    Key_M = ord("M")
    Key_N = ord("N")
    Key_O = ord("O")
    Key_P = ord("P")
    Key_Q = ord("Q")
    Key_R = ord("R")
    Key_S = ord("S")
    Key_T = ord("T")
    Key_U = ord("U")
    Key_V = ord("V")
    Key_W = ord("W")
    Key_X = ord("X")
    Key_Y = ord("Y")
    Key_Z = ord("Z")

    # Mouse button flags mirror Qt.MouseButton values.  Keeping the values
    # toolkit-neutral lets DearPyGui/native bridges feed one retained event
    # pipeline without exposing backend-specific button constants to widgets.
    NoButton = 0x00000000
    LeftButton = 0x00000001
    RightButton = 0x00000002
    MiddleButton = 0x00000004

    # QWidget attribute used by close() ownership semantics.
    WA_DeleteOnClose = 55


class QPoint:
    """Small Qt-compatible integer point value.

    The object intentionally remains tuple-friendly (iteration, indexing and
    tuple equality) so existing DearUIQt code can adopt Qt geometry types
    incrementally without changing backend call sites all at once.
    """

    __slots__ = ("_x", "_y")

    def __init__(self, x=0, y=0):
        if isinstance(x, (QPoint, QPointF)) and y == 0:
            self._x, self._y = int(x.x()), int(x.y())
        else:
            self._x, self._y = int(x), int(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def setX(self, x):
        self._x = int(x)

    def setY(self, y):
        self._y = int(y)

    def manhattanLength(self):
        return abs(self._x) + abs(self._y)

    def isNull(self):
        return self._x == 0 and self._y == 0

    def transposed(self):
        return QPoint(self._y, self._x)

    def toTuple(self):
        return self._x, self._y

    def __iter__(self):
        yield self._x
        yield self._y

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return self.toTuple()[index]

    def __repr__(self):
        return "QPoint({}, {})".format(self._x, self._y)

    def __eq__(self, other):
        if isinstance(other, (QPoint, QPointF)):
            return self._x == other.x() and self._y == other.y()
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return self.toTuple() == tuple(other)
        return NotImplemented

    def __add__(self, other):
        x, y = other
        return QPoint(self._x + int(x), self._y + int(y))

    def __sub__(self, other):
        x, y = other
        return QPoint(self._x - int(x), self._y - int(y))


class QPointF:
    """Qt-compatible floating-point point used by pointer events."""

    __slots__ = ("_x", "_y")

    def __init__(self, x=0.0, y=0.0):
        if isinstance(x, (QPoint, QPointF)) and y == 0.0:
            self._x, self._y = float(x.x()), float(x.y())
        else:
            self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def setX(self, x):
        self._x = float(x)

    def setY(self, y):
        self._y = float(y)

    def manhattanLength(self):
        return abs(self._x) + abs(self._y)

    def isNull(self):
        return self._x == 0.0 and self._y == 0.0

    def toPoint(self):
        return QPoint(round(self._x), round(self._y))

    def toTuple(self):
        return self._x, self._y

    def __iter__(self):
        yield self._x
        yield self._y

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return self.toTuple()[index]

    def __repr__(self):
        return "QPointF({}, {})".format(self._x, self._y)

    def __eq__(self, other):
        if isinstance(other, (QPoint, QPointF)):
            return self._x == float(other.x()) and self._y == float(other.y())
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return self.toTuple() == tuple(other)
        return NotImplemented

    def __add__(self, other):
        x, y = other
        return QPointF(self._x + float(x), self._y + float(y))

    def __sub__(self, other):
        x, y = other
        return QPointF(self._x - float(x), self._y - float(y))


class QSize:
    """Small immutable Qt-compatible size value used by layout hints.

    Keeping size hints toolkit-neutral lets layouts negotiate geometry without
    querying Dear PyGui during every layout request.  This mirrors QtCore.QSize
    closely enough for wrapper code while avoiding another GUI dependency.
    """

    __slots__ = ("_width", "_height")

    def __init__(self, width=-1, height=-1):
        self._width = int(width)
        self._height = int(height)

    def width(self):
        return self._width

    def height(self):
        return self._height

    def setWidth(self, width):
        self._width = int(width)

    def setHeight(self, height):
        self._height = int(height)

    def isNull(self):
        return self._width == 0 and self._height == 0

    def isValid(self):
        return self._width >= 0 and self._height >= 0

    def isEmpty(self):
        return self._width <= 0 or self._height <= 0

    def expandedTo(self, other):
        other = other if isinstance(other, QSize) else QSize(*other)
        return QSize(max(self._width, other.width()), max(self._height, other.height()))

    def boundedTo(self, other):
        other = other if isinstance(other, QSize) else QSize(*other)
        return QSize(min(self._width, other.width()), min(self._height, other.height()))

    def transposed(self):
        return QSize(self._height, self._width)

    def __iter__(self):
        yield self._width
        yield self._height

    def __repr__(self):
        return "QSize({}, {})".format(self._width, self._height)

    def __eq__(self, other):
        if isinstance(other, QSize):
            return (self._width, self._height) == (other._width, other._height)
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return (self._width, self._height) == tuple(other)
        return NotImplemented

    def __add__(self, other):
        other = other if isinstance(other, QSize) else QSize(*other)
        return QSize(self._width + other.width(), self._height + other.height())

    def __sub__(self, other):
        other = other if isinstance(other, QSize) else QSize(*other)
        return QSize(self._width - other.width(), self._height - other.height())


class QRect:
    """Small Qt-compatible integer rectangle for retained widget geometry."""

    __slots__ = ("_x", "_y", "_width", "_height")

    def __init__(self, x=0, y=0, width=0, height=0):
        if isinstance(x, QRect) and y == 0 and width == 0 and height == 0:
            self._x, self._y = x.x(), x.y()
            self._width, self._height = x.width(), x.height()
            return
        if isinstance(x, (QPoint, QPointF)) and isinstance(y, QSize):
            self._x, self._y = int(x.x()), int(x.y())
            self._width, self._height = int(y.width()), int(y.height())
            return
        self._x, self._y = int(x), int(y)
        self._width, self._height = int(width), int(height)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._width

    def height(self):
        return self._height

    def left(self):
        return self._x

    def top(self):
        return self._y

    def right(self):
        return self._x + self._width - 1

    def bottom(self):
        return self._y + self._height - 1

    def topLeft(self):
        return QPoint(self._x, self._y)

    def bottomRight(self):
        return QPoint(self.right(), self.bottom())

    def topRight(self):
        return QPoint(self.right(), self.top())

    def bottomLeft(self):
        return QPoint(self.left(), self.bottom())

    def center(self):
        return QPoint(self._x + self._width // 2, self._y + self._height // 2)

    def size(self):
        return QSize(self._width, self._height)

    def setX(self, x):
        right = self.right()
        self._x = int(x)
        self._width = max(0, right - self._x + 1)

    def setY(self, y):
        bottom = self.bottom()
        self._y = int(y)
        self._height = max(0, bottom - self._y + 1)

    def setWidth(self, width):
        self._width = int(width)

    def setHeight(self, height):
        self._height = int(height)

    def setSize(self, size):
        size = size if isinstance(size, QSize) else QSize(*size)
        self._width, self._height = size.width(), size.height()

    def moveTo(self, x, y=None):
        point = x if isinstance(x, (QPoint, QPointF)) and y is None else QPoint(x, y)
        self._x, self._y = int(point.x()), int(point.y())

    def moveLeft(self, x):
        self._x = int(x)

    def moveTop(self, y):
        self._y = int(y)

    def moveRight(self, x):
        self._x = int(x) - self._width + 1

    def moveBottom(self, y):
        self._y = int(y) - self._height + 1

    def moveCenter(self, point):
        point = point if isinstance(point, (QPoint, QPointF)) else QPoint(*point)
        self._x = int(point.x()) - self._width // 2
        self._y = int(point.y()) - self._height // 2

    def isNull(self):
        return self._width == 0 and self._height == 0

    def isEmpty(self):
        return self._width <= 0 or self._height <= 0

    def isValid(self):
        return self._width > 0 and self._height > 0

    def contains(self, point, proper=False):
        px, py = point
        if proper:
            return self.left() < px < self.right() and self.top() < py < self.bottom()
        return self.left() <= px <= self.right() and self.top() <= py <= self.bottom()

    def translated(self, dx, dy=None):
        if dy is None:
            dx, dy = dx
        return QRect(self._x + int(dx), self._y + int(dy), self._width, self._height)

    def translate(self, dx, dy=None):
        if dy is None:
            dx, dy = dx
        self._x += int(dx)
        self._y += int(dy)

    def intersects(self, other):
        other = other if isinstance(other, QRect) else QRect(*other)
        if self.isEmpty() or other.isEmpty():
            return False
        return not (self.right() < other.left() or other.right() < self.left()
                    or self.bottom() < other.top() or other.bottom() < self.top())

    def intersected(self, other):
        other = other if isinstance(other, QRect) else QRect(*other)
        if not self.intersects(other):
            return QRect()
        left = max(self.left(), other.left())
        top = max(self.top(), other.top())
        right = min(self.right(), other.right())
        bottom = min(self.bottom(), other.bottom())
        return QRect(left, top, right - left + 1, bottom - top + 1)

    def united(self, other):
        other = other if isinstance(other, QRect) else QRect(*other)
        if self.isEmpty():
            return QRect(other)
        if other.isEmpty():
            return QRect(self)
        left = min(self.left(), other.left())
        top = min(self.top(), other.top())
        right = max(self.right(), other.right())
        bottom = max(self.bottom(), other.bottom())
        return QRect(left, top, right - left + 1, bottom - top + 1)

    def adjusted(self, left, top, right, bottom):
        x = self._x + int(left)
        y = self._y + int(top)
        new_right = self.right() + int(right)
        new_bottom = self.bottom() + int(bottom)
        return QRect(x, y, new_right - x + 1, new_bottom - y + 1)

    def toTuple(self):
        return self._x, self._y, self._width, self._height

    def __iter__(self):
        yield from self.toTuple()

    def __len__(self):
        return 4

    def __getitem__(self, index):
        return self.toTuple()[index]

    def __repr__(self):
        return "QRect({}, {}, {}, {})".format(*self.toTuple())

    def __eq__(self, other):
        if isinstance(other, QRect):
            return self.toTuple() == other.toTuple()
        if isinstance(other, (tuple, list)) and len(other) == 4:
            return self.toTuple() == tuple(other)
        return NotImplemented


class QMargins:
    """Immutable Qt-compatible layout margins value."""

    __slots__ = ("_left", "_top", "_right", "_bottom")

    def __init__(self, left=0, top=0, right=0, bottom=0):
        self._left = int(left)
        self._top = int(top)
        self._right = int(right)
        self._bottom = int(bottom)

    def left(self):
        return self._left

    def top(self):
        return self._top

    def right(self):
        return self._right

    def bottom(self):
        return self._bottom

    def __iter__(self):
        yield self._left
        yield self._top
        yield self._right
        yield self._bottom

    def __repr__(self):
        return "QMargins({}, {}, {}, {})".format(
            self._left, self._top, self._right, self._bottom)

    def __eq__(self, other):
        if isinstance(other, QMargins):
            return tuple(self) == tuple(other)
        if isinstance(other, (tuple, list)) and len(other) == 4:
            return tuple(self) == tuple(other)
        return NotImplemented


class QSizePolicy:
    """Small Qt-compatible widget sizing policy.

    The policy is retained metadata used by DearUIQt layouts.  It deliberately
    stays toolkit-neutral: layouts can decide whether a hidden item contributes
    a size hint without crossing into DearPyGui, while future backends can map
    the horizontal/vertical policies to native stretch behaviour.
    """

    Fixed = 0
    Minimum = 1
    Maximum = 4
    Preferred = 5
    Expanding = 7
    MinimumExpanding = 3
    Ignored = 13

    def __init__(self, horizontal=Preferred, vertical=Preferred):
        self._horizontal = int(horizontal)
        self._vertical = int(vertical)
        self._horizontal_stretch = 0
        self._vertical_stretch = 0
        self._retain_size_when_hidden = False

    def horizontalPolicy(self):
        return self._horizontal

    def verticalPolicy(self):
        return self._vertical

    def setHorizontalPolicy(self, policy):
        self._horizontal = int(policy)

    def setVerticalPolicy(self, policy):
        self._vertical = int(policy)

    def horizontalStretch(self):
        return self._horizontal_stretch

    def verticalStretch(self):
        return self._vertical_stretch

    def setHorizontalStretch(self, stretch):
        self._horizontal_stretch = max(0, min(255, int(stretch)))

    def setVerticalStretch(self, stretch):
        self._vertical_stretch = max(0, min(255, int(stretch)))

    def retainSizeWhenHidden(self):
        return self._retain_size_when_hidden

    def setRetainSizeWhenHidden(self, retain):
        self._retain_size_when_hidden = bool(retain)

    def expandingDirections(self):
        directions = 0
        if self._horizontal in (self.Expanding, self.MinimumExpanding):
            directions |= Qt.Horizontal
        if self._vertical in (self.Expanding, self.MinimumExpanding):
            directions |= Qt.Vertical
        return directions

    def copy(self):
        other = QSizePolicy(self._horizontal, self._vertical)
        other._horizontal_stretch = self._horizontal_stretch
        other._vertical_stretch = self._vertical_stretch
        other._retain_size_when_hidden = self._retain_size_when_hidden
        return other

    def __eq__(self, other):
        if not isinstance(other, QSizePolicy):
            return NotImplemented
        return (
            self._horizontal == other._horizontal and
            self._vertical == other._vertical and
            self._horizontal_stretch == other._horizontal_stretch and
            self._vertical_stretch == other._vertical_stretch and
            self._retain_size_when_hidden == other._retain_size_when_hidden
        )


class QEvent:
    """Small Qt-compatible event value used by the retained wrapper layer.

    The wrapper intentionally keeps events toolkit-neutral. Native Dear ImGui/DPG
    callbacks may translate into these values, while unit/domain code can install
    event filters without importing the rendering backend.
    """

    None_ = 0
    ParentChange = 1
    Show = 2
    Hide = 3
    Close = 4
    EnabledChange = 5
    DynamicPropertyChange = 6
    LayoutRequest = 7
    DeferredDelete = 8
    FocusIn = 9
    FocusOut = 10
    WindowActivate = 11
    WindowDeactivate = 12
    Polish = 13
    ChildAdded = 14
    ChildRemoved = 15
    KeyPress = 16
    KeyRelease = 17
    ShortcutOverride = 18
    MouseButtonPress = 19
    MouseButtonRelease = 20
    MouseMove = 21
    Enter = 22
    Leave = 23
    ThreadChange = 24
    StyleChange = 25
    PaletteChange = 26
    ApplicationPaletteChange = 27
    User = 1000

    def __init__(self, event_type, **payload):
        self._type = int(event_type)
        self.payload = dict(payload)
        self._accepted = True

    def type(self):
        return self._type

    def accept(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


class QCloseEvent(QEvent):
    def __init__(self):
        super().__init__(QEvent.Close)


class QKeyEvent(QEvent):
    """Toolkit-neutral Qt-style keyboard event.

    DearPyGui key constants are intentionally preserved as the key value.  The
    retained wrapper therefore does not need a second key-code translation
    table, while modifiers use stable Qt-compatible bit flags.
    """

    def __init__(self, event_type, key, modifiers=Qt.NoModifier, *, text="",
                 auto_repeat=False, count=1):
        if event_type not in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            raise ValueError("QKeyEvent requires a keyboard QEvent type")
        super().__init__(event_type)
        self._key = key
        self._modifiers = int(modifiers)
        self._text = str(text or "")
        self._auto_repeat = bool(auto_repeat)
        self._count = max(1, int(count))

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def text(self):
        return self._text

    def isAutoRepeat(self):
        return self._auto_repeat

    def count(self):
        return self._count


class QMouseEvent(QEvent):
    """Toolkit-neutral Qt-style pointer event.

    Positions are retained as global/client coordinates supplied by the host
    bridge.  Optimized surfaces can therefore participate in Qt-like dispatch
    without becoming QWidget instances or polling a second native callback
    stream.
    """

    def __init__(self, event_type, position=(0.0, 0.0), *,
                 button=Qt.NoButton, buttons=Qt.NoButton,
                 modifiers=Qt.NoModifier):
        if event_type not in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                QEvent.MouseMove):
            raise ValueError("QMouseEvent requires a mouse QEvent type")
        super().__init__(event_type)
        try:
            x, y = position
        except (TypeError, ValueError):
            raise TypeError("position must be a two-value sequence")
        self._position = QPointF(x, y)
        self._button = int(button)
        self._buttons = int(buttons)
        self._modifiers = int(modifiers)

    def position(self):
        return self._position

    def globalPosition(self):
        return self._position

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def modifiers(self):
        return self._modifiers


class QChildEvent(QEvent):
    """Qt-style child ownership notification delivered to the parent object."""

    def __init__(self, event_type, child):
        if event_type not in (QEvent.ChildAdded, QEvent.ChildRemoved):
            raise ValueError("QChildEvent requires ChildAdded or ChildRemoved")
        super().__init__(event_type, child=child)
        self._child = child

    def child(self):
        return self._child

    def added(self):
        return self.type() == QEvent.ChildAdded

    def removed(self):
        return self.type() == QEvent.ChildRemoved


class SignalConnection:
    def __init__(self, signal, slot, receiver, queued):
        self.signal, self.slot, self.receiver, self.queued = signal, slot, receiver, queued
        self.active = True

    def disconnect(self):
        if not self.active:
            return
        self.active = False
        self.signal._slots.remove(self)
        if self.receiver is not None:
            self.receiver._connections.discard(self)
        self.slot = self.receiver = None

    def deliver(self, args):
        if self.active and (self.receiver is None or not self.receiver._deleted):
            if (self.receiver is not None and self.queued is not False and
                    threading.get_ident() != self.receiver.threadId()):
                raise RuntimeError("signal scheduler must deliver on the receiver's thread")
            self.slot(*args)


class Signal:
    def __init__(self, owner=None):
        self._slots = []
        self.owner = owner

    def connect(self, slot, connection_type=None, *, receiver=None, queued=None):
        if not callable(slot):
            raise TypeError("signal slot must be callable")
        if connection_type is not None:
            if queued is not None:
                raise ValueError("use either connection_type or queued, not both")
            if connection_type == Qt.AutoConnection:
                queued = None
            elif connection_type == Qt.DirectConnection:
                queued = False
            elif connection_type == Qt.QueuedConnection:
                queued = True
            else:
                raise ValueError("unknown Qt connection type")
        if receiver is None and isinstance(getattr(slot, "__self__", None), QObject):
            receiver = slot.__self__
        if receiver is not None and receiver._deleted:
            raise RuntimeError("cannot connect a deleted receiver")
        if queued and (receiver is None or getattr(receiver, "_after", None) is None):
            raise ValueError("queued connections require a receiver with a UI scheduler")
        for connection in self._slots:
            if connection.slot == slot and connection.receiver is receiver and connection.queued == queued:
                return connection
        connection = SignalConnection(self, slot, receiver, queued)
        self._slots.append(connection)
        if receiver is not None:
            receiver._connections.add(connection)
        return connection

    def disconnect(self, slot=None):
        if slot is None:
            for connection in tuple(self._slots):
                connection.disconnect()
        else:
            for connection in tuple(self._slots):
                if connection is slot or connection.slot == slot:
                    connection.disconnect()

    def emit(self, *args):
        if self.owner is not None and (self.owner._signals_blocked or self.owner._deleted):
            return
        for connection in tuple(self._slots):
            if not connection.active:
                continue
            auto_queue = (connection.queued is None and connection.receiver is not None and
                          threading.get_ident() != connection.receiver.threadId())
            if connection.queued or auto_queue:
                if getattr(connection.receiver, "_after", None) is None:
                    raise RuntimeError("cross-thread signal delivery requires a receiver scheduler")
                connection.receiver._after(0, connection.deliver, args)
            else:
                connection.deliver(args)


class QObject:
    """UI-thread-owned object tree with explicit, idempotent disposal."""

    def __init__(self, parent=None, *, after=None):
        self.parent = None
        self._children = []
        self._deleted = False
        self._connections = set()
        self._signals_blocked = False
        self._delete_later_pending = False
        self._event_filters = []
        self._filter_targets = set()
        self._thread_id = threading.get_ident()
        self._thread_affinity = None
        self._after = after if after is not None else getattr(parent, "_after", None)
        self._object_name = ""
        self.destroyed = Signal()
        self.objectNameChanged = Signal(self)
        self.setParent(parent)

    def installEventFilter(self, filter_object):
        if self._deleted:
            raise RuntimeError("cannot install an event filter on a deleted object")
        if not isinstance(filter_object, QObject):
            raise TypeError("event filter must be a QObject")
        if filter_object._deleted:
            raise RuntimeError("cannot install a deleted event filter")
        if filter_object.threadId() != self.threadId():
            raise RuntimeError("event filter and watched object must belong to the same thread")
        if filter_object not in self._event_filters:
            self._event_filters.append(filter_object)
            filter_object._filter_targets.add(self)
        return filter_object

    def removeEventFilter(self, filter_object):
        try:
            self._event_filters.remove(filter_object)
            filter_object._filter_targets.discard(self)
            return True
        except ValueError:
            return False

    def eventFilter(self, watched, event):
        return False

    def event(self, event):
        event_type = event.type()
        if event_type == QEvent.DeferredDelete:
            # QApplication batches deferred destruction just like Qt's posted
            # DeferredDelete events. The object remains valid until this turn.
            self._delete_later_pending = False
            self.delete()
            return True
        if event_type in (QEvent.ChildAdded, QEvent.ChildRemoved):
            self.childEvent(event)
            return True
        return False

    def childEvent(self, event):
        """Hook matching QObject::childEvent for ownership-tree observers."""
        pass

    def _send_event_local(self, event):
        """Deliver through receiver-local filters without QApplication recursion."""
        if self._deleted:
            return False
        if not isinstance(event, QEvent):
            raise TypeError("event must be QEvent")
        for filter_object in reversed(tuple(self._event_filters)):
            if filter_object._deleted:
                self.removeEventFilter(filter_object)
                continue
            # Qt only invokes an event filter when filter and watched object
            # share thread affinity.  Keep the installed relationship retained
            # across moveToThread(), but suspend delivery while affinities differ.
            if filter_object.threadId() != self.threadId():
                continue
            if bool(filter_object.eventFilter(self, event)):
                return True
        return bool(self.event(event))

    def sendEvent(self, event):
        """Synchronously deliver an event through the owning QApplication.

        QObject exposes this convenience even though real Qt places sendEvent on
        QCoreApplication. Routing here ensures wrapper-generated lifecycle events
        (show/hide/child/focus/layout) are visible to application-wide filters.
        """
        if self._deleted:
            return False
        if not isinstance(event, QEvent):
            raise TypeError("event must be QEvent")
        try:
            from .application import QApplication
            application = QApplication.instance()
            if (application is not None and application is not self
                    and application.threadId() == self.threadId()):
                return application.notify(self, event)
        except ImportError:
            # During the core/application import cycle there may not yet be a
            # QApplication class to consult; local delivery is still correct.
            pass
        return self._send_event_local(event)

    def setParent(self, parent):
        if self._deleted:
            raise RuntimeError("cannot reparent a deleted object")
        if parent is not None:
            if parent._deleted:
                raise RuntimeError("cannot attach to a deleted parent")
            if parent.threadId() != self.threadId():
                raise RuntimeError("QObject parent and child must belong to the same thread")
            ancestor = parent
            while ancestor is not None:
                if ancestor is self:
                    raise ValueError("object ownership cannot contain a cycle")
                next_parent = getattr(ancestor, "parent", None)
                # QAbstractItemModel reserves parent(index) for model hierarchy.
                # Its QObject owner is exposed through objectParent() instead.
                if callable(next_parent):
                    object_parent = getattr(ancestor, "objectParent", None)
                    ancestor = object_parent() if callable(object_parent) else None
                else:
                    ancestor = next_parent
        if self.parent is parent:
            return
        previous = self.parent
        if previous is not None:
            previous._children.remove(self)
        # ChildRemoved observers should see the new ownership state rather than
        # a stale pointer to the previous parent. This also makes re-entrant
        # ownership inspection match Qt's already-applied object tree.
        self.parent = None
        if previous is not None:
            previous.sendEvent(QChildEvent(QEvent.ChildRemoved, self))
        self.parent = parent
        if parent is not None:
            parent._children.append(self)
            parent.sendEvent(QChildEvent(QEvent.ChildAdded, self))
        self.sendEvent(QEvent(QEvent.ParentChange, parent=parent, previous=previous))

    def threadId(self):
        affinity = self._thread_affinity
        if affinity is not None:
            worker_id = affinity.workerThreadId()
            return affinity.affinityId() if worker_id is None else worker_id
        return self._thread_id

    def thread(self):
        """Return the QThread affinity object, or ``None`` for the creator thread."""
        return self._thread_affinity

    def moveToThread(self, thread):
        """Move this object tree to a DearUIQt QThread event loop.

        Qt requires a parentless object for affinity changes and automatically
        moves its children.  DearUIQt follows the same ownership rule.  Queued
        signals and QTimer then use the QThread scheduler rather than a private
        worker callback bridge.
        """
        if self._deleted:
            raise RuntimeError("cannot move a deleted object")
        if self.parent is not None:
            raise RuntimeError("cannot move an object with a parent")
        if threading.get_ident() != self.threadId():
            raise RuntimeError("moveToThread must be called from the object's owning thread")
        if thread is None:
            raise TypeError("moveToThread requires a QThread")
        # Avoid a hard import cycle while still enforcing the public contract.
        from .thread import QThread
        if not isinstance(thread, QThread):
            raise TypeError("moveToThread requires a QThread")
        if thread._deleted:
            raise RuntimeError("cannot move to a deleted QThread")

        def apply(obj):
            obj.sendEvent(QEvent(QEvent.ThreadChange, thread=thread))
            obj._thread_affinity = thread
            obj._after = thread.after
            for child in tuple(obj._children):
                apply(child)

        apply(self)
        return True

    def blockSignals(self, blocked):
        previous = self._signals_blocked
        self._signals_blocked = bool(blocked)
        return previous

    def signalsBlocked(self):
        return self._signals_blocked

    def setObjectName(self, name):
        """Set QObject identity without requiring a QWidget/native backend."""
        value = str(name or "")
        if value == self._object_name:
            return False
        self._object_name = value
        self.objectNameChanged.emit(value)
        return True

    def objectName(self):
        return self._object_name

    def children(self):
        return list(self._children)

    def findChildren(self, object_type, name=None):
        result = []
        for child in self._children:
            if isinstance(child, object_type) and (name is None or
                    getattr(child, "objectName", lambda: "")() == name):
                result.append(child)
            result.extend(child.findChildren(object_type, name))
        return result

    def findChild(self, object_type, name=None):
        matches = self.findChildren(object_type, name)
        return matches[0] if matches else None

    def deleteLater(self):
        """Post Qt-style DeferredDelete without creating a private wake-up.

        When a QApplication owns this thread, deferred deletions share its posted
        event queue and therefore one scheduler wake-up.  Standalone objects keep
        the historical scheduler fallback.
        """
        if self._deleted or self._delete_later_pending:
            return
        if self._after is None:
            raise RuntimeError("deferred deletion requires a UI scheduler")
        self._delete_later_pending = True
        try:
            from .application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                if application.postEvent(self, QEvent(QEvent.DeferredDelete)):
                    return
        except Exception:
            pass
        try:
            self._after(0, self._delete_later)
        except Exception:
            self._delete_later_pending = False
            raise

    def _delete_later(self):
        self._delete_later_pending = False
        if not self._deleted:
            self.delete()

    def delete(self):
        if self._deleted:
            return
        application = None
        owns_delete_transaction = False
        # Qt removes posted events/native state for an ownership subtree as the
        # tree dies. Let QApplication do that once for the recursive delete
        # transaction instead of rescanning its queues for every child object.
        try:
            from .application import QApplication
            application = QApplication.instance()
            if (application is not None and application is not self
                    and application.threadId() == self.threadId()):
                owns_delete_transaction = application._begin_object_tree_delete(self)
        except Exception:
            application = None
            owns_delete_transaction = False
        try:
            self._deleted = True
            for target in tuple(self._filter_targets):
                target.removeEventFilter(self)
            self._filter_targets.clear()
            for filter_object in tuple(self._event_filters):
                filter_object._filter_targets.discard(self)
            self._event_filters.clear()
            for connection in tuple(self._connections):
                connection.disconnect()
            error = None
            for child in tuple(self._children):
                try:
                    child.delete()
                except Exception as exc:
                    if error is None:
                        error = exc
            self._children.clear()
            if self.parent is not None:
                previous = self.parent
                try:
                    previous._children.remove(self)
                except ValueError:
                    pass
                self.parent = None
                if not previous._deleted:
                    previous.sendEvent(QChildEvent(QEvent.ChildRemoved, self))
            try:
                self.destroyed.emit(self)
            except Exception as exc:
                if error is None:
                    error = exc
            finally:
                for value in vars(self).values():
                    if isinstance(value, Signal):
                        value.disconnect()
            if error is not None:
                raise error
        finally:
            if owns_delete_transaction and application is not None:
                application._end_object_tree_delete(self)


class QMetaObject:
    """Small Qt-style meta-object helper for queued invocation and auto-connect."""

    @staticmethod
    def invokeMethod(receiver, method, connection_type=Qt.AutoConnection, *args, **kwargs):
        if not isinstance(receiver, QObject) or receiver._deleted:
            return False
        callback = getattr(receiver, method, None) if isinstance(method, str) else method
        if not callable(callback):
            return False
        if connection_type not in (Qt.AutoConnection, Qt.DirectConnection, Qt.QueuedConnection):
            raise ValueError("unknown Qt connection type")
        direct = connection_type == Qt.DirectConnection
        if connection_type == Qt.AutoConnection:
            direct = threading.get_ident() == receiver.threadId()
        if direct:
            callback(*args, **kwargs)
            return True
        scheduler = getattr(receiver, "_after", None)
        if scheduler is None:
            raise RuntimeError("queued invocation requires a receiver scheduler")
        guard = QPointer(receiver)

        def deliver():
            target = guard.data()
            if target is None:
                return
            current = getattr(target, method, None) if isinstance(method, str) else callback
            if callable(current):
                current(*args, **kwargs)

        scheduler(0, deliver)
        return True

    @staticmethod
    def connectSlotsByName(obj):
        """Connect ``on_<objectName>_<signal>`` methods across an QObject tree."""
        if not isinstance(obj, QObject) or obj._deleted:
            return 0
        count = 0
        for child in [obj] + obj.findChildren(QObject):
            name = child.objectName()
            if not name:
                continue
            for signal_name, signal in vars(child).items():
                if not isinstance(signal, Signal):
                    continue
                slot = getattr(obj, "on_{}_{}".format(name, signal_name), None)
                if callable(slot):
                    before = len(signal._slots)
                    signal.connect(slot, receiver=obj)
                    if len(signal._slots) > before:
                        count += 1
        return count


class QPointer:
    """Guarded weak reference to a QObject, mirroring QtCore.QPointer.

    The pointer never owns the target. ``data()`` becomes ``None`` as soon as
    the QObject is deleted, which makes delayed callbacks safer without adding
    one worker-specific lifetime flag per dialog/control.
    """

    def __init__(self, obj=None):
        self._ref = None
        self.assign(obj)

    def assign(self, obj):
        if obj is not None and not isinstance(obj, QObject):
            raise TypeError("QPointer can only guard QObject instances")
        self._ref = None if obj is None else weakref.ref(obj)
        return self

    def clear(self):
        self._ref = None

    def data(self):
        obj = None if self._ref is None else self._ref()
        if obj is None or getattr(obj, "_deleted", False):
            return None
        return obj

    def isNull(self):
        return self.data() is None

    def __bool__(self):
        return self.data() is not None

    def __call__(self):
        return self.data()

    def __getattr__(self, name):
        obj = self.data()
        if obj is None:
            raise ReferenceError("QPointer target has been deleted")
        return getattr(obj, name)

    def __eq__(self, other):
        if isinstance(other, QPointer):
            return self.data() is other.data()
        return self.data() is other


class QSignalBlocker:
    """Temporarily suppress change signals while synchronizing form state."""
    def __init__(self, obj):
        self.obj = obj
        self._active = False

    def __enter__(self):
        self.previous = self.obj.blockSignals(True)
        self._active = True
        return self

    def unblock(self):
        if self.obj is not None and self._active:
            self.obj.blockSignals(self.previous)
            self._active = False

    def reblock(self):
        if self.obj is not None and hasattr(self, "previous"):
            self.obj.blockSignals(True)
            self._active = True

    def dismiss(self):
        self.obj = None
        self._active = False

    def __exit__(self, *_args):
        if self.obj is not None and self._active:
            self.obj.blockSignals(self.previous)
        self._active = False


__all__ = ["Qt", "QPoint", "QPointF", "QSize", "QRect", "QMargins", "QSizePolicy", "QEvent", "QCloseEvent", "QKeyEvent", "QMouseEvent", "QChildEvent", "QObject", "QMetaObject", "QPointer", "Signal", "SignalConnection", "QSignalBlocker"]
