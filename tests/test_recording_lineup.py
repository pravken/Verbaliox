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

    def test_echo_goes_after_the_system_sound_jumps(self):
        """The system track jumped against the microphone half way (Windows lost a piece of it): the echo
        is followed past the jump, not left in the second half."""
        import numpy as np

        from app import echo_cancel as ec

        sr, n = ec.SR, 90 * ec.SR
        far = self._voice(n, sr, 1, [(0, 40), (50, 88)])
        near = self._voice(n, sr, 2, [(40, 50)])
        rng = np.random.default_rng(3)
        h = (rng.standard_normal(1200) * np.exp(-np.arange(1200) / 300)).astype(np.float32)
        h *= 0.35 / np.sqrt(np.sum(h ** 2))
        room = np.convolve(far, h)[:n]
        echo = np.zeros(n, np.float32)
        cut = 45 * sr
        d1, d2 = int(0.15 * sr), int(0.55 * sr)
        echo[d1:cut] = room[:cut - d1]
        echo[cut:] = room[cut - d2:n - d2]  # from 45 s the echo comes 0.4 s later
        out = ec.cancel(near + echo, far)
        self.assertIsNotNone(out)
        db = lambda a: 10 * np.log10(np.mean(a ** 2) + 1e-12)  # noqa: E731
        late = slice(60 * sr, 85 * sr)
        self.assertLess(db(out[late]) - db(echo[late]), -15)

    def test_the_system_sound_is_put_where_the_microphone_heard_it(self):
        """The tracks began 0.8 s apart (as the page and the app told it): the mix gets the system
        sound moved there, so whatever echo is left does not sound like a second voice."""
        import numpy as np

        from app import echo_cancel as ec

        sr, n = ec.SR, 40 * ec.SR
        far = self._voice(n, sr, 1, [(0, 30)])
        d = int(0.8 * sr)
        echo = np.concatenate([np.zeros(d, np.float32), 0.3 * far[:-d]])
        done = ec.cancel_and_align(echo, far)
        self.assertIsNotNone(done)
        _, in_room = done
        part = slice(5 * sr, 25 * sr)
        self.assertGreater(np.corrcoef(in_room[part], echo[part])[0, 1], 0.95)

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


class LiveSystemSoundTest(unittest.TestCase):
    def test_captions_get_the_system_sound_of_now_not_a_backlog(self):
        import threading

        import numpy as np

        from app.system_audio import SystemCapture

        cap = SystemCapture.__new__(SystemCapture)
        cap._live_lock = threading.Lock()
        cap._live = np.arange(16000 * 30, dtype=np.float32)  # captions switched on after 30 s of recording
        got = cap.take_live(1600)
        self.assertEqual(got[-1], 16000 * 30 - 1)  # the newest samples
        self.assertEqual(cap._live.size, 0)
        cap._live = np.arange(3000, dtype=np.float32)  # a little ahead (jitter): kept in order
        self.assertEqual(cap.take_live(1600)[0], 0)


class PageChunksTest(unittest.TestCase):
    """The page's chunks are numbered: one sent again is written once, none out of its place."""

    def test_a_chunk_sent_twice_is_written_once(self):
        try:
            from fastapi.testclient import TestClient

            from app import main
        except ImportError:
            self.skipTest("app dependencies not installed")
        from app.database import init_db

        init_db()
        client = TestClient(main.app, base_url="http://127.0.0.1:8790")
        client.get(f"/?token={main.SESSION_TOKEN}")
        pid = client.post("/api/record/page/start").json()["page_id"]
        try:
            send = lambda seq, data: client.post(f"/api/record/page/{pid}/chunk", content=data,  # noqa: E731
                                                 headers={"X-Chunk-Seq": str(seq), "Content-Type": "application/octet-stream"})
            self.assertEqual(send(0, b"aaa").json()["size"], 3)
            self.assertTrue(send(0, b"aaa").json().get("duplicate"))  # its answer was lost: sent again
            self.assertEqual(send(2, b"ccc").status_code, 409)       # 1 is missing: not written out of place
            self.assertEqual(send(1, b"bbb").json()["size"], 6)
        finally:
            client.post(f"/api/record/page/{pid}/cancel")


class FinishInBackgroundTest(unittest.TestCase):
    """Stop returns at once with the recording «mixing»; it gets its file and is queued when mixed."""

    def test_the_recording_is_there_at_once_and_queued_when_mixed(self):
        import shutil
        import subprocess
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed")
        try:
            from fastapi.testclient import TestClient

            from app import main
            from app.api import recording
        except ImportError:
            self.skipTest("app dependencies not installed")
        from app.database import delete_meeting, get_meeting, init_db

        init_db()
        tmp = Path(tempfile.mkdtemp())
        sample = tmp / "s.webm"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-c:a", "libopus",
                        str(sample)], check=True)
        client = TestClient(main.app, base_url="http://127.0.0.1:8790")
        client.get(f"/?token={main.SESSION_TOKEN}")
        pid = client.post("/api/record/page/start").json()["page_id"]
        client.post(f"/api/record/page/{pid}/chunk", content=sample.read_bytes(), headers={"X-Chunk-Seq": "0"})
        with mock.patch.object(recording, "enqueue_meeting_job") as enqueue, \
                mock.patch("app.ffmpeg_manager.tool_cmd", return_value="ffmpeg"):
            r = client.post("/api/record/finish", json={"title": "Фоновое сведение", "page_id": pid, "has_mic": True,
                                                        "notes": "заметка"})
            self.assertEqual(r.status_code, 200, r.text)
            mid = r.json()["created"][0]["id"]
            self.addCleanup(delete_meeting, mid, True)
            for _ in range(100):
                m = get_meeting(mid)
                if m["status"] != "mixing":
                    break
                time.sleep(0.05)
        self.assertEqual(m["status"], "queued")
        self.assertTrue(Path(m["media_path"]).is_file())
        self.assertEqual(m["user_notes"], "заметка")
        enqueue.assert_called_once_with(mid)
