from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog, QtTable
from .logic.odb import format_check_number as _number, format_vector as _vector, format_bytes as _bytes


class ODBCheckDialog(QtDialog):
    def __init__(self, view, result):
        self.result = dict(result or {})
        super().__init__(view, "Check ODB - {}".format(self.result.get("odb") or "ODB"), 900, 420, modal=False)
        self.header("ODB load and displacement check", str(self.result.get("odb") or ""))
        governing = self.result.get("governingReactionForce") or {}
        text = "No RF* History Output was found in this ODB."
        if governing:
            text = "Governing: {} = {}   {} = {}   Step: {}   Time: {}".format(
                governing.get("component", "RF"), _vector(governing.get("signedValue")),
                governing.get("uOutput") or "U", _vector(governing.get("uValue")),
                governing.get("step", "-"), _number(governing.get("time")))
        with self.section("Governing result") as summary:
            dpg.add_text(text, wrap=860, parent=summary)
            self.note("U is the same-direction displacement at the RF peak time.", parent=summary)
        self.table = QtTable(self.content, ("RF output", "RF value", "U output", "U value", "Step", "Time", "History region / node set"), height=-30)
        self.table.set_rows([(i, (row.get("rfOutput", ""), _vector(row.get("rfValue")),
            row.get("uOutput") or "-", _vector(row.get("uValue")), row.get("step", ""),
            _number(row.get("time")), row.get("historyRegion", "")))
            for i, row in enumerate(self.result.get("loadDisplacementRows") or [])])
        self.note("Analysis: {} s | Size: {} | Command: {} python".format(
            _number(self.result.get("analysisSeconds")), _bytes(self.result.get("fileSize", self.result.get("remoteSize"))),
            self.result.get("abaqusCommand") or ""))
        self.button_box([("Close", self.destroy, "secondary", False)])
