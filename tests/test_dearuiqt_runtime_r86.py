from DearUIQt.runtime import QGuiRuntime


class FakeBackend:
    def __init__(self):
        self.events = []
        self.width = 800
        self.height = 600
        self.client_width = 780
        self.client_height = 560

    def create_context(self):
        self.events.append(("context",))

    def configure_app(self, **kwargs):
        self.events.append(("app", kwargs))

    def create_viewport(self, **kwargs):
        self.events.append(("viewport", kwargs))

    def configure_viewport(self, viewport, **kwargs):
        self.events.append(("configure_viewport", viewport, kwargs))
        self.width = int(kwargs.get("width", self.width))
        self.height = int(kwargs.get("height", self.height))

    def get_viewport_width(self): return self.width
    def get_viewport_height(self): return self.height
    def get_viewport_client_width(self): return self.client_width
    def get_viewport_client_height(self): return self.client_height

    def set_viewport_width(self, value):
        self.width = int(value)
        self.events.append(("set_width", int(value)))

    def set_viewport_height(self, value):
        self.height = int(value)
        self.events.append(("set_height", int(value)))

    def is_dearpygui_running(self): return False
    def destroy_context(self): self.events.append(("destroy",))


def test_qgui_runtime_owns_viewport_queries_configuration_and_resize():
    backend = FakeBackend()
    runtime = QGuiRuntime(backend)
    runtime.createContext()
    runtime.createViewport(title="Host", width=800, height=600)

    size = runtime.viewportSize()
    client = runtime.viewportSize(client=True)
    assert (size.width(), size.height()) == (800, 600)
    assert (client.width(), client.height()) == (780, 560)

    assert runtime.configureViewport(vsync=True, width=900)
    assert ("configure_viewport", 0, {"vsync": True, "width": 900}) in backend.events
    assert runtime.resizeViewport(1024, 720)
    assert (runtime.viewportSize().width(), runtime.viewportSize().height()) == (1024, 720)
    assert runtime.setViewportHeight(700)
    assert runtime.viewportSize().height() == 700
