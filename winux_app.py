import os
import sys
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from dataclasses import dataclass
from typing import Iterable, List

# Import Pillow để xử lý ảnh và hiển thị lên Tkinter
from PIL import Image, ImageTk, ImageDraw

# --- CẤU HÌNH WIN32 API THEO HƯỚNG TIẾP CẬN C# (SHGetFileInfo & DestroyIcon) ---
HAS_WIN32 = False
if sys.platform.startswith("win"):
    try:
        import ctypes
        from ctypes import wintypes

        # Định nghĩa các cấu trúc tương ứng trong C# struct SHFILEINFO
        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [
                ('hIcon', wintypes.HANDLE),
                ('iIcon', ctypes.c_int),
                ('dwAttributes', wintypes.DWORD),
                ('szDisplayName', ctypes.c_wchar * 260),
                ('szTypeName', ctypes.c_wchar * 80)
            ]

        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ('fIcon', wintypes.BOOL),
                ('xHotspot', wintypes.DWORD),
                ('yHotspot', wintypes.DWORD),
                ('hbmMask', wintypes.HANDLE),
                ('hbmColor', wintypes.HANDLE)
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ('biSize', wintypes.DWORD),
                ('biWidth', ctypes.c_long),
                ('biHeight', ctypes.c_long),
                ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD),
                ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long),
                ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)
            ]

        # Khai báo hằng số tương đương const uint trong C#
        SHGFI_ICON = 0x000000100
        SHGFI_SMALLICON = 0x000000001
        SHGFI_USEFILEATTRIBUTES = 0x00000010

        FILE_ATTRIBUTE_DIRECTORY = 0x00000010
        FILE_ATTRIBUTE_NORMAL = 0x00000080

        HAS_WIN32 = True
    except Exception:
        HAS_WIN32 = False


@dataclass
class FileItem:
    name: str
    full_path: str
    is_dir: bool
    size_text: str
    type_text: str
    modified_text: str
    icon_key: str


class WindowsIconRegistry:
    """Quản lý, tạo và cache các icon dựa theo đúng triết lý nạp & giải phóng HICON của C#."""
    _registry = {}

    @classmethod
    def init_registry(cls):
        # Tạo icon Thư mục dự phòng (Folder.png)
        dir_img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        dir_draw = ImageDraw.Draw(dir_img)
        dir_draw.rectangle([1, 4, 14, 13], fill="#FFCA28", outline="#F57F17")
        dir_draw.polygon([(1, 4), (1, 2), (5, 2), (7, 4)], fill="#FFA000")
        cls._registry['dir_type'] = ImageTk.PhotoImage(dir_img)

        # Tạo icon File dự phòng (File.png)
        file_img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        file_draw = ImageDraw.Draw(file_img)
        file_draw.rectangle([2, 1, 13, 14], fill="#FFFFFF", outline="#78909C")
        file_draw.polygon([(10, 1), (13, 4), (10, 4)], fill="#B0BEC5")
        cls._registry['file_default'] = ImageTk.PhotoImage(file_img)

    @classmethod
    def get_icon(cls, ext_or_dir: str, is_dir: bool = False):
        key = "dir_type" if is_dir else ext_or_dir.lower()
        
        # Nếu đã có trong Cache thì trả về luôn để tối ưu luồng UI (tương tự Frozen trong WPF)
        if key in cls._registry and key != "":
            return cls._registry[key]

        if is_dir:
            return cls._registry['dir_type']

        if not HAS_WIN32:
            return cls._registry['file_default']

        # Chuẩn bị dữ liệu để gọi SHGetFileInfo giống hệt C#
        shinfo = SHFILEINFOW()
        flags = SHGFI_ICON | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES
        attributes = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
        target_path = f"dummy{key}" if key else "dummy_file"

        # Gọi Windows Shell32 API
        res = ctypes.windll.shell32.SHGetFileInfoW(
            target_path, attributes, ctypes.byref(shinfo), ctypes.sizeof(shinfo), flags
        )

        if not res or shinfo.hIcon is None or shinfo.hIcon == 0:
            return cls._registry['file_default']

        # Áp dụng cấu trúc try-catch-finally để đảm bảo luôn giải phóng Native Pointer (HICON)
        try:
            icon_info = ICONINFO()
            if ctypes.windll.user32.GetIconInfo(shinfo.hIcon, ctypes.byref(icon_info)):
                hdc = ctypes.windll.user32.GetDC(0)
                
                # Tạo BitmapHeader tương thích để trích xuất mảng Pixel
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = 16
                bmi.biHeight = -16  # Chiều cao âm giúp ảnh không bị lộn ngược (Top-down)
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0
                
                # Cấp phát buffer chứa dữ liệu pixel (16 * 16 * 4 bytes RGBA)
                buffer = ctypes.create_string_buffer(16 * 16 * 4)
                
                # Copy dữ liệu đồ họa ra bộ đệm (tương đương Imaging.CreateBitmapSourceFromHIcon)
                ctypes.windll.gdi32.GetDIBits(
                    hdc, icon_info.hbmColor, 0, 16, 
                    buffer, ctypes.byref(bmi), 0
                )
                
                # Giải phóng DCs tạm thời của Windows
                ctypes.windll.user32.ReleaseDC(0, hdc)
                ctypes.windll.gdi32.DeleteObject(icon_info.hbmColor)
                ctypes.windll.gdi32.DeleteObject(icon_info.hbmMask)
                
                # Dùng Pillow convert mảng bytes thô (BGRA) thành ảnh Bitmap
                pil_img = Image.frombuffer('RGBA', (16, 16), buffer.raw, 'raw', 'BGRA', 0, 1)
                tk_img = ImageTk.PhotoImage(pil_img)
                
                cls._registry[key] = tk_img
                return tk_img
        except Exception:
            return cls._registry['file_default']
        finally:
            # GIẢI PHÓNG HICON (DestroyIcon) ĐỂ TRÁNH RÒ RỈ GDI HANDLE TRONG FINALLY BLOCK
            if shinfo.hIcon:
                ctypes.windll.user32.DestroyIcon(shinfo.hIcon)


class FilePanel(ttk.Frame):
    BATCH_SIZE = 300

    def __init__(self, master, default_path: str):
        super().__init__(master)
        self.current_path = ""
        self._generation = 0
        self._items: List[FileItem] = []
        self._insert_index = 0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_navigation()
        self._build_tree()
        self._build_footer()
        self.load_directory(default_path)

    def _build_navigation(self):
        nav = ttk.Frame(self, padding=(4, 4))
        nav.grid(row=0, column=0, sticky="ew")
        nav.columnconfigure(4, weight=1)

        ttk.Button(nav, text="←", width=3, command=self.go_parent).grid(row=0, column=0, padx=(0, 2))
        ttk.Button(nav, text="→", width=3, state="disabled").grid(row=0, column=1, padx=2)
        ttk.Button(nav, text="⌂", width=3, command=self.go_home).grid(row=0, column=2, padx=2)
        ttk.Button(nav, text="↻", width=3, command=self.refresh).grid(row=0, column=3, padx=(2, 6))

        self.address_var = tk.StringVar()
        entry = ttk.Entry(nav, textvariable=self.address_var)
        entry.grid(row=0, column=4, sticky="ew")
        entry.bind("<Return>", lambda _e: self.load_directory(self.address_var.get()))

    def _build_tree(self):
        holder = ttk.Frame(self)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        columns = ("type", "size", "modified")
        self.tree = ttk.Treeview(holder, columns=columns, show="tree headings", selectmode="extended")
        
        self.tree.heading("#0", text="Name", anchor="w", command=lambda: self.sort_by("#0", False))
        self.tree.column("#0", width=360, minwidth=150, stretch=True)

        specs = (
            ("type", "Type", 125, False, "w"),
            ("size", "Size", 100, False, "e"),
            ("modified", "Date Modified", 170, False, "w"),
        )
        for key, title, width, stretch, anchor in specs:
            self.tree.heading(key, text=title, anchor="w", command=lambda c=key: self.sort_by(c, False))
            self.tree.column(key, width=width, minwidth=70, stretch=stretch, anchor=anchor)

        ys = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", self._double_click)
        self.tree.bind("<Return>", self._open_selected)

    def _build_footer(self):
        self.footer_var = tk.StringVar(value="0 item(s)")
        ttk.Label(self, textvariable=self.footer_var, anchor="w", padding=(8, 3)).grid(
            row=2, column=0, sticky="ew"
        )

    def load_directory(self, path: str):
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(path.strip())))
        if not os.path.isdir(path):
            self.footer_var.set("Folder not found")
            return

        self._generation += 1
        generation = self._generation
        self.current_path = path
        self.address_var.set(path)
        self.footer_var.set("Loading...")

        children = self.tree.get_children("")
        if children:
            self.tree.delete(*children)

        try:
            items = list(self._scan(path))
        except PermissionError:
            self.footer_var.set("Permission denied")
            return
        except OSError as exc:
            self.footer_var.set("Error: %s" % exc)
            return

        if generation != self._generation:
            return

        items.sort(key=lambda x: (not x.is_dir, x.name.casefold()))
        self._items = items
        self._insert_index = 0
        self._insert_batch(generation)

    def _scan(self, path: str) -> Iterable[FileItem]:
        parent = os.path.dirname(path)
        if parent and parent != path:
            yield FileItem("..", parent, True, "", "Parent Folder", "", "dir_type")

        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    stat = entry.stat(follow_symlinks=False)
                except (PermissionError, FileNotFoundError, OSError):
                    continue

                ext = os.path.splitext(entry.name)[1].lower()
                if is_dir:
                    size_text, type_text, icon_key = "", "File Folder", "dir_type"
                else:
                    size_text = self.format_size(stat.st_size)
                    type_text = "%s File" % ext[1:].upper() if ext else "File"
                    icon_key = ext

                yield FileItem(
                    entry.name, entry.path, is_dir, size_text, type_text,
                    datetime.fromtimestamp(stat.st_mtime).strftime("%m/%d/%Y %I:%M %p"),
                    icon_key
                )

    def _insert_batch(self, generation: int):
        if generation != self._generation:
            return
        end = min(self._insert_index + self.BATCH_SIZE, len(self._items))
        for item in self._items[self._insert_index:end]:
            img_obj = WindowsIconRegistry.get_icon(item.icon_key, item.is_dir)
            self.tree.insert(
                "", "end", text=item.name, image=img_obj,
                values=(item.type_text, item.size_text, item.modified_text, item.full_path)
            )
        self._insert_index = end
        if end < len(self._items):
            self.after_idle(lambda: self._insert_batch(generation))
        else:
            self.footer_var.set("%d item(s)" % len(self._items))

    def go_home(self):
        self.load_directory(os.path.expanduser("~"))

    def go_parent(self):
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.load_directory(parent)

    def refresh(self):
        self.load_directory(self.current_path)

    def _selection_changed(self, _event=None):
        self.footer_var.set(
            "Selected %d item(s)  |  Total %d" %
            (len(self.tree.selection()), len(self.tree.get_children("")))
        )

    def _double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self._open_item(item_id)

    def _open_selected(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self._open_item(selected[0])

    def _open_item(self, item_id):
        values = self.tree.item(item_id, "values")
        if not values or len(values) < 4:
            return
        full_path = values[3]
        
        if os.path.isdir(full_path):
            self.load_directory(full_path)
        elif os.path.isfile(full_path):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(full_path)
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", full_path])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", full_path])
            except OSError:
                pass

    def sort_by(self, column, descending):
        if column == "#0":
            rows = [(self.tree.item(i, "text"), i) for i in self.tree.get_children("")]
        else:
            rows = [(self.tree.set(i, column), i) for i in self.tree.get_children("")]
            
        if column == "size":
            rows.sort(key=lambda p: self._parse_size(p[0]), reverse=descending)
        else:
            rows.sort(key=lambda p: p[0].casefold(), reverse=descending)
            
        for index, (_value, item_id) in enumerate(rows):
            self.tree.move(item_id, "", index)
            
        self.tree.heading(column, command=lambda: self.sort_by(column, not descending))

    @staticmethod
    def _parse_size(value):
        if not value:
            return -1
        try:
            number, unit = value.replace(",", "").split(maxsplit=1)
            return float(number) * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}.get(unit, 1)
        except Exception:
            return 0

    @staticmethod
    def format_size(size_bytes):
        size = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024.0 or unit == "TB":
                return "%s B" % format(int(size), ",") if unit == "B" else "{:,.1f} {}".format(size, unit)
            size /= 1024.0
        return str(size_bytes)


class WinUXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WinUX - Abaqus File & Job Explorer")
        self.geometry("1200x800")
        self.minsize(950, 650)
        
        # Gọi khởi tạo Registry lưu trữ Icon trước khi sinh giao diện
        WindowsIconRegistry.init_registry()

        self.rowconfigure(0, weight=1) # Sửa lại grid row: bây giờ row 0 là Panel chính vì Toolbar nút bấm đã bị xóa
        self.columnconfigure(0, weight=1)
        self._configure_style()
        self._build_menubar() # Khởi tạo Menubar hệ thống
        self._build_layout()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except tk.TclError:
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(6, 4))
        style.map("Treeview", background=[("selected", "#CCE8FF")], foreground=[("selected", "#202020")])

    def _build_menubar(self):
        """Thay thế Toolbar nút bấm cũ bằng thanh Menubar Windows tiêu chuẩn."""
        menubar = tk.Menu(self)

        # 1. Menu "File"
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open", command=self._menu_not_implemented)
        file_menu.add_command(label="New Project...", command=self._menu_not_implemented)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # 2. Menu "Home"
        home_menu = tk.Menu(menubar, tearoff=0)
        home_menu.add_command(label="Go to User Profile", command=self._go_user_profile)
        home_menu.add_command(label="Go to Workspace", command=self._go_workspace)
        menubar.add_cascade(label="Home", menu=home_menu)

        # 3. Menu "View"
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Show Job Console", command=self._menu_not_implemented)
        view_menu.add_checkbutton(label="Status Bar", command=self._menu_not_implemented)
        view_menu.add_separator()
        view_menu.add_command(label="Refresh All Panels", command=self._refresh_panels)
        menubar.add_cascade(label="View", menu=view_menu)

        # Gán Menubar vào cửa sổ chính của App
        self.config(menu=menubar)

    def _go_user_profile(self):
        """Sự kiện chuyển đổi nhanh vùng thư mục Home"""
        for panel in self._get_file_panels():
            panel.go_home()

    def _go_workspace(self):
        """Quay về thư mục làm việc hiện tại của Abaqus/Python"""
        for panel in self._get_file_panels():
            panel.load_directory(os.getcwd())

    def _refresh_panels(self):
        """F5 làm mới toàn bộ các panel danh sách file"""
        for panel in self._get_file_panels():
            panel.refresh()

    def _get_file_panels(self) -> List[FilePanel]:
        """Trích xuất nhanh các FilePanel con đang chạy để quản lý tập trung từ Menu"""
        panels = []
        for child in self.winfo_children():
            # Quét sâu qua PanedWindow để định vị FilePanel
            if isinstance(child, tk.PanedWindow):
                for sub_child in child.winfo_children():
                    if isinstance(sub_child, tk.PanedWindow):
                        for leaf in sub_child.winfo_children():
                            if isinstance(leaf, FilePanel):
                                panels.append(leaf)
        return panels

    def _menu_not_implemented(self):
        # Hàm xử lý tạm thời cho các tính năng chưa phát triển
        pass

    def _build_layout(self):
        vertical = tk.PanedWindow(self, orient=tk.VERTICAL, bd=0, sashwidth=4, opaque=False)
        vertical.grid(row=0, column=0, sticky="nsew", padx=4, pady=(0, 4))

        horizontal = tk.PanedWindow(vertical, orient=tk.HORIZONTAL, bd=0, sashwidth=4, opaque=False)
        vertical.add(horizontal, stretch="always")

        left = FilePanel(horizontal, os.getcwd())
        right_default = "C:\\" if os.name == "nt" and os.path.isdir("C:\\") else os.path.expanduser("~")
        right = FilePanel(horizontal, right_default)
        horizontal.add(left, minsize=250, stretch="always")
        horizontal.add(right, minsize=250, stretch="always")

        bottom = ttk.Frame(vertical)
        vertical.add(bottom, minsize=140, stretch="always")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=1)

        columns = ("id", "job", "user", "tokens", "status", "elapsed")
        jobs = ttk.Treeview(bottom, columns=columns, show="headings", height=6)
        for key, title, width in (
            ("id", "ID", 70), ("job", "Job Name", 430), ("user", "User", 110),
            ("tokens", "Tokens", 90), ("status", "Status", 110), ("elapsed", "Elapsed", 110)
        ):
            jobs.heading(key, text=title, anchor="w")
            jobs.column(key, width=width, minwidth=60, stretch=(key == "job"), anchor="w")
        jobs.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(bottom, orient="vertical", command=jobs.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        jobs.configure(yscrollcommand=scrollbar.set)


def main():
    app = WinUXApp()
    app.mainloop()


if __name__ == "__main__":
    main()