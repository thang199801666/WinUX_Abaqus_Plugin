"""Preview rendering and progressive XY reduction for Reference Chart."""
from __future__ import annotations

import math
import re

from ...services.reference_charts import (
    make_formula_reference, evaluate_reference_formula, reduce_reference_samples)
from ...services.plot_palettes import palette_colors


class ReferencePreviewMixin:
    def _clear_preview(self, message='Refresh to preview edits'):
        for series in self._preview_series:
            series.delete()
        self._preview_series.clear()
        self._preview_message.setText(message)

    def _refresh_preview(self):
        if self._finished:
            return False
        self._clear_preview()
        try:
            if self._formula_mode:
                formula = str(self.control_value(self.formula_edit, '') or '')
                make_formula_reference(formula, name='Preview', explicit_regex=True)
                sources = (self._preview_history_provider() if callable(self._preview_history_provider)
                           else self._history_outputs)
                if not any(row.get('points') for row in sources):
                    self._preview_message.setText('No Plot data available for Formula preview.')
                    return False
                curves = evaluate_reference_formula(formula, sources)
            else:
                curves = self.data_table.to_series('Preview')
            return self._render_preview(curves)
        except (TypeError, ValueError, OverflowError, re.error) as exc:
            self._clear_preview(str(exc))
            return False

    def _reset_reduction_state(self):
        self._reduction_source_points = None
        self._reduction_applied_preset = None
        self._reduction_effective_tolerance = None
        self._reduction_pass_count = 0

    def _reduction_preset_index(self, preset):
        names = [name for name, _ratio in self.REDUCTION_PRESETS]
        try:
            return names.index(str(preset))
        except ValueError:
            return names.index(self.DEFAULT_REDUCTION_PRESET)

    def _advance_reduction_preset(self, preset):
        """Select the next fidelity level after the current one is exhausted."""
        index = self._reduction_preset_index(preset)
        if index + 1 >= len(self.REDUCTION_PRESETS):
            return None
        next_name = self.REDUCTION_PRESETS[index + 1][0]
        self.set_control_value(self.reduce_accuracy_combo, next_name)
        return next_name

    def _reduce_xy_samples(self, *_args):
        """Progressively reduce XY samples while bounding error to the source.

        The selected preset is the *starting* geometric tolerance.  Repeated
        clicks are intentionally useful: if that tolerance already produced
        the current worksheet, the next pass searches upward for the smallest
        source-relative tolerance that removes about 20% of the remaining
        samples.  Every candidate is simplified directly from the original
        snapshot, so approximation error never compounds pass-to-pass.
        """
        if self._finished or self._formula_mode:
            return False
        try:
            preset = str(self.control_value(
                self.reduce_accuracy_combo, self.DEFAULT_REDUCTION_PRESET)
                or self.DEFAULT_REDUCTION_PRESET)
            preset_map = dict(self.REDUCTION_PRESETS)
            if preset not in preset_map:
                preset = self.DEFAULT_REDUCTION_PRESET
                self.set_control_value(self.reduce_accuracy_combo, preset)
            base_tolerance = float(preset_map[preset])

            current_points = self.data_table.to_points()
            current_count = len(current_points)
            if current_count <= 2:
                self.set_control_value(
                    self.status,
                    "Reduce Samples: the curve already has only {} point(s).".format(current_count))
                return False

            if self._reduction_source_points is None:
                self._reduction_source_points = [list(point) for point in current_points]
                self._reduction_effective_tolerance = None
                self._reduction_pass_count = 0
            source_points = self._reduction_source_points
            source_count = len(source_points)

            # Exact is genuinely lossless.  Once all duplicate/collinear
            # samples are gone there is no mathematically valid second Exact
            # reduction, so continue automatically at Ultra instead of making
            # the button dead-end.
            working_preset = preset
            working_base = base_tolerance
            previous_tolerance = self._reduction_effective_tolerance
            if working_base == 0.0:
                exact = reduce_reference_samples(source_points, 0.0)
                if len(exact) < current_count:
                    reduced = exact
                    effective_tolerance = 0.0
                else:
                    working_preset = self.REDUCTION_PRESETS[1][0]
                    working_base = float(self.REDUCTION_PRESETS[1][1])
                    self.set_control_value(self.reduce_accuracy_combo, working_preset)
                    previous_tolerance = None
                    reduced = None
                    effective_tolerance = None
            else:
                reduced = None
                effective_tolerance = None

            if reduced is None:
                # The first pass honors the selected preset exactly. Every
                # later click is deliberately meaningful: target about 20%
                # fewer remaining samples, then find the smallest tolerance
                # (measured against the original source) that reaches it.
                # Do not accept a one-point improvement just because the
                # previous tolerance happens to remove one extra sample.
                last_tolerance = (float(previous_tolerance)
                                  if previous_tolerance is not None else 0.0)
                low = max(float(working_base), last_tolerance)
                candidate = reduce_reference_samples(source_points, low)
                repeated_pass = int(getattr(self, '_reduction_pass_count', 0) or 0) > 0

                if not repeated_pass and len(candidate) < current_count:
                    reduced = candidate
                    effective_tolerance = low
                else:
                    # Repeated reduction should visibly reduce the worksheet,
                    # not trickle down by one or two points. A 20% target gives
                    # staged control (100% -> 80% -> 64% -> 51%...) while every
                    # pass retains a source-relative geometric error bound.
                    target_count = max(2, int(math.floor(current_count * 0.80)))
                    target_count = min(target_count, current_count - 1)

                    if len(candidate) <= target_count:
                        # A stronger preset selected between clicks may already
                        # satisfy the next target. Honor it directly.
                        reduced = candidate
                        effective_tolerance = low
                    else:
                        # Search strictly above the previous bound. Exponential
                        # search finds a bracket; binary search minimizes the
                        # extra source-relative deviation needed for the target.
                        step = max(float(working_base) * 0.25, low * 0.25, 1.0e-8)
                        upper = low + step
                        upper_result = None
                        max_tolerance = 1.0
                        for _attempt in range(18):
                            upper = min(max_tolerance, upper)
                            trial = reduce_reference_samples(source_points, upper)
                            if len(trial) <= target_count:
                                upper_result = trial
                                break
                            if upper >= max_tolerance:
                                break
                            upper = min(max_tolerance, max(upper * 1.6, upper + step))

                        if upper_result is None:
                            terminal = reduce_reference_samples(source_points, max_tolerance)
                            if len(terminal) >= current_count:
                                self.set_control_value(
                                    self.status,
                                    "Reduce Samples: no further points can be removed without collapsing the curve.")
                                return False
                            upper = max_tolerance
                            upper_result = terminal
                            target_count = len(terminal)

                        best_tolerance = upper
                        best_result = upper_result
                        left = low
                        right = upper
                        for _attempt in range(12):
                            middle = (left + right) * 0.5
                            trial = reduce_reference_samples(source_points, middle)
                            if len(trial) <= target_count:
                                best_tolerance = middle
                                best_result = trial
                                right = middle
                            else:
                                left = middle
                        reduced = best_result
                        effective_tolerance = best_tolerance

            reduced_count = len(reduced)
            if reduced_count >= current_count:
                self.set_control_value(
                    self.status,
                    "Reduce Samples: no further points can be removed at the current fidelity.")
                return False

            self.data_table.load_series([{"points": reduced}])
            self._sync_xy_summary(len(reduced))
            self._editor_dirty = True
            self._reduction_applied_preset = working_preset
            self._reduction_effective_tolerance = float(effective_tolerance)
            self._reduction_pass_count = int(getattr(self, '_reduction_pass_count', 0) or 0) + 1
            self._render_preview([{"name": "Preview", "points": reduced}])

            removed_now = current_count - reduced_count
            removed_total = source_count - reduced_count
            reduction_now = 100.0 * removed_now / float(current_count)
            reduction_total = 100.0 * removed_total / float(source_count)
            if effective_tolerance == 0:
                accuracy = "0% geometric error"
            else:
                accuracy = "effective source deviation <= {:.4g}%".format(
                    effective_tolerance * 100.0)
            self.set_control_value(
                self.status,
                "Reduce pass {}: {:,} -> {:,} points ({:.1f}% fewer); "
                "source {:,} -> {:,} ({:.1f}% total, {}). Click again to reduce further or Save to persist.".format(
                    self._reduction_pass_count, current_count, reduced_count, reduction_now,
                    source_count, reduced_count, reduction_total, accuracy))
            return True
        except (TypeError, ValueError, OverflowError) as exc:
            self.set_control_value(self.status, "Reduce Samples: {}".format(exc))
            return False

    def _fit_preview(self):
        if self._finished or not self._preview_series:
            return
        for axis in (self._preview_x_axis, self._preview_y_axis):
            # Release fixed ranges before fitting after a zoom/pan or a
            # programmatic range change; fit_axis_data alone keeps them locked.
            axis.backend.set_axis_limits_auto(axis.tag)
            axis.fitData()

    def _render_preview(self, curves):
        """Render borrowed XY arrays with bounded native allocation."""
        self._clear_preview()
        colors = palette_colors('tableau')
        point_count = 0
        for index, curve in enumerate(curves):
            points = curve.get('points') or []
            if not points:
                continue
            point_count += len(points)
            stride = max(1, (len(points) + 1998) // 1999)
            sampled = points[::stride]
            if len(points) > 1 and (len(points) - 1) % stride:
                sampled = list(sampled) + [points[-1]]
            self._preview_series.append(self._preview_plot.addLineSeries(
                [point[0] for point in sampled], [point[1] for point in sampled],
                axis=self._preview_y_axis, color=colors[index % len(colors)],
                marker='circle' if len(points) == 1 else 'none'))
        if not self._preview_series:
            self._preview_message.setText('No matching curves to preview.')
            return False
        self._fit_preview()
        self._preview_message.setText('{} {} | {:,} points'.format(
            len(self._preview_series), 'curve' if len(self._preview_series) == 1 else 'curves', point_count))
        return True
