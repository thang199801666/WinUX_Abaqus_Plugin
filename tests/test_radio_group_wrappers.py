import threading
import unittest
from unittest.mock import Mock

from WinUx.widgets import QRadioButtonGroup


class RadioGroupTests(unittest.TestCase):
    def fixture(self):
        pending = []
        backend = Mock()
        backend.add_radio_button.return_value = 11
        backend.does_item_exist.return_value = True
        widget = QRadioButtonGroup(
            ("Delete After", "Delete At"),
            current="Delete After",
            horizontal=True,
            backend=backend,
            after=lambda delay, cb, *args: pending.append((cb, args)),
        )
        return widget, backend, pending

    @staticmethod
    def drain(pending):
        while pending:
            callback, args = pending.pop(0)
            callback(*args)

    def test_native_group_keeps_items_value_and_horizontal_contract(self):
        group, backend, _ = self.fixture()
        call = backend.add_radio_button.call_args
        self.assertEqual(call.args[0], ["Delete After", "Delete At"])
        self.assertEqual(call.kwargs["default_value"], "Delete After")
        self.assertTrue(call.kwargs["horizontal"])
        self.assertEqual(group.items(), ("Delete After", "Delete At"))
        self.assertEqual(group.count(), 2)
        self.assertEqual(group.itemText(1), "Delete At")

    def test_programmatic_change_emits_text_and_index_but_not_activated(self):
        group, backend, _ = self.fixture()
        texts, indexes, activated = [], [], []
        group.currentTextChanged.connect(texts.append)
        group.currentIndexChanged.connect(indexes.append)
        group.activated.connect(activated.append)
        self.assertTrue(group.setCurrentIndex(1))
        backend.set_value.assert_called_once_with(11, "Delete At")
        self.assertEqual(texts, ["Delete At"])
        self.assertEqual(indexes, [1])
        self.assertEqual(activated, [])
        self.assertFalse(group.setCurrentIndex(9))
        self.assertFalse(group.setCurrentText("Unknown"))

    def test_user_change_emits_activation_and_invalidates_queued_worker_value(self):
        group, backend, pending = self.fixture()
        activated = []
        group.activated.connect(activated.append)
        worker = threading.Thread(target=group.setCurrentText, args=("Delete At",))
        worker.start()
        worker.join()
        group._changed(11, "Delete After")
        self.drain(pending)
        backend.set_value.assert_not_called()
        self.assertEqual(activated, ["Delete After"])

    def test_ui_getters_read_native_value(self):
        group, backend, _ = self.fixture()
        backend.get_value.return_value = "Delete At"
        self.assertEqual(group.currentText(), "Delete At")
        self.assertEqual(group.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main()
