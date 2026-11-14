"""The echo of the speakers removed piece by piece (app/echo_cancel.py): the same result as all at once,
with memory that does not grow with the recording."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
    import soundfile as sf

    from app import echo_cancel
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    echo_cancel = None


@unittest.skipIf(echo_cancel is None or not shutil.which("ffmpeg"), "ffmpeg is missing here")
class EchoChunksTest(unittest.TestCase):
    def test_pieces_give_the_same_microphone_as_the_whole(self):
        sr = 48000
        rng = np.random.default_rng(3)
        n = sr * 40
        env = (np.sin(np.arange(n) / sr * 2 * np.pi * 0.7) > 0).astype(np.float32)
        system = rng.standard_normal(n).astype(np.float32) * 0.2 * env
        delay = int(0.35 * sr)
        mic = np.concatenate([np.zeros(delay, np.float32), system[:-delay]]) * 0.4
        mic += (rng.standard_normal(n) * 0.05 * (1 - env)).astype(np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            sf.write(d / "sys.wav", np.stack([system, system], 1), sr)
            sf.write(d / "mic.wav", mic, sr)
            whole_mic = echo_cancel._decode("ffmpeg", d / "mic.wav")
            whole_sys = echo_cancel._decode("ffmpeg", d / "sys.wav")
            expected, in_room = echo_cancel.cancel_and_align(whole_mic, whole_sys)
            seen = []
            with mock.patch.object(echo_cancel, "CHUNK_SEC", 7):
                self.assertTrue(echo_cancel.clean_microphone("ffmpeg", d / "mic.wav", d / "sys.wav", 0.0, d / "out.wav",
                                                             d / "sys_out.wav", progress=seen.append))
            got, _ = sf.read(d / "out.wav", dtype="float32")
            self.assertEqual(len(got), len(expected))
            self.assertLess(float(np.max(np.abs(got - np.clip(expected, -1, 1)))), 1e-3)  # 16-bit rounding only
            self.assertEqual(seen[-1], 1.0)
            self.assertGreater(len(seen), 4)
            self.assertFalse(list(d.glob(".echo_*")))  # the samples on disk are gone


if __name__ == "__main__":
    unittest.main()
