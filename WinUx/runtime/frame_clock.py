"""Qt-like activity-driven frame pacing with no timer thread."""
import time


class AdaptiveFrameClock:
    ACTIVE_INTERVAL = 1.0 / 60.0
    DRAG_INTERVAL = 1.0 / 240.0
    TRANSFER_INTERVAL = 1.0 / 60.0
    WORK_INTERVAL = 1.0 / 30.0
    IDLE_INTERVAL = 0.5
    BACKGROUND_INTERVAL = 1.0
    INPUT_GRACE = 1.0
    WORK_GRACE = 0.2

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        now = clock()
        self.last_input = now
        self.last_work = float('-inf')
        self.last_frame = None

    def input(self, *_args):
        self.last_input = self.clock()

    def work(self):
        self.last_work = self.clock()

    def presented(self):
        self.last_frame = self.clock()

    def delay(self, *, foreground=True, minimized=False, urgent=False, dragging=False, transferring=False):
        if urgent or self.last_frame is None:
            return 0.0
        now = self.clock()
        if minimized:
            interval = self.BACKGROUND_INTERVAL
        elif dragging:
            interval = self.DRAG_INTERVAL
        elif now - self.last_input < self.INPUT_GRACE:
            interval = self.ACTIVE_INTERVAL
        elif transferring and foreground and now - self.last_work < self.WORK_GRACE:
            interval = self.TRANSFER_INTERVAL
        elif now - self.last_work < self.WORK_GRACE:
            interval = self.WORK_INTERVAL
        else:
            interval = self.IDLE_INTERVAL if foreground else self.BACKGROUND_INTERVAL
        return max(0.0, self.last_frame + interval - now)
