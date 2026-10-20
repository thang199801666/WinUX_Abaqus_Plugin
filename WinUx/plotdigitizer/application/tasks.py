"""Background application services with no Dear ImGui dependency."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace


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
        roi = (self.engine.plot_roi() if not auto_detect or self.engine.plot_rect or
               self.engine.calibration_ready() else None)
        self._pending = True
        self._future = self._submitter(
            self.engine.compute_smart_detect, settings, image=image, roi=roi,
            curve_rgb=source_dataset.curve_rgb)

        def completed(future):
            error = None
            result = None
            try:
                result = future.result()
            except Exception as exc:  # host gets a normalized result instead of worker exceptions
                error = str(exc)
            if not self._closed:
                def deliver():
                    self._pending = False
                    if self._closed:
                        return
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

    def close(self):
        was_busy = self._pending
        self._closed = True
        self._pending = False
        future = self._future
        if future is not None and hasattr(future, "cancel"):
            try:
                future.cancel()
            except Exception:
                pass
        return not was_busy
