"""Standard WinUx regression runner (all suites via ``abaqus python``).

WinUx requires its test runtime to be the Abaqus-bundled Python, and a few
GUI suites historically crashed when several heavy modules shared one
process.  This runner therefore starts every test module in its own short
lived ``abaqus python`` subprocess, keeps one crash from destroying the
whole run, and reports one compact line per module.

Usage (run from the WinUx root):

    abaqus python tools/run_tests.py                 # full suite
    abaqus python tools/run_tests.py --jobs 4        # parallel subprocesses
    abaqus python tools/run_tests.py job_plots check # substring filters
    abaqus python tools/run_tests.py --retest-from reports/test_runner.json

Exit code is non-zero when any module fails, errors, crashes or times out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "reports" / "test_runner.json"
DEFAULT_TIMEOUT = 300.0
# Simultaneous "abaqus python" bootstraps.  Plain CPython startup, no
# license tokens; 4 keeps most machines responsive.
DEFAULT_JOBS = 4


def module_name(path: Path) -> str:
    return "tests.{}".format(path.stem)


def launch_argv(launcher: str, mod: str):
    if launcher == "abaqus":
        return ["abaqus", "python", "tools/pytestlite.py", mod]
    return [sys.executable, "tools/pytestlite.py", mod]


def classify_module(output: str):
    """Return (tests, status, details) for one child line set."""
    ran = re.search(r"^Ran (\d+) tests? .*$", output, re.MULTILINE)
    tests = int(ran.group(1)) if ran else 0
    failures = re.findall(r"^(FAIL|ERROR): ([\w.]+)", output, re.MULTILINE)
    if ran is None:
        return tests, "crash", "no unittest summary in output"
    if failures:
        return tests, "failed", ", ".join(
            "{}/{}".format(kind, name) for kind, name in failures)
    if "OK" in output:
        return tests, "passed", ""
    return tests, "unknown", "output ended without OK"


def run_one(launcher: str, path: Path, timeout: float):
    mod = module_name(path)
    started = time.monotonic()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            launch_argv(launcher, mod),
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=creationflags,
        )
        elapsed = time.monotonic() - started
        text = proc.stdout.decode("utf-8", "replace")
        tests, status, details = classify_module(text)
        if status == "passed" and proc.returncode != 0:
            status, details = "unknown", "exit {}".format(proc.returncode)
        if status != "passed":
            _save_failure_output(path, text)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        tests, status, details = 0, "timeout", "exceeded {:.0f}s".format(timeout)
    except (OSError, ValueError) as exc:
        elapsed = time.monotonic() - started
        tests, status, details = 0, "crash", str(exc)
    return {
        "module": path.name,
        "tests": tests,
        "status": status,
        "seconds": round(elapsed, 2),
        "details": details,
    }


FAILURES_DIR = ROOT / "reports" / "failures"


def _save_failure_output(path: Path, output: str):
    try:
        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        (FAILURES_DIR / (path.stem + ".txt")).write_text(
            output, encoding="utf-8")
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filters", nargs="*", help="module-name substrings")
    parser.add_argument("--exclude", nargs="*", default=[],
                        help="module-name substrings to skip")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--launcher", choices=("auto", "abaqus", "exe"),
                        default="abaqus")
    parser.add_argument("--report", dest="report", default=str(DEFAULT_REPORT))
    parser.add_argument("--quiet", action="store_true",
                        help="suppress PASS lines")
    parser.add_argument("--retest-from", dest="retest_from", default=None,
                        metavar="REPORT",
                        help="run only modules that were not passed in the given report")
    parser.add_argument("--list", action="store_true",
                        help="only print the module list")
    parser.add_argument("--include-native", action="store_true",
                        help="also run suites listed in tests/native_runtime_modules.txt")
    args = parser.parse_args()
    global _QUIET
    _QUIET = args.quiet

    terms = tuple(args.filters) or tuple()
    modules = sorted((ROOT / "tests").glob("test_*.py"))
    if terms:
        modules = [path for path in modules
                   if any(term in path.name for term in terms)]
    modules = [path for path in modules
               if not any(term in path.name for term in args.exclude)]
    native_list = ROOT / "tests" / "native_runtime_modules.txt"
    native_names = set()
    if native_list.exists():
        native_names = {line.strip() for line in
                        native_list.read_text(encoding="utf-8").splitlines()
                        if line.strip()}
    included_native = set()
    if native_names and not args.include_native:
        kept = []
        for path in modules:
            if path.name in native_names:
                included_native.add(path.name)
            else:
                kept.append(path)
        modules = kept
    if args.retest_from:
        previous = json.loads(Path(args.retest_from).read_text(encoding="utf-8"))
        bad_names = {entry["module"] for entry in previous.get("results", [])
                     if entry.get("status") != "passed"}
        modules = [path for path in modules if path.name in bad_names]
    if args.list:
        print("\n".join(path.name for path in modules))
        return 0
    if not modules:
        print("No test modules matched filters: {}".format(args.filters))
        return 2

    launcher = args.launcher
    if launcher == "abaqus":
        # Inside "abaqus python" the wrapper is preferred (it exports the
        # full Abaqus environment).  Children call it independently.
        argv_probe = ["abaqus", "python", "-c", "print(1)"]
        try:
            probe = subprocess.run(
                argv_probe, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=60.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
            if probe.returncode != 0 and b"1" not in probe.stdout:
                launcher = "exe"
        except (OSError, subprocess.SubprocessError):
            launcher = "exe"

    total_started = time.monotonic()
    results = []
    if args.jobs <= 1:
        for path in modules:
            result = run_one(launcher, path, args.timeout)
            results.append(result)
            print_result(result)
            sys.stdout.flush()
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(run_one, launcher, path, args.timeout): path
                       for path in modules}
            for future in futures:  # completion order keeps progress flowing
                result = future.result()
                results.append(result)
                print_result(result)
                sys.stdout.flush()

    results.sort(key=lambda item: item["module"])

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"launcher": launcher, "results": results}, indent=1),
        encoding="utf-8")

    counts = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    bad = [result for result in results if result["status"] != "passed"]
    duration = time.monotonic() - total_started
    summary = (
        "Ran {} modules in {:.0f}s: {} passed, {} bad, {} native-runtime skipped."
        .format(len(results) + len(included_native), duration,
                counts.get("passed", 0), len(bad), len(included_native)))
    if bad:
        print("")
        for result in bad:
            print("BAD  {} ({} tests, {}s) {}".format(
                result["module"], result["tests"], result["seconds"],
                result["details"]))
    print("")
    print("RUNNER " + summary + " Report: {}".format(report_path))
    return 1 if bad else 0


def print_result(result):
    if result["status"] == "passed":
        if not _QUIET:
            print("PASS {} ({} tests, {:.1f}s)".format(
                result["module"], result["tests"], result["seconds"]))
    else:
        print("FAIL {} ({} tests, {:.1f}s) {}".format(
            result["module"], result["tests"], result["seconds"],
            result["details"]))


_QUIET = False


if __name__ == "__main__":
    raise SystemExit(main())
