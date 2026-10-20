"""Check folder row swaps for transient origin text and needless recreation."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
import dearpygui.dearpygui as backend
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.ui.components.explorer_list_view import ExplorerListView
from WinUx.ui.components.explorer_list_model import ListViewItem


def main():
    baseline = "--baseline" in sys.argv
    backend.create_context()
    backend.configure_app(manual_callback_management=True)
    try:
        NativeWindowBackend(backend).enable()
        host = StandaloneUiHost(backend)
        configure_ui_context(host)
        backend.create_viewport(title="Folder presentation check", width=800, height=500)
        with backend.window(tag="folder_presentation_root"):
            view = ExplorerListView("folder_presentation_root", width=740, height=400)
        backend.setup_dearpygui()
        backend.show_viewport()

        def frames():
            for _ in range(4):
                host.pump()
                backend.render_dearpygui_frame()
                backend.run_callbacks(backend.get_callback_queue())

        frames()
        texts, invalid, cases = {}, [], []
        draw_text, configure = backend.draw_text, backend.configure_item

        def inspect(tag):
            state = texts[tag]
            if state["show"] and state["text"] and tuple(state["pos"]) == (0, 0):
                invalid.append(tag)

        def tracked_draw(pos, text, **kwargs):
            tag = draw_text(pos, text, **kwargs)
            if kwargs.get("parent") == view.body_canvas:
                texts[tag] = {"pos": pos, "text": text, "show": kwargs.get("show", True)}
                inspect(tag)
            return tag

        def tracked_configure(tag, **kwargs):
            if tag in texts:
                texts[tag].update({key: kwargs[key] for key in ("pos", "text", "show") if key in kwargs})
                inspect(tag)
            return configure(tag, **kwargs)

        with patch.object(backend, "draw_text", tracked_draw), \
                patch.object(backend, "configure_item", tracked_configure):
            previous = []
            for folder, count in (("a", 400), ("b", 400), ("c", 550), ("d", 120), ("empty", 0)):
                items = [ListViewItem("{}-{:04d}.txt".format(folder, i),
                                     "C:/{}/{}.txt".format(folder, i)) for i in range(count)]
                start = time.perf_counter()
                view.set_items(items)
                elapsed = (time.perf_counter() - start) * 1000
                current = [row["texts"]["name"] for row in view._row_items]
                common = min(len(previous), len(current))
                reused = sum(previous[i] == current[i] for i in range(common))
                cases.append({"folder": folder, "rows": count, "ms": round(elapsed, 2),
                              "reused": reused, "reusable": common})
                if not baseline:
                    assert reused == common, cases[-1]
                    assert not invalid, "Nonempty text was exposed at the canvas origin"
                for row in view._row_items:
                    for tag in row["texts"].values():
                        assert backend.get_item_configuration(tag)["show"]
                frames()
                previous = current
        print(json.dumps({"cases": cases, "origin_text_exposures": len(invalid)}))
        if not baseline:
            print("FOLDER_ROW_PRESENTATION_OK")
    finally:
        backend.destroy_context()


if __name__ == "__main__":
    main()
