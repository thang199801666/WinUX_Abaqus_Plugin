"""One-shot UI-thread completion for asynchronous inline rename callbacks."""


class RenameResult:
    def __init__(self):
        self.done = False
        self.success = False
        self._callbacks = []

    def then(self, callback):
        if self.done:
            callback(self.success)
        else:
            self._callbacks.append(callback)

    def complete(self, success):
        if self.done:
            return
        self.done, self.success = True, bool(success)
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback(self.success)
