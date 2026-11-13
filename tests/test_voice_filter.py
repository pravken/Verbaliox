"""The microphone cleaned by DeepFilterNet (app/voice_filter.py) when the recording is mixed."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import voice_filter as vf


class VoiceFilterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "page.webm"
        self.src.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_is_done_without_the_filter(self):
        with mock.patch.object(vf, "find_exe", return_value=None):
            self.assertFalse(vf.clean("ffmpeg", self.src, self.dir / "out.wav"))

    def test_the_cleaned_voice_is_written_with_the_delay_made_up(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "ffmpeg":
                Path(cmd[-1]).write_bytes(b"raw")
            else:  # deep-filter -D -a N -o OUT IN: writes OUT/<name of IN>
                out = Path(cmd[cmd.index("-o") + 1])
                out.mkdir(parents=True, exist_ok=True)
                (out / Path(cmd[-1]).name).write_bytes(b"clean")
            return mock.Mock(returncode=0, stderr=b"", stdout=b"")

        dest = self.dir / "voice.wav"
        with mock.patch.object(vf, "find_exe", return_value="deep-filter"), mock.patch.object(vf.subprocess, "run", run):
            self.assertTrue(vf.clean("ffmpeg", self.src, dest))
        self.assertEqual(dest.read_bytes(), b"clean")
        self.assertIn("48000", calls[0])                  # 48 kHz mono for the network
        self.assertIn("-D", calls[1])                     # no shift against the system sound
        self.assertEqual(calls[1][calls[1].index("-a") + 1], str(vf.ATTEN_DB))

    def test_a_failure_keeps_the_recording_as_it_was(self):
        with mock.patch.object(vf, "find_exe", return_value="deep-filter"), \
                mock.patch.object(vf.subprocess, "run", return_value=mock.Mock(returncode=1, stderr=b"boom", stdout=b"")):
            self.assertFalse(vf.clean("ffmpeg", self.src, self.dir / "voice.wav"))
        self.assertFalse((self.dir / "voice.wav").exists())

    def test_the_microphone_alone_is_mixed_from_the_cleaned_voice(self):
        from app.main import record_mix_command

        cmd = record_mix_command("ffmpeg", Path("page.webm"), None, False, True, Path("out.m4a"), mic=Path("voice.wav"))
        self.assertEqual(cmd[cmd.index("-i") + 1], "voice.wav")


if __name__ == "__main__":
    unittest.main()
