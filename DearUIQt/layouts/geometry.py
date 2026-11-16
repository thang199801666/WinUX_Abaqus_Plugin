"""Pure Qt-style layout geometry negotiation helpers.

This module contains no renderer calls and owns no widgets.  Retained layout
containers use it to answer dependent size queries before the backend performs
final native placement.
"""
from ..core.object import Qt, QSize, QSizePolicy


def _layout_hint(child, minimum=False):
    """Return a child's participating hint using Qt hidden/size-policy rules."""
    hidden = getattr(child, "isHidden", lambda: False)()
    policy = getattr(child, "sizePolicy", lambda: None)()
    retain_hidden = bool(policy is not None and policy.retainSizeWhenHidden())
    if hidden and not retain_hidden:
        return None
    callback = child.minimumSizeHint if minimum else child.sizeHint
    hint = callback()
    if not isinstance(hint, QSize) or not hint.isValid():
        return QSize(0, 0)
    if policy is not None:
        try:
            width, height = hint.width(), hint.height()
            if policy.horizontalPolicy() == QSizePolicy.Ignored:
                width = 0
            if policy.verticalPolicy() == QSizePolicy.Ignored:
                height = 0
            hint = QSize(width, height)
        except Exception:
            pass
    return hint


def _axis_value(size, horizontal):
    return size.width() if horizontal else size.height()


def _axis_policy(policy, horizontal):
    return policy.horizontalPolicy() if horizontal else policy.verticalPolicy()


def _axis_stretch(policy, horizontal):
    return policy.horizontalStretch() if horizontal else policy.verticalStretch()


def _axis_maximum(child, horizontal):
    callback = getattr(child, "maximumSize", None)
    maximum = callback() if callable(callback) else QSize(16777215, 16777215)
    if not isinstance(maximum, QSize) or not maximum.isValid():
        return 16777215
    return max(0, _axis_value(maximum, horizontal))


def _axis_metrics(child, horizontal, minimum=False):
    """Return base/min/max/grow/shrink metadata for one layout axis.

    This intentionally models the Qt size-policy contract rather than native
    Dear ImGui placement.  The result is used by height-for-width and
    width-for-height queries, so nested layouts can make deterministic sizing
    decisions before the renderer performs its final placement pass.
    """
    hint = _layout_hint(child, minimum)
    if hint is None:
        return None
    minimum_hint = _layout_hint(child, True) or QSize(0, 0)
    policy = getattr(child, "sizePolicy", lambda: QSizePolicy())()
    base = max(0, _axis_value(hint, horizontal))
    low = max(0, _axis_value(minimum_hint, horizontal))
    high = max(low, _axis_maximum(child, horizontal))
    kind = _axis_policy(policy, horizontal)
    if kind == QSizePolicy.Fixed:
        low = high = min(high, max(low, base))
    elif kind == QSizePolicy.Minimum:
        low = max(low, base)
    elif kind == QSizePolicy.Maximum:
        high = min(high, max(low, base))
    base = min(high, max(low, base))
    stretch = max(0, int(_axis_stretch(policy, horizontal)))
    grow = bool(kind & QSizePolicy.GrowFlag)
    shrink = bool(kind & QSizePolicy.ShrinkFlag)
    return [base, low, high, stretch, grow, shrink]


def _solve_metric_lengths(metrics, total):
    """Solve already-normalized ``[base, min, max, stretch, grow, shrink]`` rows."""
    if not metrics:
        return []
    target = max(0, int(total))
    values = [item[0] for item in metrics]
    current = sum(values)
    if current < target:
        remaining = target - current
        explicit = any(item[3] > 0 for item in metrics)
        for _ in range(len(metrics) + 2):
            active = []
            for index, item in enumerate(metrics):
                capacity = item[2] - values[index]
                weight = item[3] if explicit else (1 if item[4] else 0)
                if capacity > 0 and weight > 0:
                    active.append((index, capacity, weight))
            if not active or remaining <= 0:
                break
            total_weight = sum(item[2] for item in active)
            progressed = 0
            for index, capacity, weight in active:
                share = max(1, round(remaining * weight / total_weight))
                delta = min(capacity, share, remaining - progressed)
                if delta <= 0:
                    continue
                values[index] += delta
                progressed += delta
                if progressed >= remaining:
                    break
            if progressed <= 0:
                break
            remaining -= progressed
    elif current > target:
        remaining = current - target
        for _ in range(len(metrics) + 2):
            active = [(index, values[index] - item[1])
                      for index, item in enumerate(metrics)
                      if item[5] and values[index] > item[1]]
            if not active or remaining <= 0:
                break
            progressed = 0
            share = max(1, remaining // len(active))
            for index, capacity in active:
                delta = min(capacity, share, remaining - progressed)
                if delta <= 0:
                    continue
                values[index] -= delta
                progressed += delta
                if progressed >= remaining:
                    break
            if progressed <= 0:
                break
            remaining -= progressed
    return values


def _solve_axis_lengths(children, total, horizontal, minimum=False):
    """Allocate one main-axis extent using Qt-like policy/stretches.

    Exact native placement remains backend-owned; this solver exists for
    dependent geometry queries and nested layout size negotiation.
    """
    metrics = [_axis_metrics(child, horizontal, minimum) for child in children]
    return _solve_metric_lengths([item for item in metrics if item is not None], total)


def _dependent_extent(child, extent, *, height_for_width, minimum=False):
    """Evaluate a child's dependent axis, clamped to its retained limits."""
    hint = _layout_hint(child, minimum)
    if hint is None:
        return 0
    if height_for_width:
        capable = getattr(child, "hasHeightForWidth", None)
        callback = getattr(child, "heightForWidth", None)
        fallback = hint.height()
        minimum_value = _axis_value(_layout_hint(child, True) or QSize(0, 0), False)
        maximum = _axis_maximum(child, False)
    else:
        capable = getattr(child, "hasWidthForHeight", None)
        callback = getattr(child, "widthForHeight", None)
        fallback = hint.width()
        minimum_value = _axis_value(_layout_hint(child, True) or QSize(0, 0), True)
        maximum = _axis_maximum(child, True)
    value = -1
    if callable(capable) and capable() and callable(callback):
        try:
            value = int(callback(max(0, int(extent))))
        except (TypeError, ValueError, OverflowError):
            value = -1
    if value < 0:
        value = fallback
    return min(maximum, max(minimum_value, int(value)))



def _baseline_row_extent(children, lengths, alignments=None, minimum=False):
    """Return a horizontal row height honoring explicit AlignBaseline items.

    Native placement remains backend-owned, but dependent geometry must reserve
    enough ascent/descent for mixed-font rows or a later renderer cannot align
    their baselines without clipping.
    """
    alignments = alignments or {}
    ordinary = []
    ascents = []
    descents = []
    for child, width in zip(children, lengths):
        height = _dependent_extent(child, width, height_for_width=True, minimum=minimum)
        alignment = int(alignments.get(child, 0) or 0)
        if not (alignment & Qt.AlignBaseline):
            ordinary.append(height)
            continue
        callback = getattr(child, "baselineOffset", None)
        baseline = -1
        if callable(callback):
            try:
                baseline = int(callback(width))
            except TypeError:
                try:
                    baseline = int(callback())
                except Exception:
                    baseline = -1
            except Exception:
                baseline = -1
        if baseline < 0 or baseline > height:
            ordinary.append(height)
            continue
        ascents.append(baseline)
        descents.append(max(0, height - baseline))
    baseline_height = (max(ascents) + max(descents)) if ascents else 0
    return max([baseline_height, *ordinary], default=0)


__all__ = [
    "_layout_hint", "_axis_metrics", "_solve_metric_lengths",
    "_solve_axis_lengths", "_dependent_extent", "_baseline_row_extent",
]
