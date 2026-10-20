"""Child-window geometry must stay in absolute renderer space.

Dear PyGui 2.x reports child-window pos relative to the nearest parent
window and omits rect_min. Backends that trusted ``get_item_state["pos"]``
directly produced (0,0)-origin panes, which silently disabled every
ExplorerListView click hit test. The retained wrapper now reconstructs the
parent chain (``dpg_window_rect``) whenever item types declare window
bounds.
"""
import unittest

from tests.test_dearuiqt_modelview_r79 import FakeBackend


class ReconstructingBackend(FakeBackend):
    """FakeBackend that emulates DPG 2.x child-window state semantics."""

    def __init__(self):
        super().__init__()
        self.state = {}

    def set_window_state(self, tag, pos, rect_size):
        self.state[tag] = {"pos": list(pos), "rect_size": list(rect_size)}

    def get_item_state(self, tag):
        return dict(self.state.get(tag, {}))

    def get_item_info(self, tag):
        # QFrame/create surfaces map to mvChildWindow; add_window to the root.
        kind = "mvWindowAppItem" if tag not in self.state else "mvChildWindow"
        return {"type": "mvAppItemType::" + kind}

    def get_item_parent(self, tag):
        return self.parents.get(tag)


class GlobalPosReconstructionTests(unittest.TestCase):
    def test_relative_child_window_pos_becomes_absolute(self):
        from DearUIQt.widgets import QFrame
        backend = ReconstructingBackend()
        main = backend.add_window()
        backend.set_window_state(main, (74, 131), (834, 581))
        frame = QFrame(parent=main, backend=backend)
        backend.set_window_state(frame.tag, (0, 36), (400, 202))
        self.assertEqual(frame.globalPos().toTuple(), (74, 167))
        geometry = frame.globalGeometry()
        self.assertEqual((geometry.left(), geometry.top()), (74, 167))
        # Size keeps the renderer's rect_size provider; position is the part
        # that reconstruction must fix.

    def test_nested_child_windows_sum_every_window_ancestor(self):
        from DearUIQt.widgets import QFrame
        backend = ReconstructingBackend()
        main = backend.add_window()
        backend.set_window_state(main, (74, 131), (834, 581))
        shell = QFrame(parent=main, backend=backend)
        backend.set_window_state(shell.tag, (8, 32), (817, 540))
        pane = QFrame(parent=shell.tag, backend=backend)
        backend.set_window_state(pane.tag, (0, 0), (400, 202))
        self.assertEqual(pane.globalPos().toTuple(), (82, 163))

    def test_direct_rect_wins_when_parent_chain_leaves_root(self):
        from DearUIQt.widgets import QFrame
        backend = ReconstructingBackend()
        holder = QFrame(backend=backend)
        backend.set_window_state(holder.tag, (0, 0), (200, 100))
        widget = QFrame(parent=holder.tag, backend=backend)
        # A root-level child window's own pos is already absolute; nothing
        # above it contributes offsets.
        self.assertEqual(widget.globalPos().toTuple(), (0, 0))

    def test_fake_backends_without_window_info_keep_old_fallback(self):
        from DearUIQt.widgets import QFrame
        backend = FakeBackend()
        holder = backend.add_child_window()
        widget = QFrame(parent=holder, backend=backend)
        # FakeBackend provides no item info/parent: the direct rect fallback
        # must still answer so older adapters keep working.
        self.assertEqual(widget.globalPos().toTuple(), (0, 0))


if __name__ == "__main__":
    unittest.main()
