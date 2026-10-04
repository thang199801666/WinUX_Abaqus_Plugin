"""Child-side DPG lifecycle: build, warm up invisibly, center, publish, run."""
from __future__ import annotations

import heapq
import itertools
import os
from pathlib import Path
import queue
import threading
import time

import dearpygui.dearpygui as dpg
from ..platform.floating_viewport import (
    NativeViewport, ViewportCreationGuard, centered_position, window_rect, work_area, cloaked,
)
from .floating_forms import create_form, deliver_command, client_layout
from .theme import DialogMetrics
from ..services.floating_protocol import read_messages, encode_message


PUBLISH_HANDSHAKE_TIMEOUT = 20.0


class ChildView:
    def __init__(self):
        self.queue = []
        self.sequence = itertools.count()

    def after(self, delay, callback, *args):
        heapq.heappush(self.queue, (time.monotonic() + max(0, delay)/1000,
                                   next(self.sequence), callback, args))

    def after_render(self, callback, *args):
        self.after(0, callback, *args)

    def drain(self):
        for _ in range(64):
            if not self.queue or self.queue[0][0] > time.monotonic():
                break
            _, _, callback, args = heapq.heappop(self.queue)
            callback(*args)


def configure_context(view):
    dpg.configure_app(manual_callback_management=True)
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
    if font_path.is_file():
        with dpg.font_registry():
            font = dpg.add_font(str(font_path), DialogMetrics.BODY_FONT_SIZE)
            heading_path = font_path.with_name("seguisb.ttf")
            if heading_path.is_file():
                view.heading_font = dpg.add_font(str(heading_path), DialogMetrics.HEADING_FONT_SIZE)
            terminal_path = font_path.with_name("consola.ttf")
            if terminal_path.is_file():
                view.terminal_font = dpg.add_font(str(terminal_path), DialogMetrics.BODY_FONT_SIZE)
        dpg.bind_font(font)


class PreparedViewport:
    """An idle, cloaked graphics context. It is claimed by exactly one dialog."""
    def __init__(self, connection, messages):
        self.connection, self.messages = connection, messages
        self.view = ChildView()
        self.incoming = queue.Queue(maxsize=64)
        self.native = None
        self.startup = []

    def wait_for_init(self):
        def reader():
            try:
                for message in self.messages:
                    self.incoming.put(message)
            except (OSError, ValueError):
                pass
            finally:
                self.incoming.put({"command": "close"})
        threading.Thread(target=reader, name="prepared-dialog-reader", daemon=True).start()
        dpg.create_context()
        configure_context(self.view)
        with dpg.window(label="", no_title_bar=True, no_move=True, no_resize=True) as self.blank:
            pass
        dpg.create_viewport(title="WinUx Dialog Worker", width=480, height=300, vsync=False)
        dpg.set_primary_window(self.blank, True)
        dpg.setup_dearpygui()
        with ViewportCreationGuard() as guard:
            dpg.show_viewport()
        self.startup.extend(guard.events)
        self.native = NativeViewport(guard.hwnd, True)
        self.native.configure(0)
        for _ in range(2):
            dpg.render_dearpygui_frame()
        # Stay cloaked and hidden while idle; do not register modality or pointer
        # ownership until the real dialog controller leases this context.
        self.native._show(False)
        self.connection.sendall(encode_message({"event": "warm_ready", "pid": os.getpid()}))
        while dpg.is_dearpygui_running():
            try:
                message = self.incoming.get(timeout=.05)
            except queue.Empty:
                dpg.render_dearpygui_frame()
                continue
            if message.get("command") == "init":
                return message
            if message.get("command") == "close":
                break
        dpg.destroy_context()
        return None


class FloatingDialogRuntime:
    def __init__(self, connection, messages, initial, prepared=None):
        self.connection, self.messages, self.initial = connection, messages, initial
        self.prepared = prepared
        self.view = prepared.view if prepared else ChildView()
        self.incoming = prepared.incoming if prepared else queue.Queue(maxsize=64)
        self.native = prepared.native if prepared else None
        self.form = None
        self.desired_visible = bool(initial.get("visible", True))
        self.owner_hwnd = int(initial.get("owner_hwnd") or 0)
        self._publish_requested = False
        self._commit_requested = False
        self.startup = list(prepared.startup) if prepared else []

    def emit(self, event, **values):
        self.connection.sendall(encode_message({"event": event, **values}))

    def _read_commands(self):
        try:
            for message in self.messages:
                self.incoming.put(message)
        except (OSError, ValueError):
            pass
        finally:
            self.incoming.put({"command": "close"})

    def _focus_form(self):
        focus = getattr(self.form, "_focus_initial", None) or getattr(self.form, "focus_input", None)
        if callable(focus):
            focus()

    def _render_settled_frame(self):
        """Run queued layout callbacks before rendering one invisible frame."""
        callbacks = dpg.get_callback_queue() or []
        if callbacks:
            dpg.run_callbacks(callbacks)
        self.view.drain()
        dpg.render_dearpygui_frame()

    def show(self):
        self.desired_visible = True
        self.native.set_visible(True)
        self.native.activate()
        self._focus_form()
        self.emit("visibility", visible=True)

    def hide(self):
        active = self.native.is_foreground()
        self.desired_visible = False
        # Framework-style close ordering: when this owned viewport is the
        # foreground window, transfer activation to its already-enabled owner
        # while the dialog is still visible.  The owned HWND stays visually
        # above the owner until SW_HIDE, eliminating the desktop/other-window
        # frame that appears when focus is repaired only after the hide.
        if active and self.owner_hwnd:
            self.native.handoff_to_owner(self.owner_hwnd)
        self.native.set_visible(False)
        self.emit("visibility", visible=False, return_focus=active)

    def _drain_commands(self, preparing=False):
        for _ in range(16):
            try:
                message = self.incoming.get_nowait()
            except queue.Empty:
                break
            command = message.get("command")
            if command == "close":
                self.form.destroy()
                return
            if command == "publish":
                self._publish_requested = True
            elif command == "publish_commit":
                self._commit_requested = True
            elif command in ("activate", "hide") and preparing:
                self.desired_visible = command == "activate"
            elif command == "activate":
                self.show()
            elif command == "hide":
                self.hide()
            else:
                deliver_command(self.form, command, message.get("args", []))

    def _wait_for_owner_handoff(self, timeout=.08):
        """Wait briefly for the parent to make the Win32 owner activatable.

        This is used only for child-driven closes (caption X/Escape/form
        self-destroy).  The native dialog remains visible while the parent
        balances its modal owner-disable reference.  Once acknowledged, SW_HIDE
        can hand foreground directly to the owner instead of briefly activating
        another desktop window.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            try:
                message = self.incoming.get(timeout=.005)
            except queue.Empty:
                continue
            command = str(message.get("command") or "")
            if command == "owner_handoff_ready":
                return True
            # The form is already closed and this process is exiting.  A second
            # close or stale UI command no longer has work to perform.
        return False

    def _wait_for_publish(self):
        """Wait until the parent has registered the HWND/owner relationship.

        The viewport stays cloaked and non-activating during this handshake, so
        a modal dialog never becomes visible before the main WinUx owner has
        been disabled.  This removes the owner/dialog activation bounce that
        previously showed up as a one-frame main-window flash.
        """
        deadline = time.monotonic() + PUBLISH_HANDSHAKE_TIMEOUT
        while (self.form.winfo_exists() and not self._publish_requested
               and time.monotonic() < deadline):
            self._drain_commands(preparing=True)
            if not self.form.winfo_exists():
                return False
            self._render_settled_frame()
            time.sleep(.005)
        return bool(self._publish_requested and self.form.winfo_exists())

    def _wait_for_publish_commit(self):
        """Keep the staged HWND cloaked until the parent arms native modality.

        The child is already mapped, fully rendered and (for a visible dialog)
        foreground at this point.  Only now is it safe for the parent to disable
        the WinUx owner: disabling a *foreground* owner while no replacement is
        active is what caused the one-frame activation flash on dialog open.
        """
        deadline = time.monotonic() + PUBLISH_HANDSHAKE_TIMEOUT
        while (self.form.winfo_exists() and not self._commit_requested
               and time.monotonic() < deadline):
            self._drain_commands(preparing=True)
            if not self.form.winfo_exists():
                return False
            self._render_settled_frame()
            time.sleep(.002)
        return bool(self._commit_requested and self.form.winfo_exists())

    def _build(self):
        initial = self.initial
        if self.prepared is None:
            configure_context(self.view)
        self.form = create_form(initial["kind"], initial.get("payload") or {}, self.view, self.emit)
        # This form is the sole content of a dedicated native viewport.  Preserve
        # its last rendered pixels until SW_HIDE; deleting the DPG item first
        # exposes the viewport clear colour (black) during close hand-off.
        self.form._defer_visual_destroy = True
        # One native viewport owns keyboard routing, independently of OS modality.
        self.form.modal = True
        dpg.configure_item(self.form.tag, modal=False, no_title_bar=True, no_move=True,
                           no_resize=True, no_collapse=True, pos=(0, 0), show=True)
        minimum = dpg.get_item_configuration(self.form.tag).get("min_size", [320, 180])
        preferred = getattr(self.form, "preferred_size", None)
        if preferred is None:
            preferred = (int(initial.get("width", 560)), max(int(initial.get("height", 360)), self.form.height))
        width = max(int(preferred[0]), int(minimum[0]))
        height = int(preferred[1]) + 40
        owner = int(initial.get("owner_hwnd") or 0)
        x, y = centered_position(window_rect(owner), (width, height), work_area(owner))
        options = dict(title=str(initial.get("title") or "WinUx Dialog"), width=width, height=height,
            x_pos=x, y_pos=y, min_width=int(minimum[0]), min_height=int(minimum[1])+40,
            resizable=bool(initial.get("resizable", True)), vsync=False)
        if self.prepared:
            dpg.configure_viewport(0, **options)
            dpg.set_primary_window(self.prepared.blank, False)
        else:
            dpg.create_viewport(**options)
        dpg.set_primary_window(self.form.tag, True)
        if self.prepared:
            dpg.delete_item(self.prepared.blank)
        # DPG's primary-window preset resets scroll flags. Only the body/page
        # should scroll; the native client shell and pinned footer never do.
        dpg.configure_item(self.form.tag, no_scrollbar=True, no_scroll_with_mouse=True)
        if self.prepared is None:
            dpg.setup_dearpygui()
            with ViewportCreationGuard() as guard:
                dpg.show_viewport()
            self.startup.extend(guard.events)
            self.native = NativeViewport(guard.hwnd, bool(initial.get("resizable", True)))
        else:
            self.native._resizable = bool(initial.get("resizable", True))
        self.native.configure(owner)
        self.native.install_close_handler(self.view, self.form._close_from_escape,
                                         getattr(self.form, "native_character", None))
        self.form.hide = self.hide
        self.form.show = self.form.lift = self.show
        # Theme/chrome, callbacks, initial RPC state and layout settle while
        # cloaked. No intermediate frame is composed on the desktop.
        for _ in range(3):
            self._drain_commands(preparing=True)
            if not self.form.winfo_exists():
                return
            self._render_settled_frame()
        if not initial.get("resizable", True):
            for _ in range(3):
                overflow = dpg.get_y_scroll_max(self.form.content)
                if overflow <= 0:
                    break
                dpg.set_viewport_height(dpg.get_viewport_height() + int(overflow) + 8)
                self._render_settled_frame()
                self._render_settled_frame()
        self.native.center(owner)
        self.startup.append({"stage": "prepared", "cloaked": cloaked(self.native.hwnd),
                             "rect": window_rect(self.native.hwnd)})
        # Keep vsync disabled through the hidden preparation transaction.  The
        # viewport is not visible yet, so paying monitor intervals here only adds
        # latency and increases the window in which stale surfaces can be shown.
        self.emit("prepared", hwnd=self.native.hwnd, pid=os.getpid())
        if not self._wait_for_publish():
            if self.form.winfo_exists():
                raise RuntimeError(
                    "Timed out waiting for the parent to publish the floating dialog.")
            return
        # Consume any visibility command that raced with the publish ack while
        # still cloaked, then perform one render transaction: map under DWM cloak,
        # settle callbacks/layout, pre-activate, and only then remove the cloak.
        self._drain_commands(preparing=True)
        if not self.form.winfo_exists():
            return
        self.native.stage_publish(self.desired_visible)
        if self.desired_visible:
            # ShowWindow happened while cloaked.  Render after mapping so GLFW's
            # swap chain contains the final dialog rather than its old blank frame.
            self._render_settled_frame()
            self._render_settled_frame()
            # Transfer foreground while the WinUx owner is still enabled.  The
            # parent disables the owner only after receiving ``staged`` below, so
            # Windows never needs to activate an unrelated desktop window.
            self.native.activate()
            self.native.flush_compositor()
        self.emit("staged", hwnd=self.native.hwnd, pid=os.getpid(),
                  visible=bool(self.desired_visible),
                  foreground=bool(self.native.is_foreground()))
        if not self._wait_for_publish_commit():
            if self.form.winfo_exists():
                raise RuntimeError(
                    "Timed out waiting for the parent to commit the floating dialog.")
            return
        self.native.commit_publish(self.desired_visible)
        dpg.configure_viewport(0, vsync=True)
        self.startup.append({"stage": "published", "cloaked": cloaked(self.native.hwnd),
            "rect": window_rect(self.native.hwnd), "visible": self.desired_visible})
        if self.desired_visible:
            if not self.native.is_foreground():
                self.native.activate()
            self._focus_form()
        self.emit(
            "ready",
            hwnd=self.native.hwnd,
            pid=os.getpid(),
            visible=bool(self.native.visible),
            layout=client_layout(self.form),
            startup=self.startup,
            reveal_count=self.native.reveal_count,
        )

    def run(self):
        if self.prepared is None:
            threading.Thread(target=self._read_commands, name="floating-dialog-reader", daemon=True).start()
            dpg.create_context()
        try:
            self._build()
            while dpg.is_dearpygui_running() and self.form.winfo_exists():
                self._drain_commands()
                if not self.form.winfo_exists():
                    break
                dpg.run_callbacks(dpg.get_callback_queue() or [])
                self.view.drain()
                dpg.render_dearpygui_frame()
                if not self.native.visible:
                    time.sleep(.016)
            try:
                return_focus = bool(self.native and self.native.is_foreground())
                if return_focus and self.native and self.native.visible:
                    # Child-driven close needs a tiny two-phase hand-off because
                    # the modal owner-disable count lives in the parent process.
                    # Keep the *last rendered dialog frame* intact while waiting;
                    # never clear/delete its DPG content before SW_HIDE.
                    self.emit("closing", return_focus=True)
                    self._wait_for_owner_handoff()
                    if self.owner_hwnd:
                        self.native.handoff_to_owner(self.owner_hwnd)
                # Hide the native surface first.  All slower DPG item/context
                # teardown happens only after DWM can no longer compose it.
                if self.native and self.native.visible:
                    self.native.set_visible(False)
                finalize_visual = getattr(self.form, "_finalize_visual_destroy", None)
                if callable(finalize_visual):
                    finalize_visual()
                self.emit("closed", return_focus=return_focus)
            except OSError:
                pass
        finally:
            if self.native:
                self.native.restore_close_handler()
            dpg.destroy_context()
