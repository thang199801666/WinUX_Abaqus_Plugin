"""Regression tests for QMenu closing-click pointer capture.

Run with::

    python -m unittest tests.test_popup_click_through
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from DearUIQt import input_gate


class PopupClickThroughTests(unittest.TestCase):
    def tearDown(self):
        input_gate.reset_pointer_input_gate()

    def test_popup_close_while_button_down_blocks_until_after_release(self):
        owner = object()
        state = {"down": True, "frame": 10}
        with patch.object(input_gate, "_mouse_button_down", side_effect=lambda: state["down"]), \
             patch.object(input_gate, "_frame_count", side_effect=lambda: state["frame"]):
            input_gate.acquire_popup_input(owner)
            self.assertTrue(input_gate.release_popup_input(owner, consume_gesture=True))

            # QMenu may hide on the click/down callback. The underlying view
            # must remain blocked for the rest of that physical gesture.
            self.assertTrue(input_gate.popup_input_is_blocked())
            state["frame"] = 11
            self.assertTrue(input_gate.pointer_input_is_blocked(object()))

            # The actual mouse-up is consumed, plus one render frame, matching
            # Qt-style implicit mouse capture and preventing release click-through.
            state["down"] = False
            state["frame"] = 12
            self.assertTrue(input_gate.popup_input_is_blocked())
            state["frame"] = 13
            self.assertTrue(input_gate.popup_input_is_blocked())
            state["frame"] = 14
            self.assertFalse(input_gate.popup_input_is_blocked())

    def test_popup_close_after_mouse_up_only_consumes_current_frame(self):
        owner = object()
        state = {"down": False, "frame": 20}
        with patch.object(input_gate, "_mouse_button_down", side_effect=lambda: state["down"]), \
             patch.object(input_gate, "_frame_count", side_effect=lambda: state["frame"]):
            input_gate.acquire_popup_input(owner)
            input_gate.release_popup_input(owner, consume_gesture=True)
            self.assertTrue(input_gate.popup_input_is_blocked())
            state["frame"] = 21
            self.assertFalse(input_gate.popup_input_is_blocked())

    def test_fresh_press_is_not_eaten_after_up_state_close(self):
        owner = object()
        state = {"down": False, "frame": 30}
        with patch.object(input_gate, "_mouse_button_down", side_effect=lambda: state["down"]), \
             patch.object(input_gate, "_frame_count", side_effect=lambda: state["frame"]):
            input_gate.acquire_popup_input(owner)
            input_gate.release_popup_input(owner, consume_gesture=True)
            self.assertTrue(input_gate.popup_input_is_blocked())

            # A later down-state after the close was already observed with the
            # button up is a new user click and must pass normally.
            state["down"] = True
            state["frame"] = 31
            self.assertFalse(input_gate.popup_input_is_blocked())


if __name__ == "__main__":
    unittest.main()
