"""Native Qt-styled SSH Login runtime.

This child process deliberately uses real Tk/ttk Entry and Combobox widgets
instead of Dear ImGui primitives.  ttk.Combobox is one integrated editor/drop
arrow control and ttk.Entry owns the OS/Tk insertion caret, so editable fields
behave like ordinary desktop line edits rather than themed ImGui surrogates.

The process keeps the existing floating-dialog IPC protocol so the parent
WinUx controller does not need a second dialog lifecycle implementation.
"""
from __future__ import annotations

import os
import queue
import threading

from ..login_preferences import LoginPreferences
from ..platform.floating_viewport import cloaked, set_cloaked, window_rect
from ..platform.native_dialog_host import (
    _tk_root_hwnd,
    apply_native_qt_chrome,
    attach_native_owner,
    center_native_dialog_over_owner,
    handoff_owner_before_close,
    is_native_window_foreground,
)
from ..services.floating_protocol import encode_message


class NativeQtLoginRuntime:
    """Protocol-compatible floating Login implemented with native ttk widgets."""

    POLL_MS = 12

    def __init__(self, connection, messages, initial):
        self.connection = connection
        self.messages = messages
        self.initial = initial
        self.owner_hwnd = int(initial.get("owner_hwnd") or 0)
        self.desired_visible = bool(initial.get("visible", True))
        self.payload = dict(initial.get("payload") or {})
        self.values = dict(self.payload.get("initial") or {})
        self.incoming = queue.Queue(maxsize=128)
        self.root = None
        self.hwnd = 0
        self._closing = False
        self._close_return_focus = False
        self._waiting_owner_handoff = False
        self._published = False
        self._busy = False
        self._startup = []
        self._preferences = LoginPreferences()

    def emit(self, event, **values):
        try:
            self.connection.sendall(encode_message({"event": event, **values}))
            return True
        except (OSError, ValueError):
            return False

    def _reader(self):
        try:
            for message in self.messages:
                self.incoming.put(message)
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.incoming.put_nowait({"command": "close"})
            except queue.Full:
                pass

    @staticmethod
    def _configure_qt_styles(root):
        import tkinter as tk
        from tkinter import ttk
        from ..components.qt_style import QtFusionPalette, color_hex

        style = ttk.Style(root)
        # ``clam`` is the only stock ttk engine that consistently honours
        # field/background/border colours.  This child process is dedicated to
        # WinUx Login, so changing its ttk theme cannot affect Abaqus or the
        # Dear PyGui main window.
        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except tk.TclError:
            pass

        p = QtFusionPalette
        window = color_hex(p.WINDOW)
        base = color_hex(p.BASE)
        text = color_hex(p.TEXT)
        muted = color_hex(p.TEXT_MUTED)
        border = color_hex(p.BORDER)
        focus = color_hex(p.FOCUS)
        button = color_hex(p.BUTTON)
        button_hover = color_hex(p.BUTTON_HOVER)
        button_active = color_hex(p.BUTTON_ACTIVE)
        disabled = color_hex(p.BUTTON_DISABLED)
        select = color_hex(p.HIGHLIGHT_SOFT)

        style.configure("WinUx.Qt.TFrame", background=window)
        style.configure("WinUx.QtGroup.TLabelframe", background=window,
                        bordercolor=border, borderwidth=1, relief="solid")
        style.configure("WinUx.QtGroup.TLabelframe.Label", background=window,
                        foreground=text, font=("Segoe UI Semibold", 9))
        style.configure("WinUx.Qt.TLabel", background=window, foreground=text,
                        font=("Segoe UI", 9))
        style.configure("WinUx.QtError.TLabel", background=window,
                        foreground="#b42318", font=("Segoe UI", 9))

        # QLineEdit-like flat frame.  In clam the bordercolor map is visible,
        # so focus is rendered as a single blue frame while the actual ttk Entry
        # remains responsible for text selection and the blinking insertion caret.
        style.configure(
            "WinUx.QtLineEdit.TEntry",
            fieldbackground=base, background=base, foreground=text,
            insertcolor=text, bordercolor=border, lightcolor=border,
            darkcolor=border, padding=(6, 4), borderwidth=1, relief="flat",
        )
        style.map(
            "WinUx.QtLineEdit.TEntry",
            fieldbackground=[("disabled", disabled), ("!disabled", base)],
            foreground=[("disabled", muted), ("!disabled", text)],
            bordercolor=[("focus", focus), ("!focus", border)],
            lightcolor=[("focus", focus), ("!focus", border)],
            darkcolor=[("focus", focus), ("!focus", border)],
        )

        # A real ttk Combobox is a single widget: the editor and arrow are one
        # native control, so there is no visual or hit-test seam between them.
        style.configure(
            "WinUx.QtComboBox.TCombobox",
            fieldbackground=base, background=base, foreground=text,
            arrowcolor=text, bordercolor=border, lightcolor=border,
            darkcolor=border, padding=(6, 4), borderwidth=1, relief="flat",
            arrowsize=12,
        )
        style.map(
            "WinUx.QtComboBox.TCombobox",
            fieldbackground=[("disabled", disabled), ("readonly", base), ("!disabled", base)],
            foreground=[("disabled", muted), ("!disabled", text)],
            background=[("pressed", button_active), ("active", button_hover), ("!disabled", base)],
            arrowcolor=[("disabled", muted), ("!disabled", text)],
            bordercolor=[("focus", focus), ("!focus", border)],
            lightcolor=[("focus", focus), ("!focus", border)],
            darkcolor=[("focus", focus), ("!focus", border)],
        )
        try:
            root.option_add("*TCombobox*Listbox.background", base)
            root.option_add("*TCombobox*Listbox.foreground", text)
            root.option_add("*TCombobox*Listbox.selectBackground", select)
            root.option_add("*TCombobox*Listbox.selectForeground", text)
        except tk.TclError:
            pass

        style.configure("WinUx.Qt.TCheckbutton", background=window,
                        foreground=text, font=("Segoe UI", 9), padding=(0, 1))
        style.map("WinUx.Qt.TCheckbutton",
                  background=[("active", window), ("!disabled", window)],
                  foreground=[("disabled", muted), ("!disabled", text)])

        style.configure("WinUx.Qt.TButton", background=button,
                        foreground=text, bordercolor=border, lightcolor=border,
                        darkcolor=border, font=("Segoe UI", 9),
                        padding=(12, 5), borderwidth=1, relief="flat")
        style.map("WinUx.Qt.TButton",
                  background=[("pressed", button_active), ("active", button_hover),
                              ("disabled", disabled), ("!disabled", button)],
                  foreground=[("disabled", muted), ("!disabled", text)],
                  bordercolor=[("focus", focus), ("!focus", border)],
                  lightcolor=[("focus", focus), ("!focus", border)],
                  darkcolor=[("focus", focus), ("!focus", border)])

        style.configure("WinUx.QtPrimary.TButton", background=button,
                        foreground=text, bordercolor=focus, lightcolor=focus,
                        darkcolor=focus, font=("Segoe UI", 9),
                        padding=(12, 5), borderwidth=1, relief="flat")
        style.map("WinUx.QtPrimary.TButton",
                  background=[("pressed", button_active), ("active", button_hover),
                              ("disabled", disabled), ("!disabled", button)],
                  foreground=[("disabled", muted), ("!disabled", text)],
                  bordercolor=[("disabled", border), ("!disabled", focus)],
                  lightcolor=[("disabled", border), ("!disabled", focus)],
                  darkcolor=[("disabled", border), ("!disabled", focus)])

    def _build(self):
        import tkinter as tk
        from tkinter import ttk
        from .modern import prepare_modern_toplevel

        root = getattr(tk, "Tk")(className="WinUxLogin")
        self.root = root
        root.withdraw()
        self._configure_qt_styles(root)
        prepare_modern_toplevel(root, str(self.initial.get("title") or "SSH Login"))
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._request_close)
        root.configure(background="#f0f0f0")

        outer = ttk.Frame(root, style="WinUx.Qt.TFrame", padding=(10, 9, 10, 10))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        group = ttk.LabelFrame(outer, text="Connection", style="WinUx.QtGroup.TLabelframe",
                               padding=(9, 8, 9, 8))
        group.grid(row=0, column=0, sticky="ew")
        group.columnconfigure(1, weight=1)

        initial = self.values
        self.host_var = tk.StringVar(root, str(initial.get("host", "")))
        self.port_var = tk.StringVar(root, str(initial.get("port", "22")))
        self.username_var = tk.StringVar(root, str(initial.get("username", "")))
        self.password_var = tk.StringVar(root, str(initial.get("password", "")))
        self.remember_var = tk.BooleanVar(root, bool(initial.get("remember", False)))
        self.error_var = tk.StringVar(root, "")
        self._ports = {str(k): str(v) for k, v in dict(initial.get("ports", {})).items()}

        labels = ("Host", "Port", "Username", "Password")
        for row, text in enumerate(labels):
            ttk.Label(group, text=text, style="WinUx.Qt.TLabel", anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=(2, 4))

        self.host = ttk.Combobox(group, textvariable=self.host_var,
                                 values=list(initial.get("hosts", [])), state="normal",
                                 style="WinUx.QtComboBox.TCombobox", width=34)
        self.host.grid(row=0, column=1, sticky="ew", pady=(1, 4))
        self.port = ttk.Entry(group, textvariable=self.port_var,
                              style="WinUx.QtLineEdit.TEntry")
        self.port.grid(row=1, column=1, sticky="ew", pady=(1, 4))
        self.username = ttk.Combobox(group, textvariable=self.username_var,
                                     values=list(initial.get("usernames", [])), state="normal",
                                     style="WinUx.QtComboBox.TCombobox", width=34)
        self.username.grid(row=2, column=1, sticky="ew", pady=(1, 4))
        self.password = ttk.Entry(group, textvariable=self.password_var, show="*",
                                  style="WinUx.QtLineEdit.TEntry")
        self.password.grid(row=3, column=1, sticky="ew", pady=(1, 4))
        self.remember = ttk.Checkbutton(
            group, text="Remember password for this Windows account",
            variable=self.remember_var, style="WinUx.Qt.TCheckbutton")
        self.remember.grid(row=4, column=0, columnspan=2, sticky="w", pady=(3, 0))

        self.error = ttk.Label(outer, textvariable=self.error_var,
                               style="WinUx.QtError.TLabel", anchor="w")
        self.error.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        footer = ttk.Frame(outer, style="WinUx.Qt.TFrame")
        footer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)
        self.connect_button = ttk.Button(footer, text="Connect", command=self._submit,
                                         style="WinUx.QtPrimary.TButton", width=11)
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self._request_close,
                                        style="WinUx.Qt.TButton", width=11)
        self.connect_button.grid(row=0, column=1, padx=(0, 7))
        self.cancel_button.grid(row=0, column=2)
        self.footer = footer

        self.host.bind("<<ComboboxSelected>>", self._host_selected, add="+")
        self.username.bind("<<ComboboxSelected>>", self._username_selected, add="+")
        root.bind("<Return>", self._return_pressed, add="+")
        root.bind("<Escape>", lambda _e: self._request_close(), add="+")

        root.update_idletasks()
        requested_w = max(430, int(root.winfo_reqwidth()))
        requested_h = max(245, int(root.winfo_reqheight()))
        root.geometry(f"{requested_w}x{requested_h}")
        root.minsize(requested_w, requested_h)
        root.maxsize(requested_w, requested_h)
        root.update_idletasks()

        self.hwnd = int(_tk_root_hwnd(root) or 0)
        if self.owner_hwnd:
            attach_native_owner(root, self.owner_hwnd)
        apply_native_qt_chrome(root, window_role="dialog",
                               allow_minimize=False, allow_maximize=False)
        if self.hwnd and os.name == "nt":
            set_cloaked(self.hwnd, True)
        # Map while DWM-cloaked.  The first frame exposed to the desktop is the
        # completely laid-out ttk dialog; there is no intermediate ImGui frame.
        root.deiconify()
        root.update_idletasks()
        if self.owner_hwnd:
            center_native_dialog_over_owner(root, self.owner_hwnd)
        root.update_idletasks()
        self._startup.append({"stage": "prepared", "cloaked": cloaked(self.hwnd),
                              "rect": window_rect(self.hwnd)})
        self.emit("prepared", hwnd=self.hwnd, pid=os.getpid())

        threading.Thread(target=self._reader, name="native-login-reader", daemon=True).start()
        root.after(self.POLL_MS, self._pump)
        root.mainloop()

    def _pump(self):
        root = self.root
        if root is None:
            return
        for _ in range(32):
            try:
                message = self.incoming.get_nowait()
            except queue.Empty:
                break
            self._handle_command(message)
            if self.root is None:
                return
        try:
            root.after(self.POLL_MS, self._pump)
        except Exception:
            pass

    def _handle_command(self, message):
        command = str(message.get("command") or "")
        args = list(message.get("args") or [])
        if command == "publish":
            self._stage_publish()
        elif command == "publish_commit":
            self._commit_publish()
        elif command == "activate":
            self._show()
        elif command == "hide":
            self._hide()
        elif command == "close":
            self._begin_close(force=True)
        elif command == "owner_handoff_ready":
            if self._waiting_owner_handoff:
                self._waiting_owner_handoff = False
                self._finish_close()
        elif command == "set_busy":
            self._set_busy(bool(args[0]) if args else False)
        elif command == "set_error":
            self._set_error(str(args[0]) if args else "")

    def _stage_publish(self):
        if self.root is None:
            return
        if self.desired_visible:
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
                self._focus_initial()
                self.root.update_idletasks()
            except Exception:
                pass
        self.emit("staged", hwnd=self.hwnd, pid=os.getpid(),
                  visible=self.desired_visible,
                  foreground=bool(is_native_window_foreground(self.root)))

    def _commit_publish(self):
        if self.root is None or self._published:
            return
        if os.name == "nt" and self.hwnd:
            try:
                set_cloaked(self.hwnd, False)
            except Exception:
                pass
        self._published = True
        self._startup.append({"stage": "published", "cloaked": cloaked(self.hwnd),
                              "rect": window_rect(self.hwnd),
                              "visible": self.desired_visible})
        if self.desired_visible:
            try:
                self.root.lift()
                self.root.focus_force()
                self._focus_initial()
            except Exception:
                pass
        self.emit("ready", hwnd=self.hwnd, pid=os.getpid(), visible=self.desired_visible,
                  layout=self._client_layout(), startup=list(self._startup), reveal_count=1)

    def _show(self):
        if self.root is None:
            return
        self.desired_visible = True
        try:
            self.root.deiconify()
            if os.name == "nt" and self.hwnd and cloaked(self.hwnd):
                set_cloaked(self.hwnd, False)
            self.root.lift()
            self.root.focus_force()
            self._focus_initial()
        except Exception:
            pass
        self.emit("visibility", visible=True)

    def _hide(self):
        if self.root is None:
            return
        active = bool(is_native_window_foreground(self.root))
        self.desired_visible = False
        if active and self.owner_hwnd:
            handoff_owner_before_close(self.owner_hwnd, self.hwnd)
        try:
            self.root.withdraw()
        except Exception:
            pass
        self.emit("visibility", visible=False, return_focus=active)

    def _return_pressed(self, event=None):
        # A posted combobox popup owns Return; otherwise it is QDialog's default
        # accept action.  ttk does not expose popup state directly, so only run
        # Connect when focus is in an editable field or button.
        if self._busy:
            return "break"
        self._submit()
        return "break"

    def _host_selected(self, _event=None):
        port = self._ports.get(self.host_var.get().strip())
        if port:
            self.port_var.set(str(port))

    def _username_selected(self, _event=None):
        username = self.username_var.get().strip()
        try:
            self.password_var.set(self._preferences.password_for(username))
        except Exception:
            self.password_var.set("")

    def _snapshot(self):
        return {
            "host": self.host_var.get().strip(),
            "port": self.port_var.get().strip(),
            "username": self.username_var.get().strip(),
            "password": self.password_var.get(),
            "remember": bool(self.remember_var.get()),
        }

    def _submit(self):
        if self._busy or self.root is None:
            return
        values = self._snapshot()
        if not values["host"] or not values["username"]:
            self._set_error("Host and username are required.")
            return
        try:
            port = int(values["port"])
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self._set_error("Port must be a number from 1 to 65535.")
            return
        self._set_busy(True)
        self.error_var.set("")
        self.emit("submit", values=values)

    def _set_busy(self, busy):
        self._busy = bool(busy)
        state = "disabled" if self._busy else "normal"
        for widget in (self.host, self.port, self.username, self.password,
                       self.remember, self.cancel_button):
            try:
                widget.configure(state=state)
            except Exception:
                pass
        try:
            self.connect_button.configure(
                state=state, text="Connecting" if self._busy else "Connect")
        except Exception:
            pass

    def _set_error(self, message):
        if self.root is None:
            return
        self.error_var.set(str(message))
        self._set_busy(False)
        self._focus_initial()

    def _focus_initial(self):
        if self.root is None:
            return
        try:
            if not self.host_var.get().strip():
                target = self.host
            elif not self.username_var.get().strip():
                target = self.username
            elif not self.password_var.get():
                target = self.password
            else:
                target = self.username
            target.focus_set()
            # Put the insertion caret at the end without selecting the whole
            # value.  A later mouse click can freely relocate it.
            try:
                target.icursor("end")
                target.selection_clear()
            except Exception:
                pass
        except Exception:
            pass

    def _request_close(self):
        if self._busy:
            return
        self._begin_close(force=False)

    def _begin_close(self, force=False):
        if self._closing or self.root is None:
            return
        if self._busy and not force:
            return
        self._closing = True
        self._close_return_focus = bool(is_native_window_foreground(self.root))
        if self._close_return_focus:
            self._waiting_owner_handoff = True
            self.emit("closing", return_focus=True)
            # Parent normally acknowledges immediately.  Keep a bounded fallback
            # so a broken/closing IPC channel cannot strand the Login window.
            try:
                self.root.after(100, self._close_handoff_timeout)
            except Exception:
                self._finish_close()
        else:
            self._finish_close()

    def _close_handoff_timeout(self):
        if self._waiting_owner_handoff:
            self._waiting_owner_handoff = False
            self._finish_close()

    def _finish_close(self):
        root = self.root
        if root is None:
            return
        if self._close_return_focus and self.owner_hwnd:
            handoff_owner_before_close(self.owner_hwnd, self.hwnd)
        try:
            root.withdraw()
        except Exception:
            pass
        self.emit("closed", return_focus=self._close_return_focus)
        self.root = None
        try:
            root.after_idle(root.destroy)
        except Exception:
            try:
                root.destroy()
            except Exception:
                pass

    @staticmethod
    def _bounds(root, widget):
        try:
            x = int(widget.winfo_rootx() - root.winfo_rootx())
            y = int(widget.winfo_rooty() - root.winfo_rooty())
            w = int(widget.winfo_width())
            h = int(widget.winfo_height())
            return [x, y, x + w, y + h]
        except Exception:
            return [0, 0, 0, 0]

    def _client_layout(self):
        root = self.root
        if root is None:
            return {"client": [0, 0], "widgets": {}, "footer": [0, 0, 0, 0],
                    "shell_scrollbar": False}
        try:
            root.update_idletasks()
        except Exception:
            pass
        host = self._bounds(root, self.host)
        username = self._bounds(root, self.username)
        # Integrated ttk Combobox exposes one HWND/widget, but preserve the old
        # diagnostic keys by reporting the arrow sub-control region geometrically.
        arrow_width = min(24, max(16, host[2] - host[0]))
        u_arrow_width = min(24, max(16, username[2] - username[0]))
        widgets = {
            "host": host,
            "host_arrow": [host[2] - arrow_width, host[1], host[2], host[3]],
            "username": username,
            "username_arrow": [username[2] - u_arrow_width, username[1], username[2], username[3]],
            "password": self._bounds(root, self.password),
            "connect": self._bounds(root, self.connect_button),
            "cancel": self._bounds(root, self.cancel_button),
        }
        return {
            "client": [int(root.winfo_width()), int(root.winfo_height())],
            "widgets": widgets,
            "footer": self._bounds(root, self.footer),
            "shell_scrollbar": False,
        }

    def run(self):
        try:
            self._build()
        finally:
            root = self.root
            self.root = None
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass


__all__ = ["NativeQtLoginRuntime"]
