"""Renderer ownership writes must be idempotent without blocking real changes."""
import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.backends.native_owner_sync import _import_slot, _owner_setter


class OwnerSetterTests(unittest.TestCase):
    def setUp(self):
        self.original = Mock(return_value=123)
        self.getter = Mock(return_value=123)
        self.valid = Mock(return_value=True)
        self.clear = Mock()
        self.setter = _owner_setter(self.original, self.getter, self.valid, self.clear)

    def test_unchanged_owner_is_not_rewritten(self):
        self.assertEqual(self.setter(10, -8, 123), 123)
        self.original.assert_not_called()
        self.clear.assert_called_once_with(0)

    def test_real_owner_change_is_forwarded(self):
        self.assertEqual(self.setter(10, -8, 456), 123)
        self.original.assert_called_once_with(10, -8, 456)
        self.clear.assert_not_called()

    def test_null_owner_is_idempotent(self):
        self.getter.return_value = 0
        self.assertEqual(self.setter(10, -8, 0), 0)
        self.original.assert_not_called()

    def test_owner_removal_is_forwarded(self):
        self.setter(10, -8, 0)
        self.original.assert_called_once_with(10, -8, 0)

    def test_invalid_window_preserves_native_failure(self):
        self.valid.return_value = False
        self.getter.return_value = 0
        self.setter(10, -8, 0)
        self.original.assert_called_once_with(10, -8, 0)
        self.getter.assert_not_called()

    def test_style_and_wndproc_writes_are_untouched(self):
        for index in (-16, -20, -4):
            self.setter(10, index, 123)
            self.original.assert_called_with(10, index, 123)
        self.getter.assert_not_called()


class ImportSlotTests(unittest.TestCase):
    def setUp(self):
        self.image = ctypes.create_string_buffer(4096)
        self.base = ctypes.addressof(self.image)
        self.put16(0, 0x5A4D)
        self.put32(60, 128)
        self.put32(128, 0x4550)
        self.put16(152, 0x20B)
        self.put32(208, 4096)
        self.put32(272, 512)
        self.put32(276, 40)
        self.put32(512, 768)
        self.put32(524, 640)
        self.put32(528, 800)
        ctypes.memmove(self.base + 640, b'USER32.dll\0', 11)
        ctypes.c_uint64.from_address(self.base + 768).value = 1024
        ctypes.memmove(self.base + 1026, b'SetWindowLongPtrW\0', 18)

    def put16(self, offset, value):
        ctypes.c_uint16.from_address(self.base + offset).value = value

    def put32(self, offset, value):
        ctypes.c_uint32.from_address(self.base + offset).value = value

    def test_finds_named_import(self):
        self.assertEqual(_import_slot(self.base), self.base + 800)

    def test_rejects_unsupported_image(self):
        self.put16(152, 0x10B)
        self.assertIsNone(_import_slot(self.base))

    def test_rejects_directory_outside_image(self):
        self.put32(272, 4090)
        self.assertIsNone(_import_slot(self.base))

    def test_does_not_patch_other_dll(self):
        ctypes.memmove(self.base + 640, b'OTHER0.dll\0', 11)
        self.assertIsNone(_import_slot(self.base))

    def test_skips_ordinal_import(self):
        ctypes.c_uint64.from_address(self.base + 768).value = (1 << 63) | 7
        self.assertIsNone(_import_slot(self.base))


if __name__ == '__main__':
    unittest.main()
