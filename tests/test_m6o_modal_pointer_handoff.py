import unittest
from DearUIQt import input_gate

class Node:
    def __init__(self, parent=None): self.parent = parent

class M6oModalPointerHandoffTests(unittest.TestCase):
    def tearDown(self): input_gate.reset_pointer_input_gate()

    def test_release_subtree_releases_descendant_capture(self):
        root = Node(); child = Node(root)
        self.assertTrue(input_gate.acquire_pointer_input(child))
        self.assertIs(input_gate.pointer_input_owner(), child)
        self.assertTrue(input_gate.release_pointer_input_subtree(root))
        self.assertIsNone(input_gate.pointer_input_owner())

    def test_release_subtree_preserves_sibling_capture(self):
        root = Node(); sibling = Node()
        self.assertTrue(input_gate.acquire_pointer_input(sibling))
        self.assertFalse(input_gate.release_pointer_input_subtree(root))
        self.assertIs(input_gate.pointer_input_owner(), sibling)

    def test_release_subtree_handles_callable_parent(self):
        root = Node()
        class Child:
            def parent(self): return root
        child = Child()
        self.assertTrue(input_gate.acquire_pointer_input(child))
        self.assertTrue(input_gate.release_pointer_input_subtree(root))
        self.assertIsNone(input_gate.pointer_input_owner())

if __name__ == '__main__': unittest.main()
