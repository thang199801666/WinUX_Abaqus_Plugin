"""Read-only comparison of submission sources against an archived WinUx release."""
import difflib
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    archive = root.parent / "WinUx-0.0.1.zip"
    paths = (
        "WinUx/controllers/job_submission.py", "WinUx/services/remote_jobs.py",
        "WinUx/dialogs/logic/job_manager.py", "WinUx/dialogs/job_manager_form.py",
        "WinUx/runtime/operation_context.py", "WinUx/services/ssh_serialization.py",
        "WinUx/controllers/job_schedule.py",
    )
    with zipfile.ZipFile(archive) as source:
        for path in paths:
            if "WinUx/" + path not in source.namelist():
                print(path, "NOT PRESENT in archive")
                continue
            old = source.read("WinUx/" + path).decode("utf-8-sig").splitlines()
            current = (root / path).read_text(encoding="utf-8-sig").splitlines()
            changes = list(difflib.unified_diff(old, current, fromfile="0.0.1/" + path,
                                                tofile="current/" + path, n=3))
            print(path, "IDENTICAL" if not changes else "CHANGED")
            for line in changes:
                print(line)


if __name__ == "__main__":
    main()
