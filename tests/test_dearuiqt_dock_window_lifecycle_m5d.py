import unittest

from DearUIQt.docking import QDockWindowLifecycle


class DockWindowLifecycleTests(unittest.TestCase):
    def test_docked_floating_moving_docked(self):
        life = QDockWindowLifecycle("docked", True)
        seen = []
        life.stateChanged.connect(lambda old, new: seen.append((old, new)))
        self.assertTrue(life.setMode("floating"))
        self.assertTrue(life.beginMove())
        self.assertTrue(life.endMove(docked=True))
        self.assertTrue(life.isDocked())
        self.assertFalse(life.isMoving())
        self.assertIn(("floating", "moving"), seen)

    def test_visibility_does_not_destroy_mode(self):
        life = QDockWindowLifecycle("floating", True)
        life.setVisible(False)
        self.assertEqual(life.state(), "hidden")
        self.assertTrue(life.isFloating())
        life.setVisible(True)
        self.assertEqual(life.state(), "floating")

    def test_move_transaction_owns_drop_target(self):
        life = QDockWindowLifecycle("floating", True)
        targets, finished = [], []
        life.dropTargetChanged.connect(lambda value: targets.append(value))
        life.moveFinished.connect(lambda value: finished.append(value))
        self.assertTrue(life.beginMove())
        self.assertTrue(life.setDropTarget("left", "outer"))
        self.assertEqual(life.dropTarget(), {"area": "left", "scope": "outer"})
        self.assertTrue(life.endMove(docked=True))
        self.assertTrue(life.isDocked())
        self.assertIsNone(life.dropTarget())
        self.assertEqual(finished[-1]["target"], {"area": "left", "scope": "outer"})
        self.assertEqual(targets[-1], None)

    def test_cancel_move_clears_semantic_target(self):
        life = QDockWindowLifecycle("floating", True)
        life.beginMove("right", "inner")
        self.assertTrue(life.isMoving())
        self.assertTrue(life.cancelMove(docked=False))
        self.assertFalse(life.isMoving())
        self.assertTrue(life.isFloating())
        self.assertIsNone(life.dropTarget())

    def test_geometry_is_normalized_and_copied(self):
        life = QDockWindowLifecycle()
        self.assertTrue(life.setGeometry({"pos": [10, 20], "size": [500, 300]}))
        value = life.geometry()
        self.assertEqual(value, {"pos": (10, 20), "size": (500, 300)})
        value["pos"] = (0, 0)
        self.assertEqual(life.geometry()["pos"], (10, 20))


if __name__ == '__main__':
    unittest.main()
