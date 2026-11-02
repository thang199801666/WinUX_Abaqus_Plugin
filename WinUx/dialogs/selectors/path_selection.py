"""Selection policy shared by the local file and folder browser surfaces."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class PathSelectionOptions:
    kind: str = "folder"
    multiple: bool = False
    extensions: tuple = ()
    save: bool = False

    def __post_init__(self):
        if self.kind not in ("file", "folder"):
            raise ValueError("Selection kind must be file or folder.")
        if self.save and (self.kind != "file" or self.multiple):
            raise ValueError("Save supports a single file only.")
        extensions = tuple(dict.fromkeys(
            ("." + str(ext).lstrip("*. ")).lower()
            for ext in self.extensions
            if str(ext).strip() not in ("", "*", ".*", "*.*")))
        object.__setattr__(self, "extensions", extensions)

    def includes(self, entry, is_dir, *, show_all=False):
        if is_dir:
            return True  # Folders remain navigable with every file filter.
        return self.kind == "file" and entry.is_file(follow_symlinks=True) and (
            show_all or not self.extensions or Path(entry.name).suffix.lower() in self.extensions)

    def format_paths(self, paths):
        values = [str(path) if self.kind == "folder" else Path(path).name for path in paths]
        if not self.multiple or len(values) <= 1:
            return values[0] if values else ""
        return " ".join('"{}"'.format(value) for value in values)

    def resolve(self, directory, text, *, show_all=False):
        text = str(text or "").strip()
        if not text:
            raise ValueError("Enter or select a {} name.".format(self.kind))
        # Windows paths contain backslashes: shlex's POSIX escaping would
        # corrupt them. Explorer-style quoted names also allow spaces.
        if self.multiple and text.startswith('"'):
            tokens = re.findall(r'"([^"\r\n]+)"', text)
            if not tokens or re.sub(r'"[^"\r\n]+"', '', text).strip():
                raise ValueError('Quote each selected name, separated by spaces.')
        else:
            tokens = [text.strip('"')]
        paths = []
        for value in tokens:
            path = Path(os.path.abspath(os.path.join(
                directory, os.path.expandvars(os.path.expanduser(value)))))
            if self.kind == "folder":
                if not path.is_dir():
                    raise ValueError("Folder does not exist: {}".format(path))
            else:
                if self.save and not path.suffix and self.extensions and not show_all:
                    path = path.with_suffix(self.extensions[0])
                if self.extensions and not show_all and path.suffix.lower() not in self.extensions:
                    raise ValueError("Choose a supported file type or select All files.")
                if self.save:
                    if not path.parent.is_dir():
                        raise ValueError("Destination folder does not exist.")
                    if path.exists() and not path.is_file():
                        raise ValueError("Destination is not a regular file.")
                elif not path.is_file():
                    raise ValueError("File does not exist: {}".format(path))
            if str(path) not in paths:
                paths.append(str(path))
        return paths if self.multiple else paths[0]
