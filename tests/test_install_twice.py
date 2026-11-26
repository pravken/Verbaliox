"""A second «Установить» while the first install runs (or the install started with the app) answers with the
state: status() takes the module's lock, and was asked under it — the request hung for good (found in an audit)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import threading
import unittest
from unittest import mock

from app import nemotron_diar, onnx_gpu


class InstallTwiceTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def _second_click(self, module):
        out = {}
        t = threading.Thread(target=lambda: out.update(st=module.install_async()), daemon=True)
        with mock.patch.dict(module._state, {"installing": True}):
            t.start()
            t.join(timeout=5)
            acquired = module._lock.acquire(timeout=1)
            if acquired:
                module._lock.release()
        self.assertFalse(t.is_alive(), "install_async hung on its own lock")
        self.assertTrue(acquired, "the lock was left held")
        self.assertTrue(out["st"]["installing"])

    def test_onnx_gpu(self):
        self._second_click(onnx_gpu)

    def test_nemotron(self):
        self._second_click(nemotron_diar)


if __name__ == "__main__":
    unittest.main()
