"""Local filesystem queries and mutations used by the explorer."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Sequence

from .items import FileItem


class FileSystemModel:
    """All local filesystem state and mutations used by the explorer."""

    _INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
    _RESERVED_NAMES = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {"COM{}".format(number) for number in range(1, 10)}
        | {"LPT{}".format(number) for number in range(1, 10)}
    )

    def list_directory(self, folder: Path) -> List[FileItem]:
        folder = self.normalize(folder)
        result: List[FileItem] = []
        with os.scandir(str(folder)) as entries:
            for entry in entries:
                try:
                    stat = entry.stat(follow_symlinks=False)
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                result.append(FileItem(
                    entry.name,
                    Path(entry.path),
                    is_dir,
                    stat.st_size,
                    stat.st_mtime,
                ))
        return sorted(
            result,
            key=lambda item: (not item.is_dir, item.name.casefold()),
        )

    @staticmethod
    def normalize(path) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(str(path).strip()))
        return Path(os.path.abspath(expanded))

    def transfer(
            self, sources: Sequence[Path], destination: Path,
            move=False) -> List[Path]:
        destination = self.normalize(destination)
        if not destination.is_dir():
            raise OSError("Destination folder does not exist")
        created = []
        for source_value in sources:
            source = self.normalize(source_value)
            target = self.unique_target(destination / source.name)
            if self._same_or_child(destination, source):
                raise OSError("Cannot copy a folder into itself")
            if move:
                created.append(Path(shutil.move(str(source), str(target))))
            elif source.is_dir():
                created.append(Path(shutil.copytree(str(source), str(target))))
            else:
                created.append(Path(shutil.copy2(str(source), str(target))))
        return created

    @staticmethod
    def unique_target(target: Path) -> Path:
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        for number in range(2, 10000):
            candidate = target.with_name(
                "{} ({}){}".format(stem, number, suffix))
            if not candidate.exists():
                return candidate
        raise OSError("Could not create a unique file name")

    def rename(self, source: Path, new_name: str) -> Path:
        source = self.normalize(source)
        new_name = self.validate_name(new_name)
        target = source.with_name(new_name)
        if target == source:
            return source
        same_windows_path = (
            os.path.normcase(os.path.abspath(str(target)))
            == os.path.normcase(os.path.abspath(str(source)))
        )
        if target.exists() and not same_windows_path:
            raise OSError("A file with that name already exists")
        return source.rename(target)

    @classmethod
    def validate_name(cls, name: str) -> str:
        """Validate a filename using Windows Explorer's visible rules."""
        name = str(name).strip()
        if not name or name in (".", ".."):
            raise ValueError("A file name cannot be blank")
        if name.endswith((".", " ")):
            raise ValueError(
                "A file name cannot end with a period or space")
        if (
            any(character in cls._INVALID_NAME_CHARS for character in name)
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError(
                'A file name cannot contain any of these characters: '
                '\\ / : * ? " < > |')
        reserved_stem = name.split(".", 1)[0].rstrip(" .").upper()
        if reserved_stem in cls._RESERVED_NAMES:
            raise ValueError(
                '"{}" is a reserved system name'.format(reserved_stem))
        return name

    @staticmethod
    def new_folder(parent: Path) -> Path:
        target = FileSystemModel.unique_target(parent / "New folder")
        target.mkdir()
        return target

    @staticmethod
    def new_file(parent: Path) -> Path:
        target = FileSystemModel.unique_target(parent / "New file")
        target.touch()
        return target

    @staticmethod
    def delete(paths: Iterable[Path]) -> None:
        for path in paths:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(str(path))
            else:
                path.unlink()

    @staticmethod
    def _same_or_child(candidate: Path, parent: Path) -> bool:
        try:
            candidate.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False
