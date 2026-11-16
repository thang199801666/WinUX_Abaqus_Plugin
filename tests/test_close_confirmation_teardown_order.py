from WinUx.dialogs.blocking_form import BlockingDialog


class _View:
    def __init__(self):
        self.queue = []

    def after(self, delay, callback, *args):
        self.queue.append(("after", delay, callback, args))
        return len(self.queue)

    def after_render(self, callback, *args):
        self.queue.append(("after_render", callback, args))
        return len(self.queue)


class _Loop:
    def isRunning(self):
        return False


def test_confirm_result_is_not_delivered_until_after_dialog_destroy_is_requested():
    events = []
    view = _View()
    dialog = BlockingDialog.__new__(BlockingDialog)
    dialog.result = {"done": False, "value": None}
    dialog._wait_loop = _Loop()
    dialog.view = view
    dialog.on_result = lambda value: events.append(("callback", value))
    dialog.destroy = lambda: events.append(("destroy", None))

    dialog.finish(True)

    assert dialog.result == {"done": True, "value": True}
    assert events == [("destroy", None)]
    assert len(view.queue) == 1
    kind, callback, args = view.queue.pop(0)
    assert kind == "after_render"
    callback(*args)
    assert events == [("destroy", None), ("callback", True)]


def test_cancel_result_uses_same_close_before_callback_contract():
    events = []
    view = _View()
    dialog = BlockingDialog.__new__(BlockingDialog)
    dialog.result = {"done": False, "value": None}
    dialog._wait_loop = None
    dialog.view = view
    dialog.on_result = lambda value: events.append(("callback", value))
    dialog.destroy = lambda: events.append(("destroy", None))

    dialog.finish(False)

    assert events == [("destroy", None)]
    kind, callback, args = view.queue.pop(0)
    assert kind == "after_render"
    callback(*args)
    assert events == [("destroy", None), ("callback", False)]
