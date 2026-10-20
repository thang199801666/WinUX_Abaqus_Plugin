// DearUIQt's Windows multi-viewport extension for pinned Dear PyGui 2.3.1.
// The Python API remains opt-in; stock WinUx deployments are not changed.
#pragma once
#include "mvContext.h"
#include "mvViewport.h"
#include "mvContainers.h"
#include "mvItemRegistry.h"
#include <imgui_internal.h>
#include <Windows.h>
#include <thread>
#include <unordered_map>
#include <unordered_set>

namespace DearUIQtNative {
struct Window {
    mvUUID owner = 0;
    bool modal = false;
    std::string name;
};
inline std::unordered_map<mvUUID, Window> windows;
inline std::unordered_set<HWND> disabledOwners;
inline std::thread::id guiThread;

inline bool enabled() {
    return GContext && ImGui::GetCurrentContext() &&
        (ImGui::GetIO().ConfigFlags & ImGuiConfigFlags_ViewportsEnable);
}

inline bool requireGuiThread() {
    if (!GContext || !ImGui::GetCurrentContext()) {
        PyErr_SetString(PyExc_RuntimeError, "Create a DearUIQt context first");
        return false;
    }
    if (guiThread != std::this_thread::get_id()) {
        PyErr_SetString(PyExc_RuntimeError, "Native windows require the owning GUI thread");
        return false;
    }
    return true;
}

inline ImGuiViewport* viewportFor(mvUUID item) {
    auto found = windows.find(item);
    if (found == windows.end()) return nullptr;
    auto window = ImGui::FindWindowByName(found->second.name.c_str());
    if (!window || !window->Active || window->Viewport == ImGui::GetMainViewport()) return nullptr;
    return window->Viewport;
}

inline void beforeWindow(mvAppItem& item) {
    if (!enabled()) return;
    auto found = windows.find(item.uuid);
    if (found == windows.end()) return;
    found->second.name = item.info.internalLabel;
    ImGuiWindowClass cls;
    cls.ClassId = ImGui::GetID(item.info.internalLabel.c_str());
    cls.DockingAllowUnclassed = false;
    cls.ViewportFlagsOverrideSet = ImGuiViewportFlags_NoAutoMerge;
    cls.ViewportFlagsOverrideClear = ImGuiViewportFlags_NoDecoration;
    auto parent = viewportFor(found->second.owner);
    cls.ParentViewportId = parent ? parent->ID : ImGui::GetMainViewport()->ID;
    ImGui::SetNextWindowClass(&cls);
}

inline void synchronizeOwners() {
    std::unordered_set<HWND> needed;
    for (auto it = windows.begin(); it != windows.end();) {
        auto item = GetItem(*GContext->itemRegistry, it->first);
        if (!item) { it = windows.erase(it); continue; }
        auto viewport = viewportFor(it->first);
        if (viewport && item->config.show) {
            auto handle = static_cast<HWND>(viewport->PlatformHandleRaw);
            auto parentViewport = viewportFor(it->second.owner);
            if (!parentViewport) parentViewport = ImGui::GetMainViewport();
            auto parent = static_cast<HWND>(parentViewport->PlatformHandleRaw);
            if (handle && parent && handle != parent) {
                // Ownership is structural. Rewriting GWLP_HWNDPARENT on every
                // frame causes USER32/DWM to reset non-client hot tracking on
                // some Windows builds, which makes the native Close button
                // flash continuously while hovered. Touch the owner only when
                // the actual relationship changed.
                if (GetWindow(handle, GW_OWNER) != parent)
                    SetWindowLongPtrW(handle, GWLP_HWNDPARENT, reinterpret_cast<LONG_PTR>(parent));
                if (it->second.modal) needed.insert(parent);
            }
        }
        ++it;
    }
    for (auto owner : disabledOwners)
        if (!needed.count(owner) && IsWindow(owner)) EnableWindow(owner, TRUE);
    for (auto owner : needed)
        if (IsWindowEnabled(owner)) { EnableWindow(owner, FALSE); disabledOwners.insert(owner); }
    for (auto it = disabledOwners.begin(); it != disabledOwners.end();)
        if (!needed.count(*it)) it = disabledOwners.erase(it); else ++it;

    // Disabling an owner HWND does not disable Dear ImGui's queued navigation
    // requests. A background editor can have requested keyboard focus just
    // before a modal opened, and apply it on the following frame. Keep the
    // shared ImGui context's focus inside the enabled modal, without changing
    // desktop foreground or overriding a focused control/popup in that modal.
    auto nav = ImGui::GetCurrentContext()->NavWindow;
    auto navHandle = nav && nav->Viewport
        ? static_cast<HWND>(nav->Viewport->PlatformHandleRaw) : nullptr;
    if (navHandle && disabledOwners.count(navHandle)) {
        ImGuiWindow* target = nullptr;
        HWND foreground = GetForegroundWindow();
        for (const auto& entry : windows) {
            if (!entry.second.modal) continue;
            auto item = GetItem(*GContext->itemRegistry, entry.first);
            auto viewport = viewportFor(entry.first);
            if (!item || !item->config.show || !viewport) continue;
            auto handle = static_cast<HWND>(viewport->PlatformHandleRaw);
            if (!handle || !IsWindowEnabled(handle)) continue;
            auto candidate = ImGui::FindWindowByName(entry.second.name.c_str());
            bool ownsDisabledNav = false;
            std::unordered_set<HWND> seen;
            for (auto owner = GetWindow(handle, GW_OWNER); owner && seen.insert(owner).second;
                 owner = GetWindow(owner, GW_OWNER)) {
                if (owner == navHandle) { ownsDisabledNav = true; break; }
            }
            if (candidate && (ownsDisabledNav || handle == foreground)) {
                target = candidate;
                if (handle == foreground) break;
            }
        }
        if (target && nav->RootWindow != target->RootWindow)
            ImGui::FocusWindow(target);
    }
}

inline void reset() {
    for (auto owner : disabledOwners) if (IsWindow(owner)) EnableWindow(owner, TRUE);
    disabledOwners.clear();
    windows.clear();
    guiThread = {};
}

inline PyObject* enable(PyObject*, PyObject*) {
    if (!GContext || !ImGui::GetCurrentContext()) {
        PyErr_SetString(PyExc_RuntimeError, "Create a DearUIQt context first");
        return nullptr;
    }
    if (guiThread != std::thread::id{} && !requireGuiThread()) return nullptr;
    if (GContext->viewport && GContext->viewport->shown) {
        PyErr_SetString(PyExc_RuntimeError, "Enable native windows before showing the main viewport");
        return nullptr;
    }
    guiThread = std::this_thread::get_id();
    ImGui::GetIO().ConfigFlags |= ImGuiConfigFlags_ViewportsEnable;
    ImGui::GetIO().ConfigViewportsNoAutoMerge = false;
    ImGui::GetIO().ConfigViewportsNoDefaultParent = false;
    GContext->IO.manualCallbacks = true;
    Py_RETURN_TRUE;
}

inline PyObject* isEnabled(PyObject*, PyObject*) { return PyBool_FromLong(enabled()); }

inline PyObject* configure(PyObject*, PyObject* args) {
    unsigned long long id, owner = 0;
    int modal = 0;
    if (!PyArg_ParseTuple(args, "K|Kp", &id, &owner, &modal)) return nullptr;
    if (!requireGuiThread()) return nullptr;
    if (!enabled()) {
        PyErr_SetString(PyExc_RuntimeError, "Enable native windows first");
        return nullptr;
    }
    std::lock_guard<std::recursive_mutex> lock(GContext->mutex);
    auto item = GetItem(*GContext->itemRegistry, id);
    if (!item || item->type != mvAppItemType::mvWindowAppItem || id == owner) {
        PyErr_SetString(PyExc_ValueError, "Expected a top-level window and a different owner");
        return nullptr;
    }
    if (owner && windows.find(owner) == windows.end()) {
        auto parent = GetItem(*GContext->itemRegistry, owner);
        if (!parent || parent->type != mvAppItemType::mvWindowAppItem ||
                !static_cast<mvWindowAppItem*>(parent)->configData.mainWindow) {
            PyErr_SetString(PyExc_ValueError, "Owner must be a native window or the primary window");
            return nullptr;
        }
    }
    std::unordered_set<mvUUID> ancestors;
    for (auto current = owner; current && windows.count(current); current = windows.at(current).owner) {
        if (current == id || !ancestors.insert(current).second) {
            PyErr_SetString(PyExc_ValueError, "Native window ownership cannot contain a cycle");
            return nullptr;
        }
    }
    auto window = static_cast<mvWindowAppItem*>(item);
    if (window->configData.mainWindow) {
        PyErr_SetString(PyExc_ValueError, "The primary window cannot be a secondary native window");
        return nullptr;
    }
    // OS caption/resize/close replace the ImGui window's own caption controls.
    // The native HWND must also be the *only* owner of move gestures. Without
    // NoMove, Dear ImGui treats an unoccupied part of this title-less client
    // window as a drag surface and can move the platform viewport when the user
    // grabs labels, padding or other dialog content.  NoMove disables only the
    // ImGui/client-area move path; the Win32 caption still performs normal OS
    // move/drag behaviour.
    window->configData.modal = false;
    window->configData.popup = false;
    window->configData.windowflags |=
        ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoDocking;
    windows[id] = {owner, bool(modal), item->info.internalLabel};
    Py_RETURN_NONE;
}

inline PyObject* handle(PyObject*, PyObject* args) {
    unsigned long long id;
    if (!PyArg_ParseTuple(args, "K", &id)) return nullptr;
    if (!requireGuiThread()) return nullptr;
    auto viewport = viewportFor(id);
    return PyLong_FromVoidPtr(viewport ? viewport->PlatformHandleRaw : nullptr);
}

inline PyObject* inputState(PyObject*, PyObject*) {
    if (!requireGuiThread()) return nullptr;
    auto& g = *ImGui::GetCurrentContext();
    return Py_BuildValue("{s:s,s:s,s:s,s:I,s:I,s:I,s:I,s:i,s:i,s:i,s:i,s:f,s:f}",
        "hovered_window", g.HoveredWindow ? g.HoveredWindow->Name : "",
        "nav_window", g.NavWindow ? g.NavWindow->Name : "",
        "nav_root", g.NavWindow ? g.NavWindow->RootWindow->Name : "",
        "nav_viewport", g.NavWindow && g.NavWindow->Viewport ? g.NavWindow->Viewport->ID : 0,
        "mouse_viewport", g.MouseViewport ? g.MouseViewport->ID : 0,
        "hovered_viewport", g.IO.MouseHoveredViewport,
        "active_id", g.ActiveId,
        "nav_mouse_hover", g.NavHighlightItemUnderNav,
        "mouse_down", g.IO.MouseDown[0],
        "mouse_owned", g.IO.MouseDownOwned[0],
        "focus_lost", g.IO.AppFocusLost,
        "mouse_x", g.IO.MousePos.x, "mouse_y", g.IO.MousePos.y);
}
} // namespace DearUIQtNative
