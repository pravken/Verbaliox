"""Studio recordings: the system audio and the microphone line up."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest


class RecordingLineUpTest(unittest.TestCase):
    """The system audio and the microphone of a studio recording line up (app/main.record_mix_command,
    app/system_audio.silence_to_add): a voice heard by both no longer comes twice, one late."""

    def test_the_early_start_of_the_system_audio_is_left_out(self):
        from pathlib import Path

        from app.main import record_mix_command

        cmd = record_mix_command("ffmpeg", Path("page.webm"), Path("sys.wav"), False, True, Path("out.m4a"), 1.25)
        i = cmd.index("sys.wav")
        self.assertEqual(cmd[i - 3:i - 1], ["-ss", "1.250"])
        self.assertNotIn("-ss", cmd[:cmd.index("page.webm")])
        cmd = record_mix_command("ffmpeg", Path("page.webm"), Path("sys.wav"), False, True, Path("out.m4a"))
        self.assertNotIn("-ss", cmd)

    def test_a_pause_the_loopback_skipped_is_written_as_silence(self):
        from app.system_audio import BLOCK, SR, silence_to_add

        self.assertEqual(silence_to_add(1.0, SR - BLOCK, BLOCK), 0)  # in step with the clock
        self.assertEqual(silence_to_add(10.0, SR, BLOCK), 9 * SR - BLOCK)  # 9 s of nothing before this block


class EchoCancelTest(unittest.TestCase):
    """The speakers' echo is taken out of the microphone (app/echo_cancel.py), the user's voice stays."""

    @staticmethod
    def _voice(n, sr, seed, ranges):
        import numpy as np

        r = np.random.default_rng(seed)
        x = np.convolve(r.standard_normal(n), np.ones(6) / 6, mode="same").astype(np.float32)
        env = np.zeros(n, np.float32)
        for a, b in ranges:
            env[int(a * sr):int(b * sr)] = 1
        t = np.arange(n) / sr
        return (x * env * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t + seed) ** 2) * 0.2).astype(np.float32)

    def test_echo_goes_and_the_voice_stays(self):
        import numpy as np

        from app import echo_cancel as ec

        sr, n = ec.SR, 60 * ec.SR
        far = self._voice(n, sr, 1, [(0, 15), (25, 40), (45, 50)])
        near = self._voice(n, sr, 2, [(15, 25), (40, 50), (52, 58)])  # 45-50: both talk
        rng = np.random.default_rng(3)
        h = (rng.standard_normal(1200) * np.exp(-np.arange(1200) / 300)).astype(np.float32)
        h *= 0.35 / np.sqrt(np.sum(h ** 2))
        echo = np.concatenate([np.zeros(int(0.15 * sr), np.float32), np.convolve(far, h)])[:n]
        out = ec.cancel(near + echo, far)
        self.assertIsNotNone(out)
        db = lambda a: 10 * np.log10(np.mean(a ** 2) + 1e-12)  # noqa: E731
        far_only, near_only = slice(30 * sr, 39 * sr), slice(53 * sr, 57 * sr)
        self.assertLess(db(out[far_only]) - db(echo[far_only]), -20)  # the echo is 20 dB lower at least
        self.assertGreater(np.corrcoef(out[near_only], near[near_only])[0, 1], 0.98)
        self.assertLess(abs(db(out[near_only]) - db(near[near_only])), 1.0)

    def test_nothing_is_done_without_an_echo(self):
        from app import echo_cancel as ec

        n = 40 * ec.SR
        far = self._voice(n, ec.SR, 1, [(0, 20)])
        near = self._voice(n, ec.SR, 2, [(20, 38)])
        self.assertIsNone(ec.cancel(near, far))  # headphones: the recording stays as it is

    def test_the_cleaned_microphone_is_mixed_instead_of_the_page_sound(self):
        from pathlib import Path

        from app.main import record_mix_command

        cmd = record_mix_command("ffmpeg", Path("page.webm"), Path("sys.wav"), False, True, Path("out.m4a"), 0.5,
                                 mic=Path("mic.wav"))
        self.assertIn("mic.wav", cmd)
        self.assertNotIn("page.webm", cmd)
        cmd = record_mix_command("ffmpeg", Path("page.webm"), Path("sys.wav"), True, True, Path("out.webm"), 0.5,
                                 mic=Path("mic.wav"))
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:v")  # the picture still comes from the page
        self.assertIn("[2:a][1:a]amix", " ".join(cmd))


if __name__ == "__main__":
    unittest.main()
