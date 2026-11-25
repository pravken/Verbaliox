"""Loading GigaAM / Parakeet (app/asr_onnx._load): an installation without the files of the variants loads offline.
Nothing is downloaded: the resolvers of onnx-asr and the library itself are fakes."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from app import asr_onnx


def _fake_onnx_asr(load_model=None):
    fake = types.ModuleType("onnx_asr")
    fake.load_model = mock.Mock(side_effect=load_model or (lambda *a, **k: mock.Mock()))
    fake.load_vad = mock.Mock(return_value="vad")
    return fake


class _Resolvers:
    """onnx_asr.loader with resolvers that only record what they were asked; without the network (`online` False)
    a file that is not on disk fails as it would."""

    def __init__(self, on_disk):
        self.on_disk = set(on_disk)  # (onnx name, quantization)
        self.online = False
        self.asked = []
        self.module = types.ModuleType("onnx_asr.loader")
        self.module.create_asr_resolver = self._resolver
        self.module.create_vad_resolver = lambda name, path, offline=False: self._resolver(name, path, offline)

    def _resolver(self, name, path, offline=False):
        outer = self

        class R:
            repo_id = "istupakov/gigaam-v3-onnx"

            def resolve_model(self, quantization=None):
                outer.asked.append((name, quantization, offline))
                if (name, quantization) in outer.on_disk:
                    return {}
                if offline or not outer.online:
                    raise FileNotFoundError(f"{name} {quantization}: no network")
                outer.on_disk.add((name, quantization))
                return {}

        return R()


class OfflineLoadTest(unittest.TestCase):
    """An installation of 0.9.3 (no int8 files) without internet: GigaAM loads from its main files; the int8 come in
    the background only, and their failure leaves the main model working."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "gigaam-v3").mkdir()
        (self.dir / "gigaam-v3" / "v3_e2e_rnnt_encoder.onnx").write_bytes(b"x")
        (self.dir / "vad").mkdir()
        (self.dir / "vad" / "silero_vad.onnx").write_bytes(b"x")
        self.res = _Resolvers({("gigaam-v3-e2e-rnnt", None), ("silero", None)})
        self.fake = _fake_onnx_asr()
        for p in (mock.patch.object(asr_onnx, "model_dir", lambda mid: self.dir / mid),
                  mock.patch.object(asr_onnx, "_vad_dir", lambda: self.dir / "vad"),
                  mock.patch.object(asr_onnx, "_present", set()),
                  mock.patch.object(asr_onnx, "_pinned", lambda r: r),
                  mock.patch.object(asr_onnx, "ensure_package"),
                  mock.patch.object(asr_onnx, "queue_threads", return_value=4),
                  mock.patch.dict(sys.modules, {"onnx_asr": self.fake, "onnx_asr.loader": self.res.module}),
                  mock.patch.dict(asr_onnx._loaded, {}, clear=True), mock.patch.dict(asr_onnx._made, {}, clear=True),
                  mock.patch.dict(asr_onnx._plain, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_the_first_load_after_a_start_needs_no_network(self):
        with mock.patch.object(asr_onnx, "_complete_async") as complete:
            asr_onnx._load("gigaam-v3")
            asr_onnx._load("gigaam-v3", live=True)
        complete.assert_called_with("gigaam-v3")  # the int8 files: in the background
        self.assertNotIn(("gigaam-v3-e2e-ctc", "int8"), [a[:2] for a in self.res.asked])
        self.assertNotIn(("gigaam-v3-e2e-rnnt", "int8"), [a[:2] for a in self.res.asked])
        got = [(c.args[0], c.kwargs.get("quantization")) for c in self.fake.load_model.call_args_list]
        self.assertEqual(got, [("gigaam-v3-e2e-rnnt", None), ("gigaam-v3-e2e-rnnt", None)])  # fp32 meanwhile

    def test_the_first_load_does_not_wait_for_the_download_of_the_variants(self):
        with asr_onnx._fetch_lock:  # _complete_async downloads 0.45 GB under it
            done = threading.Event()

            def load():
                with mock.patch.object(asr_onnx, "_complete_async"):
                    asr_onnx._load("gigaam-v3")
                done.set()

            threading.Thread(target=load, daemon=True).start()
            self.assertTrue(done.wait(3))

    def test_missing_main_files_are_fetched_without_the_variants(self):
        self.res.on_disk.discard(("gigaam-v3-e2e-rnnt", None))
        self.res.online = True
        with mock.patch.object(asr_onnx, "_complete_async"):
            asr_onnx._load("gigaam-v3")
        online = [a[:2] for a in self.res.asked if not a[2]]
        self.assertIn(("gigaam-v3-e2e-rnnt", None), online)
        self.assertNotIn(("gigaam-v3-e2e-ctc", "int8"), online)

    def test_a_variant_that_fails_leaves_the_main_model(self):
        self.assertFalse(asr_onnx.fetch("gigaam-v3"))  # offline: the int8 files fail, nothing is raised
        self.res.online = True
        self.assertTrue(asr_onnx.fetch("gigaam-v3"))
        self.assertIn(("gigaam-v3-e2e-ctc", "int8"), self.res.on_disk)


if __name__ == "__main__":
    unittest.main()
