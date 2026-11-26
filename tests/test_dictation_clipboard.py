"""Dictation's clipboard write (app/dictation._write_clipboard) with Windows' functions faked: nothing is
written through a NULL pointer (the process crashed), and every block the clipboard did not take is freed
(found in an audit: a busy clipboard leaked it)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import ctypes
import unittest

from app import dictation


class _Kernel32:
    def __init__(self, alloc_ok=True, lock_ok=True):
        self.alloc_ok, self.lock_ok = alloc_ok, lock_ok
        self.blocks = {}  # handle -> buffer
        self.freed = []
        self.next = 0x1000

    def GlobalAlloc(self, flags, size):
        if not self.alloc_ok:
            return 0
        self.next += 8
        self.blocks[self.next] = ctypes.create_string_buffer(size)
        return self.next

    def GlobalLock(self, h):
        return ctypes.addressof(self.blocks[h]) if self.lock_ok else 0

    def GlobalUnlock(self, h):
        return 1

    def GlobalFree(self, h):
        self.freed.append(h)
        return 0


class _User32:
    def __init__(self, open_ok=True, set_ok=True):
        self.open_ok, self.set_ok = open_ok, set_ok
        self.data = {}
        self.closed = 0

    def OpenClipboard(self, _hwnd):
        return 1 if self.open_ok else 0

    def EmptyClipboard(self):
        self.data.clear()
        return 1

    def SetClipboardData(self, fmt, h):
        if not self.set_ok:
            return 0
        self.data[fmt] = h
        return h

    def RegisterClipboardFormatW(self, name):
        return {"CanIncludeInClipboardHistory": 0xC100, "CanUploadToCloudClipboard": 0xC101}[name]

    def CloseClipboard(self):
        self.closed += 1
        return 1


class ClipboardWriteTest(unittest.TestCase):
    def test_the_text_goes_in_and_stays_out_of_the_history(self):
        k, u = _Kernel32(), _User32()
        self.assertTrue(dictation._write_clipboard(u, k, "Привет"))
        self.assertEqual(k.blocks[u.data[13]].raw, "Привет\0".encode("utf-16-le"))
        self.assertEqual(k.blocks[u.data[0xC100]].raw, b"\0\0\0\0")
        self.assertEqual(k.freed, [])  # taken by the clipboard: Windows frees them
        self.assertEqual(u.closed, 1)

    def test_no_memory(self):
        k, u = _Kernel32(alloc_ok=False), _User32()
        self.assertFalse(dictation._write_clipboard(u, k, "текст"))
        self.assertEqual(u.data, {})

    def test_a_block_that_cannot_be_locked_is_freed(self):
        k, u = _Kernel32(lock_ok=False), _User32()
        self.assertFalse(dictation._write_clipboard(u, k, "текст"))
        self.assertEqual(k.freed, list(k.blocks))

    def test_a_busy_clipboard_frees_the_block(self):
        k, u = _Kernel32(), _User32(open_ok=False)
        self.assertFalse(dictation._write_clipboard(u, k, "текст", tries=2))
        self.assertEqual(k.freed, list(k.blocks))
        self.assertEqual(u.closed, 0)

    def test_a_block_the_clipboard_refused_is_freed(self):
        k, u = _Kernel32(), _User32(set_ok=False)
        self.assertFalse(dictation._write_clipboard(u, k, "текст"))
        self.assertEqual(k.freed, list(k.blocks))
        self.assertEqual(u.closed, 1)


if __name__ == "__main__":
    unittest.main()
