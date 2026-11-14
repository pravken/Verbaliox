"""The computer's sound follows the output device Windows uses: a headset plugged in mid-call moved
the call's sound to it, and the loopback of the old device recorded silence (app/system_audio.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
    import soundfile as sf

    from app import system_audio
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    system_audio = None


class _Rec:
    def __init__(self, dev):
        self.dev = dev

    def __enter__(self):
        self.dev.opened += 1
        return self

    def __exit__(self, *a):
        self.dev.closed += 1

    def record(self, numframes):
        time.sleep(numframes / 48000)
        if self.dev.gone:
            raise RuntimeError("device unplugged")
        return np.full((numframes, 2), self.dev.value, dtype=np.float32)


class _Dev:
    def __init__(self, id_, value):
        self.id, self.name, self.value = id_, f"Device {id_}", value
        self.opened = self.closed = 0
        self.gone = False

    def recorder(self, **kw):
        return _Rec(self)


@unittest.skipIf(system_audio is None, "app dependencies not installed")
class DeviceChangeTest(unittest.TestCase):
    def test_the_recording_moves_to_the_new_output_device(self):
        speakers, mics = _Dev("A", 0.1), {}
        current = {"dev": speakers}
        b = _Dev("B", 0.5)
        devices = {"A": speakers, "B": b}
        fake = types.SimpleNamespace(default_speaker=lambda: current["dev"],
                                     get_microphone=lambda id, include_loopback: devices[id])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"soundcard": fake}), \
                mock.patch.object(system_audio, "DEVICE_CHECK_SEC", 0.2):
            cap = system_audio.SystemCapture(Path(tmp) / "sys.wav")
            cap.start()
            time.sleep(0.6)
            current["dev"] = b  # a headset plugged in
            time.sleep(0.8)
            cap.stop()
            data, sr = sf.read(str(cap.path), dtype="float32")
        self.assertEqual(cap.switches, 1)
        self.assertGreater(b.opened, 0)
        self.assertEqual(speakers.closed, 1)
        self.assertAlmostEqual(float(data[0, 0]), 0.1, places=3)
        self.assertAlmostEqual(float(data[-1, 0]), 0.5, places=3)  # the new device's sound at the end
        self.assertAlmostEqual(len(data) / sr, 1.4, delta=0.35)  # kept to the clock across the move

    def test_an_unplugged_device_gives_silence_until_another_comes(self):
        a = _Dev("A", 0.2)
        current = {"dev": a}
        fake = types.SimpleNamespace(default_speaker=lambda: current["dev"],
                                     get_microphone=lambda id, include_loopback: {"A": a}[id])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"soundcard": fake}), \
                mock.patch.object(system_audio, "DEVICE_CHECK_SEC", 0.2):
            cap = system_audio.SystemCapture(Path(tmp) / "sys.wav")
            cap.start()
            time.sleep(0.4)
            a.gone = True

            def none():
                raise RuntimeError("no device")
            fake.default_speaker = none
            time.sleep(0.6)
            cap.stop()
            data, sr = sf.read(str(cap.path), dtype="float32")
        self.assertEqual(cap.error, "")
        self.assertAlmostEqual(float(data[-1, 0]), 0.0)
        self.assertGreater(len(data) / sr, 0.8)


if __name__ == "__main__":
    unittest.main()
