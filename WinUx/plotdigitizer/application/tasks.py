"""Background application services with no Dear ImGui dependency."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock

from ..core.tick_detection import detect_calibration_ticks


# Standalone/application callers still get a reusable executor without importing
# WinUx UI.  The WinUx dialog injects ``QtConcurrent.run`` so smart detection
# shares the host's QThreadPool instead of creating a worker pool per form.
_SHARED_SMART_DETECT_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="plot-digitizer-shared")


class SmartDetectRunner:
    """Serialize expensive smart-detect work and dispatch results to the host thread."""

    def __init__(self, engine, dispatcher, max_workers=1, submitter=None):
        self.engine = engine
        self.dispatcher = dispatcher
        self._submitter = submitter or _SHARED_SMART_DETECT_EXECUTOR.submit
        self._future = None
        self._closed = False
        self._pending = False
        self._generation = 0
        self._cancel_event = None

    @property
    def busy(self):
        return self._pending

    def submit(self, settings, dataset_index, on_done, *, auto_detect=True):
        if self._closed or self.busy:
            return False
        image = self.engine.image.copy() if self.engine.image is not None else None
        source_image = self.engine.image
        source_dataset = self.engine.datasets[dataset_index]
        source_revision = self.engine.revision
        settings = replace(settings)
        self._generation += 1
        generation = self._generation
        cancel_event = self._cancel_event = Event()
        roi = (self.engine.plot_roi() if not auto_detect or self.engine.plot_rect or
               self.engine.calibration_ready() else None)
        self._pending = True
        try:
            self._future = self._submitter(
                self.engine.compute_smart_detect, settings, image=image, roi=roi,
                curve_rgb=source_dataset.curve_rgb, cancelled=cancel_event.is_set)
        except Exception:
            self._pending = False
            cancel_event.set()
            raise

        def completed(future):
            error = None
            result = None
            try:
                result = future.result()
            except Exception as exc:  # host gets a normalized result instead of worker exceptions
                error = str(exc)
            if not self._closed:
                def deliver():
                    if self._closed or generation != self._generation:
                        return
                    self._pending = False
                    index = next((i for i, ds in enumerate(self.engine.datasets)
                                  if ds is source_dataset), None)
                    if (self.engine.image is not source_image or index is None or
                            self.engine.revision != source_revision):
                        on_done(None, settings, dataset_index,
                                "Image, calibration or dataset changed; extract again.")
                        return
                    on_done(result, settings, index, error)
                self.dispatcher(deliver)

        self._future.add_done_callback(completed)
        return True

    def cancel(self):
        was_busy = self._pending
        self._pending = False
        self._generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        future = self._future
        if future is not None and hasattr(future, "cancel"):
            try:
                future.cancel()
            except Exception:
                pass
        return was_busy

    def close(self):
        self._closed = True
        return not self.cancel()


class TickCalibrationRunner:
    """Run Box tick/OCR calibration away from the UI thread.

    Unlike curve extraction, Box calibration is replaceable: drawing a newer
    Box supersedes an older request.  Late worker results are ignored and the
    active result is delivered only if the image/box/calibration scale still
    match the state from which it was computed.
    """

    def __init__(self, engine, dispatcher, submitter=None):
        self.engine = engine
        self.dispatcher = dispatcher
        self._submitter = submitter or _SHARED_SMART_DETECT_EXECUTOR.submit
        self._future = None
        self._closed = False
        self._pending = False
        self._generation = 0
        self._cancel_event = None

    @property
    def busy(self):
        return self._pending

    def submit(self, rect, on_done, *, on_progress=None, on_region=None, align_axes=None):
        if self._closed or self.engine.image is None or rect is None:
            return False
        self._generation += 1
        generation = self._generation
        if self._cancel_event is not None:
            self._cancel_event.set()
        cancel_event = self._cancel_event = Event()
        previous = self._future
        if previous is not None and hasattr(previous, "cancel"):
            try:
                previous.cancel()
            except Exception:
                pass

        # Tick detector is read-only; avoid duplicating a potentially large
        # screenshot every time the user redraws a Box.
        image = self.engine.image
        source_image = image
        source_revision = self.engine.revision
        rect = tuple(int(round(value)) for value in rect)
        scale_x = self.engine.calibration.scale_x
        scale_y = self.engine.calibration.scale_y
        snap_to_axes = self.engine.calibration.snap_to_axes
        align_axes = snap_to_axes if align_axes is None else bool(align_axes)
        self._pending = True

        def cancelled():
            # Running futures cannot be stopped with Future.cancel(). Let the
            # detector abandon old work between words instead of consuming a
            # worker until both axes and all fallback passes have completed.
            return (cancel_event.is_set() or self.engine.image is not source_image or
                    self.engine.revision != source_revision or
                    self.engine.plot_rect is None or tuple(self.engine.plot_rect) != rect or
                    self.engine.calibration.scale_x != scale_x or
                    self.engine.calibration.scale_y != scale_y or
                    self.engine.calibration.snap_to_axes != snap_to_axes)

        # Keep at most one queued UI update, even if OCR reports many words
        # before the next frame. Neither the worker nor stale jobs touch widgets.
        progress_lock = Lock()
        progress_state = [None, False]

        def deliver_progress():
            with progress_lock:
                latest, progress_state[1] = progress_state[0], False
            if (latest is not None and not self._closed and self._pending and
                    generation == self._generation and not cancelled()):
                on_progress(*latest)

        def report(value, message):
            if self._closed or cancelled():
                return
            with progress_lock:
                progress_state[0] = (value, message)
                if progress_state[1]:
                    return
                progress_state[1] = True
            self.dispatcher(deliver_progress)

        options = {'cancelled': cancelled, 'align_axes': align_axes}
        if on_region is not None:
            def report_region(aligned):
                def deliver_region():
                    if (not self._closed and self._pending and generation == self._generation and
                            not cancelled()):
                        on_region(aligned)
                self.dispatcher(deliver_region)
            options['region_aligned'] = report_region
        if on_progress is not None:
            options['progress'] = report
        try:
            self._future = self._submitter(
                detect_calibration_ticks, image, rect, scale_x, scale_y, **options)
        except Exception:
            self._pending = False
            cancel_event.set()
            raise

        def completed(future):
            error = None
            result = None
            try:
                result = future.result()
            except Exception as exc:
                error = str(exc)
            if self._closed:
                return

            def deliver():
                if self._closed or generation != self._generation:
                    return
                self._pending = False
                current_rect = tuple(self.engine.plot_rect) if self.engine.plot_rect is not None else None
                if (self.engine.image is not source_image or current_rect != rect or
                        self.engine.revision != source_revision or
                        self.engine.calibration.scale_x != scale_x or
                        self.engine.calibration.scale_y != scale_y or
                        self.engine.calibration.snap_to_axes != snap_to_axes):
                    on_done(None, rect, "Plot area or calibration changed; tick detection was discarded.")
                    return
                on_done(result, rect, error)

            self.dispatcher(deliver)

        self._future.add_done_callback(completed)
        return True

    def cancel(self):
        was_busy = self._pending
        self._pending = False
        self._generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        future = self._future
        if future is not None and hasattr(future, "cancel"):
            try:
                future.cancel()
            except Exception:
                pass
        return was_busy

    def close(self):
        self._closed = True
        return not self.cancel()
