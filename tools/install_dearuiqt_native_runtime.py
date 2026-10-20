"""Install a verified native runtime beside DearUIQt, without replacing vendor/."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    source = args.runtime.resolve()
    metadata = json.loads((source / "dearuiqt_build.json").read_text(encoding="utf-8"))
    binary = source / "dearpygui/_dearpygui.pyd"
    if (metadata.get("native_abi") != 1 or metadata.get("python_cache_tag") != sys.implementation.cache_tag
            or metadata.get("extension_sha256") != hashlib.sha256(binary.read_bytes()).hexdigest()):
        raise RuntimeError("Native runtime ABI/hash validation failed")
    abi = "cp{}{}-win_amd64".format(*sys.version_info[:2])
    target = Path(__file__).resolve().parents[1] / "DearUIQt/native/runtime" / abi
    if target.exists():
        current = target / "dearuiqt_build.json"
        current_binary = target / "dearpygui/_dearpygui.pyd"
        if (not current.is_file() or json.loads(current.read_text(encoding="utf-8")) != metadata
                or not current_binary.is_file()
                or hashlib.sha256(current_binary.read_bytes()).hexdigest() != metadata["extension_sha256"]):
            raise RuntimeError("A different installed runtime already exists; explicit upgrade is required")
        print("WINUX_NATIVE_RUNTIME_ALREADY_INSTALLED " + str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=abi + ".stage-", dir=str(target.parent)))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print("WINUX_NATIVE_RUNTIME_INSTALLED " + str(target))


if __name__ == "__main__":
    main()
