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


if __name__ == "__main__":
    unittest.main()
