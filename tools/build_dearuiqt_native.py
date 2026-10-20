"""Build an isolated Windows multi-viewport backend with ``abaqus python``.

Never overwrites vendor/. Source and output directories must be outside vendor/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REVISION = "719d068967ace64eb9ff4171f2052a0799fd6c35"


def replace_once(path, before, after):
    text = path.read_text(encoding="utf-8")
    if after in text:
        return
    if text.count(before) != 1:
        raise RuntimeError("Pinned upstream patch no longer matches: {}".format(path))
    path.write_text(text.replace(before, after, 1), encoding="utf-8")


def patch_source(source):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != REVISION:
        raise RuntimeError("Build requires pinned Dear PyGui revision " + REVISION)
    src = source / "src"
    shutil.copy2(ROOT / "DearUIQt/native/dearuiqt_native_windows.h", src)
    # Patch only this opt-in fork, keeping DPG's existing public API unchanged.
    for name in ("dearpygui.cpp", "mvContainers.cpp", "mvGraphics_win32.cpp"):
        path = src / name
        text = path.read_text(encoding="utf-8")
        # Keep any precompiled header first.
        if '#include "dearuiqt_native_windows.h"' not in text:
            lines = text.splitlines(keepends=True)
            insertion = next((i + 1 for i, line in enumerate(lines) if "#pragma hdrstop" in line), 1)
            lines.insert(insertion, '#include "dearuiqt_native_windows.h"\n')
            path.write_text("".join(lines), encoding="utf-8")
    replace_once(src / "dearpygui.cpp", "\tmethods.clear();", """\tmethods.clear();
    methods.push_back({"dearuiqt_enable_native_windows", DearUIQtNative::enable, METH_NOARGS, nullptr});
    methods.push_back({"dearuiqt_native_windows_enabled", DearUIQtNative::isEnabled, METH_NOARGS, nullptr});
    methods.push_back({"dearuiqt_configure_native_window", DearUIQtNative::configure, METH_VARARGS, nullptr});
    methods.push_back({"dearuiqt_native_window_handle", DearUIQtNative::handle, METH_VARARGS, nullptr});""")
    replace_once(src / "dearpygui_commands.h", "\t\t\tImGui::DestroyContext();",
                 "\t\t\tDearUIQtNative::reset();\n\t\t\tImGui::DestroyContext();")
    replace_once(src / "dearpygui.cpp",
                 '    methods.push_back({"dearuiqt_native_window_handle", DearUIQtNative::handle, METH_VARARGS, nullptr});',
                 '    methods.push_back({"dearuiqt_native_window_handle", DearUIQtNative::handle, METH_VARARGS, nullptr});\n'
                 '    methods.push_back({"dearuiqt_native_input_state", DearUIQtNative::inputState, METH_NOARGS, nullptr});')
    # The commands header is included before our extension in dearpygui.cpp.
    path = src / "dearpygui_commands.h"
    replace_once(path, '#include "mvAppItemCommons.h"',
                 '#include "dearuiqt_native_windows.h"\n#include "mvAppItemCommons.h"')
    replace_once(src / "mvContainers.cpp", "    if (config.mainWindow)\n    {\n        ImGui::SetNextWindowBgAlpha",
                 "    DearUIQtNative::beforeWindow(item);\n    if (config.mainWindow)\n    {\n        ImGui::SetNextWindowBgAlpha")
    replace_once(src / "mvContainers.cpp", "        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));",
                 "        ImGui::SetNextWindowViewport(ImGui::GetMainViewport()->ID);\n        ImGui::SetNextWindowPos(ImGui::GetMainViewport()->Pos);")
    replace_once(src / "mvGraphics_win32.cpp", "\tImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());", """\tImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
    if (DearUIQtNative::enabled()) {
        ImGui::UpdatePlatformWindows();
        DearUIQtNative::synchronizeOwners();
        ImGui::RenderPlatformWindowsDefault();
    }""")
    # The first click can arrive before NewFrame's desktop hover polling has
    # switched from the owner viewport to the new dialog. Keep the event's
    # position and viewport together, before queuing the button-down itself.
    replace_once(source / "thirdparty/imgui/backends/imgui_impl_win32.cpp",
                 "        io.AddMouseSourceEvent(mouse_source);\n        io.AddMouseButtonEvent(button, true);",
                 """        // DearUIQt: bind the first press to its actual native viewport.
        if (io.ConfigFlags & ImGuiConfigFlags_ViewportsEnable) {
            POINT position = { (LONG)GET_X_LPARAM(lParam), (LONG)GET_Y_LPARAM(lParam) };
            ::ClientToScreen(hwnd, &position);
            io.AddMousePosEvent((float)position.x, (float)position.y);
            if (ImGuiViewport* viewport = ImGui_ImplWin32_FindViewportByPlatformHandle(ImGui::GetPlatformIO(), hwnd))
                io.AddMouseViewportEvent(viewport->ID);
        }
        io.AddMouseSourceEvent(mouse_source);
        io.AddMouseButtonEvent(button, true);""")
    # Overlay sources may retain an older checkout timestamp (copy2). Ensure
    # MSBuild recompiles the ABI consumers instead of silently relinking an old
    # implementation after an incremental overlay change.
    for name in ("dearuiqt_native_windows.h", "dearpygui.cpp", "mvContainers.cpp", "mvGraphics_win32.cpp"):
        (src / name).touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--generator", default="Visual Studio 18 2026")
    parser.add_argument("--patch-only", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    protected = (ROOT / "vendor").resolve()
    if source == protected or protected in source.parents or output == protected or protected in output.parents:
        raise RuntimeError("Production vendor/ is protected")
    patch_source(source)
    if args.patch_only:
        return
    build = source / "build-dearuiqt"
    subprocess.check_call([
        args.cmake, "-S", str(source), "-B", str(build), "-G", args.generator, "-A", "x64",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
        "-DMVDIST_ONLY=ON", "-DMV_PY_VERSION=3.10", "-DMVDPG_VERSION=2.3.1-dearuiqt-native1",
        "-DPython_ROOT_DIR=" + sys.prefix, "-DPython_INCLUDE_DIR=" + str(Path(sys.prefix) / "Include"),
        "-DPython_LIBRARY=" + str(Path(sys.prefix) / "libs/python310.lib"),
        "-DFT_WITH_ZLIB=OFF", "-DFT_WITH_BZIP2=OFF", "-DFT_WITH_PNG=OFF", "-DFT_WITH_HARFBUZZ=OFF",
        "-DCMAKE_DISABLE_FIND_PACKAGE_ZLIB=TRUE", "-DCMAKE_DISABLE_FIND_PACKAGE_BZip2=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PNG=TRUE", "-DCMAKE_DISABLE_FIND_PACKAGE_HarfBuzz=TRUE",
    ])
    subprocess.check_call([args.cmake, "--build", str(build), "--config", "Release", "--parallel", "4"])
    package = output / "dearpygui"
    package.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "dearpygui.py"):
        shutil.copy2(ROOT / "vendor/dearpygui" / name, package / name)
    binary = source / "cmake-build-local/DearPyGui/Release/_dearpygui.pyd"
    shutil.copy2(binary, package / binary.name)
    shutil.copy2(source / "LICENSE", output / "LICENSE-DearPyGui.txt")
    licenses = output / "licenses"
    licenses.mkdir(exist_ok=True)
    for dependency, name in (("imgui", "LICENSE.txt"), ("implot", "LICENSE"),
                             ("imnodes", "LICENSE.md"), ("ImGuiFileDialog", "LICENSE"),
                             ("freetype", "docs/LICENSE.TXT"), ("freetype", "docs/FTL.TXT")):
        candidate = source / "thirdparty" / dependency / name
        if candidate.is_file():
            shutil.copy2(candidate, licenses / (dependency + "-" + Path(name).name))
    (output / "dearuiqt_build.json").write_text(json.dumps({
        "upstream_revision": REVISION, "native_abi": 1,
        "python": sys.version, "python_cache_tag": sys.implementation.cache_tag,
        "extension_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }, indent=2), encoding="utf-8")
    print("DEARUIQT_NATIVE_BUILD_OK " + str(output), flush=True)


if __name__ == "__main__":
    main()
