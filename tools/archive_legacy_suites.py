"""Retire superseded revision-snapshot suites into tests/legacy/.

Policy (agreed 2026-10-18): every revision-snapshot family keeps only the
latest revision, which must express the *current* contract.  Older revisions
assert intentionally superseded states and are parked here, outside the
``tests/test_*.py`` discovery glob, so ``tools/run_tests.py`` skips them while
the files stay available for archaeology.

Old framework-phase suites (``imgui_qt_*``, ``legacy_visual_restore_phase*``,
``startup_hotfix_phase16``, ``phase2_optimizations``,
``modern_dialog_phase3``) targeted ``WinUx/ui/framework`` paths that were
physically replaced by the ``DearUIQt`` package; the current contracts live in
the ``test_dearuiqt_*`` suites.

Archived suites can still be run manually:

    abaqus python tools/pytestlite.py tests.legacy.test_folder_browser_qt_visual_rev52
"""
import shutil
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"
LEGACY = TESTS / "legacy"

ARCHIVE = [
    # folder_browser_qt_visual — latest rev53 kept at tests/ root
    "test_folder_browser_qt_visual_rev38.py",
    "test_folder_browser_qt_visual_rev40.py",
    "test_folder_browser_qt_visual_rev41.py",
    "test_folder_browser_qt_visual_rev42.py",
    "test_folder_browser_qt_visual_rev43.py",
    "test_folder_browser_qt_visual_rev44.py",
    "test_folder_browser_qt_visual_rev45.py",
    "test_folder_browser_qt_visual_rev46.py",
    "test_folder_browser_qt_visual_rev47.py",
    "test_folder_browser_qt_visual_rev48.py",
    "test_folder_browser_qt_visual_rev49.py",
    "test_folder_browser_qt_visual_rev50.py",
    "test_folder_browser_qt_visual_rev51.py",
    "test_folder_browser_qt_visual_rev52.py",
    # folder_browser_polish — latest rev37 kept
    "test_folder_browser_polish_rev34.py",
    "test_folder_browser_polish_rev35.py",
    # ssh_console_context_menu — latest rev38 kept
    "test_ssh_console_context_menu_rev27.py",
    "test_ssh_console_context_menu_rev28.py",
    "test_ssh_console_context_menu_rev29.py",
    "test_ssh_console_context_menu_rev31.py",
    "test_ssh_console_context_menu_rev32.py",
    "test_ssh_console_context_menu_rev33.py",
    "test_ssh_console_context_menu_rev34.py",
    "test_ssh_console_context_menu_rev35.py",
    "test_ssh_console_context_menu_rev36.py",
    "test_ssh_console_context_menu_rev37.py",
    # ssh_console_line_editor — latest r63 kept
    "test_ssh_console_line_editor_r62.py",
    # qt_component_polish — latest rev16 kept
    "test_qt_component_polish_rev7.py",
    "test_qt_component_polish_rev8.py",
    "test_qt_component_polish_rev9.py",
    "test_qt_component_polish_rev10.py",
    "test_qt_component_polish_rev11.py",
    "test_qt_component_polish_rev13.py",
    "test_qt_component_polish_rev14.py",
    "test_qt_component_polish_rev15.py",
    # transfer_center — rev61 (full width) + v2 + redesign kept
    "test_transfer_center_layout_rev41.py",
    "test_transfer_center_progress_centering_rev42.py",
    "test_transfer_center_draw_overlay_rev43.py",
    "test_transfer_center_custom_progress_rev44.py",
    "test_transfer_center_layout_rev45.py",
    "test_transfer_center_visuals_rev46.py",
    "test_transfer_center_balance_rev47.py",
    "test_transfer_center_progress_button_height_rev48.py",
    "test_transfer_center_fixed_center_overlay_rev49.py",
    "test_transfer_center_completion_cleanup_rev50.py",
    # qt_header_column — menu rev19 + uniform_fill rev23 + autowidth rev22 kept
    "test_qt_header_column_autowidth_rev20.py",
    "test_qt_header_column_autowidth_rev21.py",
    # qt_toolbar_button_alignment — rev18 kept
    "test_qt_toolbar_button_alignment_rev17.py",
    # Old "imgui_qt framework" phase suites — the WinUx/ui/framework tree they
    # describe was replaced by the DearUIQt package (contracts moved to
    # test_dearuiqt_*); the redirected path aliases no longer carry meaning.
    "test_imgui_qt_foundation.py",
    "test_imgui_qt_phase3.py",
    "test_imgui_qt_phase4.py",
    "test_imgui_qt_phase5.py",
    "test_imgui_qt_phase6_explorer.py",
    "test_imgui_qt_phase8_command_chrome.py",
    "test_imgui_qt_phase9_shell.py",
    "test_imgui_qt_form_controls_phase10.py",
    "test_imgui_qt_form_controls_phase11.py",
    "test_imgui_qt_form_controls_phase12.py",
    "test_legacy_visual_restore_phase14.py",
    "test_legacy_visual_restore_phase15.py",
    "test_startup_hotfix_phase16.py",
    "test_phase2_optimizations.py",
    "test_modern_dialog_phase3.py",
]


def main():
    LEGACY.mkdir(exist_ok=True)
    moved, missing = [], []
    for name in ARCHIVE:
        source = TESTS / name
        if source.exists():
            shutil.move(str(source), str(LEGACY / name))
            moved.append(name)
        else:
            missing.append(name)
    print("moved:", len(moved))
    for name in moved:
        print("  ", name)
    if missing:
        print("MISSING:")
        for name in missing:
            print("  ", name)


if __name__ == "__main__":
    main()
