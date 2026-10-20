"""Render watcher snapshots natively; assert retained rows, selection and scroll."""
from pathlib import Path, PurePosixPath
import argparse
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.explorer_item_model import stable_item_identity
from WinUx.runtime.dpg_callbacks import run_callback_jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()
    dpg.create_context()
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Watcher smooth refresh check", width=1000, height=650)
        with dpg.window(label="Files", width=980, height=610) as window:
            panel = FilePanel(window, "server" if args.server else "watch-check", {}, has_toolbar=False)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        def frames(count=3):
            for _ in range(count):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.005)

        directory = PurePosixPath("/work/remote-check") if args.server else Path("C:/watch-check")
        if args.server:
            from WinUx.view import WinUXView
            view_host = SimpleNamespace(right=panel)
            WinUXView.display_server_directory(view_host, directory, [], "test-host", reset_history=True)

        def refresh(rows):
            if args.server:
                return WinUXView.display_server_directory(view_host, directory, rows, "test-host", record_history=False)
            return panel.refresh_directory(directory, rows)
        def snapshot(tick=0, extra=False, removed=False):
            rows = [SimpleNamespace(name="model{:03}.sta".format(i),
                                    path=directory / "model{:03}.sta".format(i), is_dir=False,
                                    size=1024 + (tick * 1024 if i == 50 else 0),
                                    modified=1700000000 + i + (tick * 100 if i == 50 else 0))
                    for i in range(100) if not (removed and i == 20)]
            if extra:
                rows.append(SimpleNamespace(name="new.sta", path=directory / "new.sta",
                                            is_dir=False, size=9, modified=1700000500))
            return rows

        panel.display(directory, snapshot())
        frames(40)
        view = panel.listview
        view.select_indices([50])
        selected_path = view.items[50].path
        view._set_keyboard_focus(True)
        frames(30)
        dpg.set_y_scroll(view.body_window, 450)
        frames(10)
        scroll = dpg.get_y_scroll(view.body_window)
        assert scroll > 0, "Harness did not establish a scroll range"
        def tags():
            return {stable_item_identity(view.items[row["index"]]):
                    (row["background"], tuple(row["texts"].values()), row.get("icon"))
                    for row in view._row_items}
        initial = tags()
        pinned = view._pinned_item
        with patch.object(view, "_rebuild_draw_items", wraps=view._rebuild_draw_items) as rebuild, \
                patch.object(view, "_rebuild_body_rows", wraps=view._rebuild_body_rows) as body, \
                patch.object(panel, "restore_vertical_scroll", wraps=panel.restore_vertical_scroll) as restore:
            for tick in range(1, 21):
                assert refresh(snapshot(tick)) is None
                frames(1)
                assert tags() == initial, "Metadata update replaced draw primitives"
                assert abs(dpg.get_y_scroll(view.body_window) - scroll) < 1, (tick, scroll, dpg.get_y_scroll(view.body_window))
                assert {view.items[i].path for i in view.selected} == {selected_path}
            view.sort_key, view.sort_ascending = "date", False
            refresh(snapshot(21))
            frames()
            assert tags() == initial, "Date sort replaced rows"
            assert {view.items[i].path for i in view.selected} == {selected_path}
            refresh(snapshot(22, extra=True, removed=True))
            frames()
            updated = tags()
            for key in initial.keys() & updated.keys():
                assert updated[key] == initial[key], "Insert/delete replaced an unchanged row"
            assert abs(dpg.get_y_scroll(view.body_window) - scroll) < 1
            assert view._pinned_item is pinned
            with patch.object(view, "set_items", wraps=view.set_items) as set_items:
                refresh(snapshot(22, extra=True, removed=True))
                set_items.assert_not_called()
            panel._filter_query = "model050"
            refresh(snapshot(23, extra=True, removed=True))
            frames()
            assert [item.name for item in view.items] == ["model050.sta"]
            assert {view.items[i].path for i in view.selected} == {selected_path}
            if args.server:
                panel._filter_query = ""
                cases = [SimpleNamespace(name=name, path=directory / name, is_dir=False,
                                         size=size, modified=1700000700)
                         for name, size in (("A.inp", 1), ("a.inp", 2))]
                refresh(snapshot(24) + cases)
                frames()
                upper = next(item for item in view.items if item.name == "A.inp")
                lower = next(item for item in view.items if item.name == "a.inp")
                assert upper is not lower
                cases[0].size = 100
                refresh(snapshot(25) + cases)
                frames()
                assert next(item for item in view.items if item.name == "A.inp") is upper
                assert next(item for item in view.items if item.name == "a.inp") is lower
                assert (upper.size, lower.size) == (100, 2)
            rebuild.assert_not_called()
            body.assert_not_called()
            restore.assert_not_called()
        print("SMOOTH_REFRESH_OK", "server" if args.server else "local",
              "20 metadata updates, date reorder, insert/delete; stable row tags, selection and scroll")
    finally:
        dpg.destroy_context()


if __name__ == "__main__":
    main()
