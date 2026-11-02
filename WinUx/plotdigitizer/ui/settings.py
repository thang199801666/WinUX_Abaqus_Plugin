"""Owned settings dialog for the Plot Digitizer workspace."""
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt import ToolWindow


class PlotDigitizerSettingsDialog(QtDialog):
    """Keep live settings controls separate from the digitizing workflow."""

    disclosure = ToolWindow.disclosure

    def __init__(self, owner):
        super().__init__(owner.view, "Plot Digitizer Settings", 460, 650,
                         parent=owner, modal=True)
        self.hide()
        self.setMinimumSize(400, 480)
        owner._build_plot_preferences_panel(self.content, ui=self)
        # The engine continues to synchronize these controls even while this
        # dialog is hidden. Ownership/callback gating stays on this dialog.
        owner._control_wrappers.update(self._control_wrappers)
        # Keep Close/reset reachable even when the expanded options scroll.
        self.button_box([("Close", self.hide, "primary", True)], left_actions=[
            ("Reset Display Defaults", owner._reset_plot_preferences, "secondary", False)])

    def reject(self):
        self.hide()

    def _close_from_escape(self):
        self.hide()

    def _close_from_native(self):
        self.hide()
