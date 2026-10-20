from DearUIQt.runtime import QGuiRuntime


class FakeBackend:
    def __init__(self):
        self.events = []
        self.running = False
        self.callbacks = [("cb", 1)]

    def create_context(self):
        self.events.append(("create_context",))

    def configure_app(self, **kwargs):
        self.events.append(("configure_app", kwargs))

    def create_viewport(self, **kwargs):
        self.events.append(("create_viewport", kwargs))

    def setup_dearpygui(self):
        self.events.append(("setup",))

    def set_primary_window(self, tag, primary):
        self.events.append(("primary", tag, primary))

    def set_exit_callback(self, callback):
        self.events.append(("exit", callback))

    def set_viewport_resize_callback(self, callback):
        self.events.append(("resize", callback))

    def show_viewport(self):
        self.running = True
        self.events.append(("show",))

    def is_dearpygui_running(self):
        return self.running

    def render_dearpygui_frame(self):
        self.events.append(("render",))

    def stop_dearpygui(self):
        self.running = False
        self.events.append(("stop",))

    def get_callback_queue(self):
        return self.callbacks

    def destroy_context(self):
        self.running = False
        self.events.append(("destroy",))


def test_qgui_runtime_owns_renderer_context_viewport_and_frame_lifecycle():
    backend = FakeBackend()
    runtime = QGuiRuntime(backend)
    assert runtime.createContext(manual_callbacks=True)
    assert not runtime.createContext()
    assert runtime.contextCreated()
    assert ("configure_app", {"manual_callback_management": True}) in backend.events

    assert runtime.createViewport(title="WinUX", width=800, height=600)
    assert runtime.viewportCreated()
    assert runtime.setup()
    runtime.setPrimaryWindow("root")
    runtime.setExitCallback("exit_cb")
    runtime.setViewportResizeCallback("resize_cb")
    assert runtime.show()
    assert runtime.isRunning()
    assert runtime.renderFrame()
    assert runtime.callbackQueue() == tuple(backend.callbacks)

    assert runtime.stop()
    assert not runtime.isRunning()
    assert runtime.destroy()
    assert not runtime.contextCreated()
    assert not runtime.viewportCreated()
    assert ("destroy",) in backend.events
