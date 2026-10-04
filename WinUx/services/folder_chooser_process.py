"""Standalone folder chooser: all Tk objects live in this child process."""
import json
import os
import sys


def choose_folder(initial):
    import tkinter as tk
    from tkinter import filedialog

    initial = initial if os.path.isdir(initial) else os.getcwd()
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update_idletasks()
        return filedialog.askdirectory(
            parent=root, title="Choose local folder",
            initialdir=initial, mustexist=True,
        ) or ""
    finally:
        root.destroy()


def main():
    try:
        result = {"path": choose_folder(sys.argv[1] if len(sys.argv) > 1 else "")}
    except Exception as exc:
        result = {"error": str(exc)}
    # ASCII JSON avoids dependence on the Abaqus console code page.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
