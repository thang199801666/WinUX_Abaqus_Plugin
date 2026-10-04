"""Cursor and retention contracts shared by SSH console and job polling."""
import random
import unittest

from WinUx.runtime.text_buffer import BoundedTextBuffer


class BoundedTextBufferTests(unittest.TestCase):
    def test_eviction_keeps_monotonic_cursors_and_newest_characters(self):
        buffer = BoundedTextBuffer(7)
        self.assertEqual(buffer.append("abc"), 3)
        cursor = buffer.cursor()
        self.assertEqual(buffer.append("defghi"), 9)
        self.assertEqual(buffer.snapshot(), "cdefghi")
        self.assertEqual(buffer.read_since(cursor), "defghi")
        self.assertEqual(buffer.read_since(0), "cdefghi")
        self.assertEqual(buffer.read_since(9), "")
        self.assertEqual(buffer.read_since(100), "")

    def test_clear_does_not_reuse_offsets(self):
        buffer = BoundedTextBuffer(4)
        buffer.append("abcdef")
        buffer.clear()
        self.assertEqual((buffer.cursor(), len(buffer), buffer.snapshot()), (6, 0, ""))
        buffer.append("xy")
        self.assertEqual(buffer.cursor(), 8)
        self.assertEqual(buffer.read_since(6), "xy")
        self.assertEqual(buffer.read_since(0), "xy")

    def test_large_chunk_unicode_and_empty_appends(self):
        buffer = BoundedTextBuffer(3)
        self.assertEqual(buffer.append("abc\u03bb\U0001f600d"), 6)
        self.assertEqual(buffer.snapshot(), "\u03bb\U0001f600d")
        self.assertEqual(buffer.append(None), 6)
        self.assertEqual(buffer.append(""), 6)
        self.assertEqual(buffer.read_since(4), "\U0001f600d")

    def test_random_stream_matches_string_reference(self):
        rng = random.Random(42)
        buffer = BoundedTextBuffer(97)
        text, offset = "", 0
        for _ in range(500):
            if rng.randrange(20) == 0:
                offset += len(text)
                text = ""
                buffer.clear()
            else:
                chunk = "".join(rng.choice("ab\n\u03bb") for _ in range(rng.randrange(150)))
                text += chunk
                overflow = max(0, len(text) - 97)
                text = text[overflow:]
                offset += overflow
                buffer.append(chunk)
            self.assertEqual(buffer.snapshot(), text)
            self.assertEqual(buffer.cursor(), offset + len(text))
            self.assertEqual(len(buffer), len(text))
            for cursor in (0, offset - 1, offset, offset + 20, buffer.cursor(), buffer.cursor() + 1):
                self.assertEqual(buffer.read_since(cursor), text[max(0, cursor - offset):])

    def test_cursor_reads_cross_internal_chunks(self):
        buffer = BoundedTextBuffer(10_000)
        source = "abcdefghij" * 1_500
        buffer.append(source)
        cursor = buffer.cursor()
        buffer.append("tail")
        self.assertEqual(buffer.snapshot(), (source + "tail")[-10_000:])
        self.assertEqual(buffer.read_since(cursor), "tail")
        self.assertEqual(buffer.read_since(8_000), (source + "tail")[8_000:])


if __name__ == "__main__":
    unittest.main()
