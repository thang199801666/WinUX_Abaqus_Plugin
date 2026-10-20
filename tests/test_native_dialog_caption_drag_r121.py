from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "DearUIQt/native/dearuiqt_native_windows.h"
RUNTIME = ROOT / "DearUIQt/native/runtime/cp310-win_amd64"
BINARY = RUNTIME / "dearpygui/_dearpygui.pyd"
MANIFEST = RUNTIME / "dearuiqt_build.json"

# Compiled configure() instruction for:
# windowflags |= NoTitleBar | NoMove | NoDocking
_PATCHED_FLAGS = bytes.fromhex("81 8f 58 02 00 00 05 00 08 00")
_OLD_FLAGS = bytes.fromhex("81 8f 58 02 00 00 01 00 08 00")


def test_native_dialogs_disable_imgui_client_area_movement():
    source = HEADER.read_text(encoding="utf-8")
    assert "ImGuiWindowFlags_NoTitleBar" in source
    assert "ImGuiWindowFlags_NoMove" in source
    assert "ImGuiWindowFlags_NoDocking" in source
    # The comment records the architectural intent: only Win32 non-client
    # caption hit testing should own top-level movement.
    assert "Win32 caption still performs normal OS" in source


def test_bundled_runtime_has_caption_only_drag_flag_patch():
    data = BINARY.read_bytes()
    assert data.count(_PATCHED_FLAGS) == 1
    assert data.count(_OLD_FLAGS) == 0


def test_caption_drag_runtime_manifest_matches_binary():
    metadata = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert metadata["runtime_patch"] == "owner-sync-caption-only-drag-r121"
    assert metadata["extension_sha256"] == hashlib.sha256(BINARY.read_bytes()).hexdigest()
