import json
import os
import subprocess
import sys
from pathlib import Path

from WinUx.services.odb_upgrade import (
    JSON_BEGIN,
    JSON_END,
    build_odb_upgrade_script,
    newest_first_abaqus_commands,
    parse_odb_upgrade_output,
)


def test_abaqus_commands_are_sorted_newest_first():
    commands = newest_first_abaqus_commands(
        ["abaqus", "abq2023", "abq2026", "abq2024hf2", "custom"])
    assert commands[:3] == ["abq2026", "abq2024hf2", "abq2023"]
    assert commands[-1] == "abaqus"


def test_parse_upgrade_payload():
    payload = {"mode": "check", "results": [{"path": "a.odb", "requiresUpgrade": True}]}
    output = "noise\n{}\n{}\n{}\n".format(
        JSON_BEGIN, json.dumps(payload), JSON_END)
    assert parse_odb_upgrade_output(output) == payload


def test_upgrade_helper_preserves_original_on_failure(tmp_path):
    (tmp_path / "odbAccess.py").write_text(
        "def isUpgradeRequiredForOdb(upgradeRequiredOdbPath): return True\n"
        "def upgradeOdb(existingOdbPath, upgradedOdbPath): "
        "raise RuntimeError('cannot convert database')\n",
        encoding="utf-8",
    )
    helper = tmp_path / "helper.py"
    helper.write_text(build_odb_upgrade_script(), encoding="utf-8")
    odb = tmp_path / "sample.odb"
    odb.write_text("ORIGINAL", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(helper), "upgrade", str(odb)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=True,
    )
    payload = parse_odb_upgrade_output(result.stdout)
    assert payload["results"][0]["status"] == "error"
    assert odb.read_text(encoding="utf-8") == "ORIGINAL"


def test_upgrade_helper_replaces_only_after_success(tmp_path):
    (tmp_path / "odbAccess.py").write_text(
        "def isUpgradeRequiredForOdb(upgradeRequiredOdbPath):\n"
        "    return open(upgradeRequiredOdbPath, 'r').read().startswith('OLD')\n"
        "def upgradeOdb(existingOdbPath, upgradedOdbPath):\n"
        "    data = open(existingOdbPath, 'r').read()\n"
        "    out = open(upgradedOdbPath, 'w'); out.write('NEW:' + data); out.close()\n",
        encoding="utf-8",
    )
    helper = tmp_path / "helper.py"
    helper.write_text(build_odb_upgrade_script(), encoding="utf-8")
    odb = tmp_path / "sample.odb"
    odb.write_text("OLD-data", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(helper), "upgrade", str(odb)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=True,
    )
    payload = parse_odb_upgrade_output(result.stdout)
    assert payload["results"][0]["status"] == "upgraded"
    assert odb.read_text(encoding="utf-8") == "NEW:OLD-data"
    assert not list(tmp_path.glob("*.winux-backup-*.odb"))
    assert not list(tmp_path.glob("*.winux-upgrade-*.odb"))


def test_parallel_upgrade_caps_workers_at_four():
    import threading
    import time
    from WinUx.services.odb_upgrade import run_parallel_odb_upgrades

    lock = threading.Lock()
    active = [0]
    peak = [0]

    def run_one(path):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(0.06)
            return {
                "mode": "upgrade",
                "results": [{
                    "path": path,
                    "name": path,
                    "status": "upgraded",
                    "requiresUpgrade": False,
                    "error": None,
                }],
            }
        finally:
            with lock:
                active[0] -= 1

    paths = ["{}.odb".format(index) for index in range(9)]
    payload = run_parallel_odb_upgrades(paths, run_one, max_workers=99)
    assert payload["workerCount"] == 4
    assert peak[0] <= 4
    assert peak[0] >= 2
    assert [row["path"] for row in payload["results"]] == paths


def test_parallel_upgrade_failure_does_not_cancel_other_odbs():
    from WinUx.services.odb_upgrade import run_parallel_odb_upgrades

    def run_one(path):
        if path == "bad.odb":
            raise RuntimeError("conversion failed")
        return {
            "mode": "upgrade",
            "results": [{
                "path": path,
                "name": path,
                "status": "upgraded",
                "requiresUpgrade": False,
                "error": None,
            }],
        }

    payload = run_parallel_odb_upgrades(
        ["a.odb", "bad.odb", "c.odb"], run_one, max_workers=4)
    assert payload["workerCount"] == 3
    assert payload["results"][0]["status"] == "upgraded"
    assert payload["results"][1]["status"] == "error"
    assert "conversion failed" in payload["results"][1]["error"]
    assert payload["results"][2]["status"] == "upgraded"


def test_upgrade_helper_can_keep_original_and_create_copy(tmp_path):
    (tmp_path / "odbAccess.py").write_text(
        "def isUpgradeRequiredForOdb(upgradeRequiredOdbPath): return True\n"
        "def upgradeOdb(existingOdbPath, upgradedOdbPath):\n"
        "    data = open(existingOdbPath, 'r').read()\n"
        "    out = open(upgradedOdbPath, 'w'); out.write('NEW:' + data); out.close()\n",
        encoding="utf-8",
    )
    helper = tmp_path / "helper.py"
    helper.write_text(build_odb_upgrade_script(), encoding="utf-8")
    odb = tmp_path / "sample.odb"
    odb.write_text("OLD-data", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(helper), "upgrade", "keep", str(odb)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, check=True)
    payload = parse_odb_upgrade_output(result.stdout)
    row = payload["results"][0]
    assert row["status"] == "upgraded"
    assert row["overwritten"] is False
    assert odb.read_text(encoding="utf-8") == "OLD-data"
    upgraded = tmp_path / "sample_upgraded.odb"
    assert upgraded.read_text(encoding="utf-8") == "NEW:OLD-data"
    assert Path(row["outputPath"]) == upgraded


def test_upgrade_helper_keep_mode_avoids_existing_output(tmp_path):
    (tmp_path / "odbAccess.py").write_text(
        "def isUpgradeRequiredForOdb(upgradeRequiredOdbPath): return True\n"
        "def upgradeOdb(existingOdbPath, upgradedOdbPath):\n"
        "    out = open(upgradedOdbPath, 'w'); out.write('NEW'); out.close()\n",
        encoding="utf-8",
    )
    helper = tmp_path / "helper.py"
    helper.write_text(build_odb_upgrade_script(), encoding="utf-8")
    odb = tmp_path / "sample.odb"
    odb.write_text("OLD", encoding="utf-8")
    existing = tmp_path / "sample_upgraded.odb"
    existing.write_text("KEEP-ME", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(helper), "upgrade", "keep", str(odb)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, check=True)
    payload = parse_odb_upgrade_output(result.stdout)
    row = payload["results"][0]
    assert existing.read_text(encoding="utf-8") == "KEEP-ME"
    assert (tmp_path / "sample_upgraded_2.odb").read_text(encoding="utf-8") == "NEW"
    assert Path(row["outputPath"]).name == "sample_upgraded_2.odb"
